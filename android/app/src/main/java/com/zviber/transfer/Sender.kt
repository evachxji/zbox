package com.zviber.transfer

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.serialization.encodeToString
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * 发送方：prepare-upload 协商（403 = 对方拒绝）→ 逐文件 POST upload 流式上传 → 失败调 cancel。
 */
object Sender {

    // prepare-upload 需等待对方用户确认，读超时放宽到 5 分钟
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .writeTimeout(5, TimeUnit.MINUTES)
        .build()

    private class OutFile(
        val meta: FileMeta,
        val uri: Uri,
        val record: TransferRecord,
    )

    /** 进行中的发送会话：供 UI 按记录取消 */
    private class ActiveSession {
        val records = CopyOnWriteArrayList<TransferRecord>()

        @Volatile
        var cancelled = false

        @Volatile
        var call: Call? = null

        @Volatile
        var job: Job? = null

        @Volatile
        var base: String? = null

        @Volatile
        var sessionId: String? = null
    }

    // 记录 id -> 发送会话（仅进行中保留在表里）
    private val activeByRecord = ConcurrentHashMap<String, ActiveSession>()

    /** 是否有正在发送中的会话（供 MainActivity 判断退后台是否保持服务） */
    fun hasActive(): Boolean = activeByRecord.isNotEmpty()

    fun send(context: Context, device: PeerDevice, uris: List<Uri>, scope: CoroutineScope) {
        val session = ActiveSession()
        session.job = scope.launch(Dispatchers.IO) { doSend(context, device, uris, session) }
    }

    /** 取消某条记录所属的发送会话：中断当前请求，通知对端 cancel，记录置「已取消」 */
    fun cancel(recordId: String) {
        val session = activeByRecord[recordId] ?: return
        session.cancelled = true
        session.call?.cancel()
        session.job?.cancel()
        session.records.forEach {
            if (it.status != TransferStatus.DONE) it.status = TransferStatus.CANCELED
        }
        val base = session.base
        val sessionId = session.sessionId
        if (base != null && sessionId != null) {
            // UI 线程调用，POST 放后台
            thread { postCancel(base, sessionId) }
        }
    }

    private fun doSend(context: Context, device: PeerDevice, uris: List<Uri>, session: ActiveSession) {
        val base = "http://${device.ip}:$PROTOCOL_PORT$API_PREFIX"
        val resolver = context.contentResolver

        // 1. 收集元数据（id = uuid，sha256 留空）
        val files = uris.mapNotNull { uri ->
            val (name, size0) = queryMeta(context, uri)
            if (name == null) return@mapNotNull null
            // 大小未知时用 AssetFileDescriptor 兜底取真实长度
            var size = size0
            if (size < 0) {
                size = try {
                    resolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
                } catch (_: Exception) {
                    -1L
                }
            }
            if (size < 0) {
                // 协议要求必须知道长度：拒绝该文件并在记录中提示
                TransferRecord(
                    id = UUID.randomUUID().toString(),
                    outgoing = true,
                    peerAlias = device.info.alias,
                    fileName = name,
                    size = -1L,
                ).also {
                    it.status = TransferStatus.FAILED
                    it.error = "无法获取文件大小"
                    TransferStore.add(it)
                }
                return@mapNotNull null
            }
            val meta = FileMeta(
                id = UUID.randomUUID().toString(),
                fileName = name,
                size = size,
                fileType = resolver.getType(uri) ?: "application/octet-stream",
            )
            val record = TransferRecord(
                id = meta.id,
                outgoing = true,
                peerAlias = device.info.alias,
                fileName = name,
                size = size,
            ).also {
                it.fileUri = uri.toString()
                TransferStore.add(it)
            }
            OutFile(meta, uri, record)
        }
        if (files.isEmpty()) return

        // 登记会话供 UI 取消；发送结束（无论成败）移出
        session.base = base
        files.forEach {
            session.records.add(it.record)
            activeByRecord[it.record.id] = session
        }
        try {
            // 2. prepare-upload
            val prepareBody = protoJson.encodeToString(
                PrepareRequest(
                    info = Settings.localInfo(),
                    files = files.associate { it.meta.id to it.meta },
                )
            ).toRequestBody("application/json".toMediaType())
            val prepareRequest = Request.Builder()
                .url("$base/prepare-upload")
                .post(prepareBody)
                .build()

            val prepareCall = client.newCall(prepareRequest)
            session.call = prepareCall
            val response = try {
                prepareCall.execute()
            } catch (e: Exception) {
                // 被取消时记录已由 cancel() 置为「已取消」
                if (session.cancelled) return
                files.forEach { fail(it.record, e.message ?: "连接失败") }
                return
            }

            val prepare = response.use { resp ->
                when (resp.code) {
                    200 -> resp.body?.string()?.let {
                        try { protoJson.decodeFromString<PrepareResponse>(it) } catch (_: Exception) { null }
                    }
                    403 -> {
                        files.forEach { it.record.status = TransferStatus.REJECTED }
                        null
                    }
                    409 -> {
                        files.forEach { fail(it.record, "对方正忙") }
                        null
                    }
                    else -> {
                        files.forEach { fail(it.record, "协商失败：HTTP " + resp.code) }
                        null
                    }
                }
            } ?: return

            // 应答刚到就被取消：补发 cancel 通知对端（幂等）
            session.sessionId = prepare.sessionId
            if (session.cancelled) {
                postCancel(base, prepare.sessionId)
                return
            }

            // 3. 逐文件流式上传
            files.forEach { it.record.status = TransferStatus.TRANSFERRING }
            for (file in files) {
                val token = prepare.files[file.meta.id]
                if (token == null) {
                    fail(file.record, "对方未接受该文件")
                    continue
                }
                val ok = uploadOne(context, base, prepare.sessionId, token, file, session)
                if (!ok) {
                    if (session.cancelled) return
                    // 失败即中止整批：通知对方 cancel
                    postCancel(base, prepare.sessionId)
                    // 其余未传文件标记为已取消
                    files.filter { it.record.status == TransferStatus.TRANSFERRING && it.meta.id != file.meta.id }
                        .forEach { it.record.status = TransferStatus.CANCELED }
                    return
                }
            }
        } finally {
            files.forEach { activeByRecord.remove(it.record.id) }
        }
    }

