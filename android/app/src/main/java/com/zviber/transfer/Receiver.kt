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
import java.security.MessageDigest
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
 * 错误码：400 参数/会话无效，403 拒绝或 token 错误，409 会话冲突/状态不可写，422 sha256 校验失败，500 内部错误（含短读）。
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
        val remoteIp: String,
        val createdAt: Long = System.currentTimeMillis(),
    ) {
        @Volatile
        var state = SessionState.PENDING

        @Volatile
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
        if (request.files.isEmpty()) {
            return TransferServer.error(Status.BAD_REQUEST, "no files")
        }
        val ip = http.remoteIpAddress ?: ""
        DeviceStore.upsert(request.info, ip)

        purgeStaleSessions()

        val sessionId = UUID.randomUUID().toString()
        val tokens = request.files.keys.associateWith { randomToken() }
        val records = request.files.mapValues { (_, meta) ->
            TransferRecord(
                id = sessionId + ":" + meta.id,
                outgoing = false,
                peerAlias = request.info.alias,
                fileName = meta.fileName,
                size = meta.size,
            ).also { TransferStore.add(it) }
        }
        val decision = CompletableDeferred<Uri?>()
        val session = Session(sessionId, request.info, request.files.values.toList(), tokens, decision, records, ip)
        // PENDING 检查 + 插入必须原子，并发 prepare 不能双通过
        val inserted = synchronized(sessions) {
            if (sessions.values.any { it.state == SessionState.PENDING }) {
                false
            } else {
                sessions[sessionId] = session
                true
            }
        }
        if (!inserted) {
            records.values.forEach {
                it.status = TransferStatus.FAILED
                it.error = "会话冲突"
            }
            return TransferServer.error(Status.CONFLICT, "another session is waiting for confirmation")
        }

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
        val dir = try {
            runBlocking { withTimeoutOrNull(180_000) { decision.await() } }
        } finally {
            // 兜底：旋转/重建不留僵尸对话框与未完结 deferred
            IncomingState.clear(sessionId)
            decision.complete(null)
        }

        if (dir == null) {
            sessions.remove(sessionId)
            records.values.forEach { it.status = TransferStatus.REJECTED }
            return TransferServer.error(Status.FORBIDDEN, "rejected")
        }

        // 等待期间会话可能已被 cancel：不再覆盖状态、不再响应接受
        if (session.cancelled || !sessions.containsKey(sessionId)) {
            return TransferServer.error(Status.CONFLICT, "session cancelled")
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
            ?: return drainAndError(http, Status.BAD_REQUEST, "missing sessionId")
        val fileId = params["fileId"]?.firstOrNull()
            ?: return drainAndError(http, Status.BAD_REQUEST, "missing fileId")
        val token = params["token"]?.firstOrNull()
            ?: return drainAndError(http, Status.BAD_REQUEST, "missing token")

        val session = sessions[sessionId]
            ?: return drainAndError(http, Status.FORBIDDEN, "invalid session")
        val meta = session.files.firstOrNull { it.id == fileId }
            ?: return drainAndError(http, Status.BAD_REQUEST, "invalid fileId")
        if (session.tokens[fileId] != token) {
            return drainAndError(http, Status.FORBIDDEN, "invalid token")
        }
        // 来源 IP 必须与 prepare-upload 时一致
        if (session.remoteIp.isNotEmpty() && http.remoteIpAddress != session.remoteIp) {
            return drainAndError(http, Status.FORBIDDEN, "ip mismatch")
        }
        if (session.cancelled || session.state != SessionState.ACTIVE) {
            return drainAndError(http, Status.CONFLICT, "session not writable")
        }

        // 协议要求发送方必须知道长度：拒绝未知长度（chunked）的上传
        val contentLength = http.headers["content-length"]?.toLongOrNull() ?: -1L
        if (contentLength < 0) {
            return TransferServer.error(Status.BAD_REQUEST, "missing content-length")
        }

        val record = session.records.getValue(fileId)
        record.status = TransferStatus.TRANSFERRING

        val dir = DocumentFile.fromTreeUri(context, session.dirUri!!)
            ?: return fail(record, "save directory unavailable")
        val doc = createUniqueFile(dir, sanitizeName(meta.fileName))
            ?: return fail(record, "cannot create file")
        session.currentDoc = doc

        // 对端提供 sha256 时边写边算摘要
        val digest = if (meta.sha256.isNullOrEmpty()) null else MessageDigest.getInstance("SHA-256")
        var received = 0L
        try {
            context.contentResolver.openOutputStream(doc.uri, "w")?.use { out ->
                val input = http.inputStream
                val buffer = ByteArray(64 * 1024)
                var remaining = contentLength
                while (true) {
                    if (session.cancelled) throw CancelledException()
                    val want = if (remaining < 0) buffer.size else minOf(buffer.size.toLong(), remaining).toInt()
                    if (want == 0) break
                    val n = input.read(buffer, 0, want)
                    if (n < 0) break
                    out.write(buffer, 0, n)
                    digest?.update(buffer, 0, n)
                    if (remaining > 0) remaining -= n
                    received += n
                    record.progress = received
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

        // 短读校验：实收字节数必须等于 Content-Length，否则删除半成品回 500
        if (contentLength >= 0 && received != contentLength) {
            doc.delete()
            record.status = TransferStatus.FAILED
            record.error = "字节数不足：" + received + "/" + contentLength
            return TransferServer.error(Status.INTERNAL_ERROR, "incomplete body")
        }

        // sha256 校验：不匹配删文件回 422
        if (digest != null) {
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            if (!actual.equals(meta.sha256, ignoreCase = true)) {
                doc.delete()
                record.status = TransferStatus.FAILED
                record.error = "sha256 校验失败"
                return TransferServer.error(TransferServer.STATUS_422, "sha256 mismatch")
            }
        }

        record.progress = meta.size
        record.status = TransferStatus.DONE
        return TransferServer.jsonResponse(Status.OK, "")
    }

    /** POST /cancel?sessionId：中止会话并删除半成品 */
    fun handleCancel(http: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        val sessionId = http.parameters["sessionId"]?.firstOrNull()
            ?: return TransferServer.error(Status.BAD_REQUEST, "missing sessionId")
        val session = sessions[sessionId]
            ?: return TransferServer.jsonResponse(Status.OK, "") // 幂等：不存在的会话直接成功
        // 来源 IP 必须与 prepare-upload 时一致（与 upload 相同规则）
        if (session.remoteIp.isNotEmpty() && http.remoteIpAddress != session.remoteIp) {
            return TransferServer.error(Status.FORBIDDEN, "ip mismatch")
        }
        sessions.remove(sessionId)
        session.cancelled = true
        try { session.currentDoc?.delete() } catch (_: Exception) {}
        session.records.values.forEach {
            if (it.status != TransferStatus.DONE) it.status = TransferStatus.CANCELED
        }
        return TransferServer.jsonResponse(Status.OK, "")
    }

    // ---------- 内部工具 ----------

    private class CancelledException : Exception()

    /** 排空请求体剩余字节再回错误，避免过早响应触发 RST 冲掉错误码（对齐 PC 端 _drain_body） */
    private fun drainAndError(
        http: NanoHTTPD.IHTTPSession,
        status: NanoHTTPD.Response.IStatus,
        message: String,
    ): NanoHTTPD.Response {
        try {
            val len = http.headers["content-length"]?.toLongOrNull() ?: 0L
            if (len > 0) {
                val input = http.inputStream
                val buffer = ByteArray(64 * 1024)
                var remaining = len
                while (remaining > 0) {
                    val n = input.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
                    if (n < 0) break
                    remaining -= n
                }
            }
        } catch (_: Exception) {
        }
        return TransferServer.error(status, message)
    }

    /** 文件名消毒：剥掉路径分隔，防目录穿越 */
    private fun sanitizeName(name: String): String =
        name.substringAfterLast('/').substringAfterLast('\\').ifEmpty { "file" }

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
            .filter { it.state == SessionState.PENDING && now - it.createdAt > 10 * 60_000 }
            .forEach { sessions.remove(it.sessionId) }
    }

    private fun randomToken(): String = UUID.randomUUID().toString().replace("-", "")
}
