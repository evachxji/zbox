package com.zviber.transfer

import android.content.Context
import android.net.Uri
import android.webkit.MimeTypeMap
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.documentfile.provider.DocumentFile
import fi.iki.elonen.NanoHTTPD
import fi.iki.elonen.NanoHTTPD.Response.Status
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.encodeToString
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/** 等待用户确认的接收请求（驱动 ReceiveDialog） */
class PendingRequest(
    val sessionId: String,
    val fromAlias: String,
    val files: List<FileMeta>,
    val onAccept: (Uri) -> Unit,
    val onReject: () -> Unit,
) {
    var dirUri by mutableStateOf<Uri?>(null)
    val totalSize: Long get() = files.sumOf { it.size }
}

/** 当前待确认的接收请求（Compose 可观察） */
object IncomingState {
    var pending by mutableStateOf<PendingRequest?>(null)
        private set

    fun show(request: PendingRequest) {
        pending = request
    }

    fun clear(sessionId: String) {
        if (pending?.sessionId == sessionId) pending = null
    }
}

/**
 * 接收方核心：prepare-upload 会话状态机 + upload 流式写入 SAF 目录 + cancel 清理半成品。
 * 错误码：400 参数/会话无效，403 拒绝或 token 错误，409 已有会话等待确认，422 会话状态不可写，500 内部错误。
 */
class Receiver(private val context: Context) {

    private enum class SessionState { PENDING, ACTIVE }

    private class Session(
        val sessionId: String,
        val remote: DeviceInfo,
        val files: List<FileMeta>,
        val tokens: Map<String, String>,
        val decision: CompletableDeferred<Uri?>,
        val records: Map<String, TransferRecord>,
        val createdAt: Long = System.currentTimeMillis(),
    ) {
        var state = SessionState.PENDING
        var dirUri: Uri? = null

        @Volatile
        var cancelled = false

        @Volatile
        var currentDoc: DocumentFile? = null
    }

    private val sessions = ConcurrentHashMap<String, Session>()

    /** POST /prepare-upload */
    fun handlePrepare(http: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val body = TransferServer.readJsonBody(http)
            ?: return TransferServer.error(Status.BAD_REQUEST, "invalid body")
        val request = try {
            protoJson.decodeFromString<PrepareRequest>(body)
        } catch (_: Exception) {
            return TransferServer.error(Status.BAD_REQUEST, "invalid json")
        }
        val ip = http.remoteIpAddress ?: ""
        DeviceStore.upsert(request.info, ip)

        purgeStaleSessions()
        if (sessions.values.any { it.state == SessionState.PENDING }) {
            return TransferServer.error(Status.CONFLICT, "another session is waiting for confirmation")
        }

        val sessionId = UUID.randomUUID().toString()
        val tokens = request.files.keys.associateWith { randomToken() }
        val records = request.files.mapValues { (_, meta) ->
            TransferRecord(
                id = meta.id,
                outgoing = false,
                peerAlias = request.info.alias,
                fileName = meta.fileName,
                size = meta.size,
            ).also { TransferStore.add(it) }
        }
        val decision = CompletableDeferred<Uri?>()
        val session = Session(sessionId, request.info, request.files.values.toList(), tokens, decision, records)
        sessions[sessionId] = session

        IncomingState.show(
            PendingRequest(
                sessionId = sessionId,
                fromAlias = request.info.alias,
                files = session.files,
                onAccept = { uri -> decision.complete(uri) },
                onReject = { decision.complete(null) },
            )
        )

        // NanoHTTPD 工作线程上阻塞等待用户确认，最长 3 分钟
        val dir = runBlocking { withTimeoutOrNull(180_000) { decision.await() } }
        IncomingState.clear(sessionId)

        if (dir == null) {
            sessions.remove(sessionId)
            records.values.forEach { it.status = TransferStatus.REJECTED }
            return TransferServer.error(Status.FORBIDDEN, "rejected")
        }

        session.dirUri = dir
        session.state = SessionState.ACTIVE
        val payload = protoJson.encodeToString(PrepareResponse(sessionId, tokens))
        return TransferServer.jsonResponse(Status.OK, payload)
    }