    /** 通知对端中止会话（幂等，失败静默） */
    private fun postCancel(base: String, sessionId: String) {
        try {
            client.newCall(
                Request.Builder()
                    .url("$base/cancel?sessionId=" + sessionId)
                    .post("".toRequestBody(null))
                    .build()
            ).execute().close()
        } catch (_: Exception) {
        }
    }

    /** 单文件上传：流式 RequestBody，分块上报进度 */
    private fun uploadOne(
        context: Context,
        base: String,
        sessionId: String,
        token: String,
        file: OutFile,
        session: ActiveSession,
    ): Boolean {
        val body = object : RequestBody() {
            override fun contentType() = "application/octet-stream".toMediaType()
            override fun contentLength() = file.meta.size
            override fun writeTo(sink: BufferedSink) {
                context.contentResolver.openInputStream(file.uri)?.use { input ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        sink.write(buffer, 0, n)
                        file.record.progress += n
            file.record.sampleSpeed()
                    }
                } ?: throw java.io.IOException("cannot open input stream")
            }
        }
        val url = "$base/upload?sessionId=$sessionId&fileId=${file.meta.id}&token=$token"
        val call = client.newCall(Request.Builder().url(url).post(body).build())
        session.call = call
        return try {
            call.execute().use { resp ->
                if (resp.isSuccessful) {
                    file.record.progress = file.meta.size
                    file.record.status = TransferStatus.DONE
                    true
                } else {
                    fail(file.record, "上传失败：HTTP " + resp.code)
                    false
                }
            }
        } catch (e: Exception) {
            if (session.cancelled) return false
            fail(file.record, e.message ?: "上传失败")
            false
        }
    }

    private fun fail(record: TransferRecord, message: String) {
        record.status = TransferStatus.FAILED
        record.error = message
    }

    /** 从 SAF Uri 读出显示名与大小 */
    private fun queryMeta(context: Context, uri: Uri): Pair<String?, Long> {
        var name: String? = null
        var size = -1L
        try {
            context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val nameIdx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val sizeIdx = cursor.getColumnIndex(OpenableColumns.SIZE)
                    if (nameIdx >= 0) name = cursor.getString(nameIdx)
                    if (sizeIdx >= 0 && !cursor.isNull(sizeIdx)) size = cursor.getLong(sizeIdx)
                }
            }
        } catch (_: Exception) {
        }
        return (name ?: uri.lastPathSegment?.substringAfterLast('/') ?: "file") to size
    }
}
