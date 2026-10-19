package com.zbox.transfer

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
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
    val onAccept: (Uri?) -> Unit,
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
        val record: TransferRecord,   // 整会话一条记录（对齐 PC 端）：总大小 + 聚合进度
        val remoteIp: String,
        val createdAt: Long = System.currentTimeMillis(),
    ) {
        @Volatile
        var state = SessionState.PENDING

        @Volatile
        var bytesDone = 0L        // 已完整落盘的累计字节（当前文件进度 = bytesDone + received）

        @Volatile
        var savedCount = 0        // 已完整落盘的文件数，== files.size 时记录转 DONE

        @Volatile
        var dirUri: Uri? = null

        @Volatile
        var cancelled = false

        @Volatile
        var currentTarget: SaveTarget? = null
    }

    private val sessions = ConcurrentHashMap<String, Session>()

    init {
        active = this
    }

    companion object {
        /** 运行中的接收实例（记录页长按取消接收用） */
        @Volatile
        var active: Receiver? = null
            private set
    }

    /** 是否有正在传输中的接收会话（供 MainActivity 判断退后台是否保持服务） */
    fun hasActive(): Boolean = sessions.values.any { it.state == SessionState.ACTIVE }

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
        val files = request.files.values.toList()
        val top = commonTopFolder(files)
        val first = files.first()
        val record = TransferRecord(
            id = sessionId,
            outgoing = false,
            peerAlias = request.info.alias,
            fileName = top
                ?: if (files.size == 1) (first.path?.takeIf { it.isNotBlank() } ?: first.fileName)
                else first.fileName,
            size = files.sumOf { it.size },
            multiCount = files.size,
            folderName = top,
        ).also { TransferStore.add(it) }
        val decision = CompletableDeferred<Uri?>()
        val session = Session(sessionId, request.info, files, tokens, decision, record, ip)
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
            record.status = TransferStatus.FAILED
            record.error = AppError.SESSION_CONFLICT
            return TransferServer.error(Status.CONFLICT, "another session is waiting for confirmation")
        }

        IncomingState.show(
            PendingRequest(
                sessionId = sessionId,
                fromAlias = request.info.alias,
                files = session.files,
                onAccept = { uri -> decision.complete(uri ?: Uri.EMPTY) },   // 未选目录 = 默认系统 Download
                onReject = { decision.complete(null) },
            )
        )

        // NanoHTTPD 工作线程上阻塞等待用户确认，最长 170 秒（比发送方 prepare 的 180 秒提前 10 秒，避免两头同值竞态）
        val dir = try {
            runBlocking { withTimeoutOrNull(170_000) { decision.await() } }
        } finally {
            // 兜底：旋转/重建不留僵尸对话框与未完结 deferred
            IncomingState.clear(sessionId)
            decision.complete(null)
        }

        if (dir == null) {
            sessions.remove(sessionId)
            record.status = TransferStatus.REJECTED
            return TransferServer.error(Status.FORBIDDEN, "rejected")
        }

        // 等待期间会话可能已被 cancel：不再覆盖状态、不再响应接受
        if (session.cancelled || !sessions.containsKey(sessionId)) {
            return TransferServer.error(Status.CONFLICT, "session cancelled")
        }

        session.dirUri = if (dir == Uri.EMPTY) null else dir   // null = 默认系统 Download
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

        val record = session.record
        record.status = TransferStatus.TRANSFERRING

        // 保存目标：用户选定目录（SAF）；未选则默认系统 Download（MediaStore）
        // 文件夹传输：path 分段消毒后还原目录树（目录冲突=合并）；无有效段退回扁平逻辑
        val relParts = safeRelParts(meta.path)
        val fileName = if (relParts.isNotEmpty()) relParts.last() else sanitizeName(meta.fileName)
        val dirParts = if (relParts.size > 1) relParts.dropLast(1) else emptyList()
        val target = openSaveTarget(session.dirUri, fileName, meta.fileType, dirParts)
            ?: return fail(record, AppError.UNKNOWN, "cannot create file")
        session.currentTarget = target

        // 对端提供 sha256 时边写边算摘要
        val digest = if (meta.sha256.isNullOrEmpty()) null else MessageDigest.getInstance("SHA-256")
        var received = 0L
        try {
            context.contentResolver.openOutputStream(target.uri, "w")?.use { out ->
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
                    record.progress = session.bytesDone + received
                    record.sampleSpeed()
                }
            } ?: return fail(record, AppError.UNKNOWN, "cannot open output stream")
        } catch (_: CancelledException) {
            target.deleter()
            record.status = TransferStatus.CANCELED
            return TransferServer.error(Status.BAD_REQUEST, "cancelled")
        } catch (e: Exception) {
            target.deleter()
            return fail(record, friendlyNetError(e), "write failed")
        } finally {
            session.currentTarget = null
        }

        // 短读校验：实收字节数必须等于 Content-Length，否则删除半成品回 500
        if (contentLength >= 0 && received != contentLength) {
            target.deleter()
            record.status = TransferStatus.FAILED
            record.error = AppError.INCOMPLETE_BODY
            return TransferServer.error(Status.INTERNAL_ERROR, "incomplete body")
        }

        // sha256 校验：不匹配删文件回 422
        if (digest != null) {
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            if (!actual.equals(meta.sha256, ignoreCase = true)) {
                target.deleter()
                record.status = TransferStatus.FAILED
                record.error = AppError.HASH_MISMATCH
                return TransferServer.error(TransferServer.STATUS_422, "sha256 mismatch")
            }
        }

        target.finish()   // MediaStore 路径清 IS_PENDING，文件对其它应用可见
        session.bytesDone += meta.size
        session.savedCount += 1
        if (record.fileUri == null) {
            record.fileUri = target.uri.toString()
            record.savedTreeUri = session.dirUri?.toString()
        }
        record.progress = session.bytesDone
        if (session.savedCount == session.files.size) {
            record.status = TransferStatus.DONE
        }
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
        try { session.currentTarget?.deleter?.invoke() } catch (_: Exception) {}
        if (session.record.status != TransferStatus.DONE) {
            session.record.status = TransferStatus.CANCELED
        }
        return TransferServer.jsonResponse(Status.OK, "")
    }

    /** 本机主动取消传输中的接收会话（记录页长按「取消」）：
     * 置位 cancelled，读流循环下一次检查抛 CancelledException 清理半成品并回错；
     * 等待确认期的会话走弹窗拒绝按钮，不在这里处理。 */
    fun cancelIncoming(recordId: String) {
        val session = sessions[recordId] ?: return
        if (session.state != SessionState.ACTIVE) return
        sessions.remove(recordId)
        session.cancelled = true
        try { session.currentTarget?.deleter?.invoke() } catch (_: Exception) {}
        if (session.record.status != TransferStatus.DONE) {
            session.record.status = TransferStatus.CANCELED
        }
    }

    // ---------- 内部工具 ----------

    /** 保存目标：文件 Uri + 删除半成品 + 完成收尾（MediaStore 需清 IS_PENDING） */
    private class SaveTarget(val uri: Uri, val deleter: () -> Unit, val finish: () -> Unit = {})

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

    /** 会话共同顶层文件夹名：全部文件同属一个顶层目录时返回它，否则 null */
    private fun commonTopFolder(files: List<FileMeta>): String? {
        val top = files.first().path?.split('/')?.firstOrNull()
        if (top.isNullOrEmpty()) return null
        if (files.any { it.path?.split('/')?.firstOrNull() != top }) return null
        return top
    }

    /** 把发送方声明的 path 相对路径清洗成安全分段（与 PC 端 _safe_rel_parts 同语义） */
    private fun safeRelParts(path: String?): List<String> {
        if (path.isNullOrEmpty()) return emptyList()
        return path.split('/')
            .filter { it.isNotEmpty() && it != "." && it != ".." }
            .map { seg ->
                seg.map { c -> if (c in "<>:\"\\|?*" || c.code < 32) '_' else c }
                    .joinToString("").trimEnd(' ', '.').ifEmpty { "_" }
            }
    }

    private fun fail(record: TransferRecord, error: AppError, message: String): NanoHTTPD.Response {
        record.status = TransferStatus.FAILED
        record.error = error
        return TransferServer.error(Status.INTERNAL_ERROR, message)
    }

    /** 打开保存目标：用户选定的 SAF 目录；未选（null）时默认系统 Download/Zbox（MediaStore，API 29+ 免权限） */
    private fun openSaveTarget(dirUri: Uri?, fileName: String, mime: String?,
                               dirParts: List<String> = emptyList()): SaveTarget? {
        if (dirUri != null) {
            var dir = DocumentFile.fromTreeUri(context, dirUri) ?: return null
            for (seg in dirParts) {
                dir = ensureSubdir(dir, seg) ?: return null
            }
            val doc = createUniqueFile(dir, fileName) ?: return null
            return SaveTarget(doc.uri, { doc.delete() })
        }
        return createDownloadFile(fileName, mime, dirParts)
    }

    /** 在 SAF 目录下找或建子目录（同名目录合并复用，对齐 PC 端 makedirs(exist_ok) 语义） */
    private fun ensureSubdir(dir: DocumentFile, name: String): DocumentFile? {
        dir.listFiles().firstOrNull { it.isDirectory && it.name == name }?.let { return it }
        return dir.createDirectory(name)
    }

    /** 默认保存到系统 Download/Zbox（RELATIVE_PATH 子目录插入时自动创建）；API 26-28 无 MediaStore.Downloads 免权限写入，返回 null 走失败提示 */
    private fun createDownloadFile(fileName: String, mime: String?,
                                   dirParts: List<String> = emptyList()): SaveTarget? {
        if (Build.VERSION.SDK_INT < 29) return null
        val resolver = context.contentResolver
        val relPath = Environment.DIRECTORY_DOWNLOADS + "/Zbox" +
            (if (dirParts.isEmpty()) "" else "/" + dirParts.joinToString("/"))
        var candidate = fileName
        var index = 2
        while (downloadExists(candidate, relPath)) {
            val dot = fileName.lastIndexOf('.')
            candidate = if (dot > 0) {
                fileName.substring(0, dot) + " (" + index + ")" + fileName.substring(dot)
            } else {
                fileName + " (" + index + ")"
            }
            index++
        }
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, candidate)
            put(MediaStore.Downloads.MIME_TYPE, mime ?: "application/octet-stream")
            put(MediaStore.Downloads.RELATIVE_PATH, relPath)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: return null
        return SaveTarget(uri, { resolver.delete(uri, null, null) }, {
            val done = ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }
            try { resolver.update(uri, done, null, null) } catch (_: Exception) {}
        })
    }

    /** Download 目标子目录下是否已有同名文件（重名加 " (2)" 后缀用） */
    private fun downloadExists(name: String, relPath: String): Boolean {
        val cursor = context.contentResolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            arrayOf(MediaStore.Downloads._ID),
            MediaStore.Downloads.DISPLAY_NAME + "=? AND " + MediaStore.Downloads.RELATIVE_PATH + "=?",
            arrayOf(name, relPath + "/"),
            null,
        ) ?: return false
        cursor.use { return it.count > 0 }
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