    /** POST /upload?sessionId&fileId&token（body 为文件原始字节流） */
    fun handleUpload(http: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val params = http.parameters
        val sessionId = params["sessionId"]?.firstOrNull()
            ?: return TransferServer.error(Status.BAD_REQUEST, "missing sessionId")
        val fileId = params["fileId"]?.firstOrNull()
            ?: return TransferServer.error(Status.BAD_REQUEST, "missing fileId")
        val token = params["token"]?.firstOrNull()
            ?: return TransferServer.error(Status.BAD_REQUEST, "missing token")

        val session = sessions[sessionId]
            ?: return TransferServer.error(Status.BAD_REQUEST, "invalid session")
        val meta = session.files.firstOrNull { it.id == fileId }
            ?: return TransferServer.error(Status.BAD_REQUEST, "invalid fileId")
        if (session.tokens[fileId] != token) {
            return TransferServer.error(Status.FORBIDDEN, "invalid token")
        }
        if (session.cancelled || session.state != SessionState.ACTIVE) {
            return TransferServer.error(TransferServer.STATUS_422, "session not writable")
        }

        val record = session.records.getValue(fileId)
        record.status = TransferStatus.TRANSFERRING

        val dir = DocumentFile.fromTreeUri(context, session.dirUri!!)
            ?: return TransferServer.error(Status.INTERNAL_ERROR, "save directory unavailable")
        val doc = createUniqueFile(dir, meta.fileName)
            ?: return fail(record, "cannot create file")
        session.currentDoc = doc

        val contentLength = http.headers["content-length"]?.toLongOrNull() ?: -1L
        try {
            context.contentResolver.openOutputStream(doc.uri, "w")?.use { out ->
                val input = http.inputStream
                val buffer = ByteArray(64 * 1024)
                var remaining = contentLength
                while (true) {
                    val want = if (remaining < 0) buffer.size else minOf(buffer.size.toLong(), remaining).toInt()
                    if (want == 0) break
                    val n = input.read(buffer, 0, want)
                    if (n < 0) break
                    if (session.cancelled) throw CancelledException()
                    out.write(buffer, 0, n)
                    if (remaining > 0) remaining -= n
                    record.progress += n
                }
            } ?: return fail(record, "cannot open output stream")
        } catch (_: CancelledException) {
            doc.delete()
            record.status = TransferStatus.CANCELED
            return TransferServer.error(Status.BAD_REQUEST, "cancelled")
        } catch (e: Exception) {
            doc.delete()
            return fail(record, e.message ?: "write error")
        } finally {
            session.currentDoc = null
        }

        record.progress = meta.size
        record.status = TransferStatus.DONE
        return TransferServer.jsonResponse(Status.OK, "")
    }

    /** POST /cancel?sessionId：中止会话并删除半成品 */
    fun handleCancel(http: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val sessionId = http.parameters["sessionId"]?.firstOrNull()
            ?: return TransferServer.error(Status.BAD_REQUEST, "missing sessionId")
        val session = sessions.remove(sessionId)
            ?: return TransferServer.error(Status.BAD_REQUEST, "invalid session")
        session.cancelled = true
        try { session.currentDoc?.delete() } catch (_: Exception) {}
        session.records.values.forEach {
            if (it.status != TransferStatus.DONE) it.status = TransferStatus.CANCELED
        }
        return TransferServer.jsonResponse(Status.OK, "")
    }

    // ---------- 内部工具 ----------

    private class CancelledException : Exception()

    private fun fail(record: TransferRecord, message: String): NanoHTTPD.Response {
        record.status = TransferStatus.FAILED
        record.error = message
        return TransferServer.error(Status.INTERNAL_ERROR, message)
    }

    /** 在 SAF 目录中创建不重名的文件（同名加 " (2)" 后缀） */
    private fun createUniqueFile(dir: DocumentFile, fileName: String): DocumentFile? {
        val existing = dir.listFiles().mapNotNull { it.name }.toMutableSet()
        var candidate = fileName
        var index = 2
        while (candidate in existing) {
            val dot = fileName.lastIndexOf('.')
            candidate = if (dot > 0) {
                fileName.substring(0, dot) + " (" + index + ")" + fileName.substring(dot)
            } else {
                fileName + " (" + index + ")"
            }
            index++
        }
        val mime = mimeFromName(candidate)
        val created = dir.createFile(mime, candidate) ?: return null
        existing.add(candidate)
        return created
    }

    private fun mimeFromName(fileName: String): String {
        val ext = MimeTypeMap.getFileExtensionFromUrl(fileName)
        if (!ext.isNullOrEmpty()) {
            MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext.lowercase())?.let { return it }
        }
        return "application/octet-stream"
    }

    private fun purgeStaleSessions() {
        val now = System.currentTimeMillis()
        sessions.values
            .filter { now - it.createdAt > 10 * 60_000 }
            .forEach { sessions.remove(it.sessionId) }
    }

    private fun randomToken(): String = UUID.randomUUID().toString().replace("-", "")
}
