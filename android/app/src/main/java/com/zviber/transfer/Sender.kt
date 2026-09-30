package com.zviber.transfer

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.serialization.encodeToString
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import java.util.UUID
import java.util.concurrent.TimeUnit

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

    fun send(context: Context, device: PeerDevice, uris: List<Uri>, scope: CoroutineScope) {
        scope.launch(Dispatchers.IO) { doSend(context, device, uris) }
    }

    private fun doSend(context: Context, device: PeerDevice, uris: List<Uri>) {
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
            ).also { TransferStore.add(it) }
            OutFile(meta, uri, record)
        }
        if (files.isEmpty()) return

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

        val response = try {
            client.newCall(prepareRequest).execute()
        } catch (e: Exception) {
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

        // 3. 逐文件流式上传
        files.forEach { it.record.status = TransferStatus.TRANSFERRING }
        for (file in files) {
            val token = prepare.files[file.meta.id]
            if (token == null) {
                fail(file.record, "对方未接受该文件")
                continue
            }
            val ok = uploadOne(context, base, prepare.sessionId, token, file)
            if (!ok) {
                // 失败即中止整批：通知对方 cancel
                try {
                    client.newCall(
                        Request.Builder()
                            .url("$base/cancel?sessionId=" + prepare.sessionId)
                            .post("".toRequestBody(null))
                            .build()
                    ).execute().close()
                } catch (_: Exception) {
                }
                // 其余未传文件标记为已取消
                files.filter { it.record.status == TransferStatus.TRANSFERRING && it.meta.id != file.meta.id }
                    .forEach { it.record.status = TransferStatus.CANCELED }
                return
            }
        }
    }

    /** 单文件上传：流式 RequestBody，分块上报进度 */
    private fun uploadOne(
        context: Context,
        base: String,
        sessionId: String,
        token: String,
        file: OutFile,
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
                    }
                } ?: throw java.io.IOException("cannot open input stream")
            }
        }
        val url = "$base/upload?sessionId=$sessionId&fileId=${file.meta.id}&token=$token"
        return try {
            client.newCall(Request.Builder().url(url).post(body).build()).execute().use { resp ->
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
