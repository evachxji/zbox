package com.zviber.transfer

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

// ===================== LocalSend v2.2 协议常量（与 PC 端逐字节一致） =====================

/** HTTP TCP 端口 */
const val PROTOCOL_PORT = 53327

/** UDP 组播地址 */
const val MULTICAST_GROUP = "224.0.0.168"

/** API 前缀 */
const val API_PREFIX = "/api/localsend/v2"

/** 协议 JSON：容忍未知字段、默认值照常输出、null 字段省略 */
val protoJson = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
    explicitNulls = false
}

// ===================== 协议数据类 =====================

/** 设备信息（announce / register / info / prepare-upload 共用） */
@Serializable
data class DeviceInfo(
    val alias: String,
    val version: String = "2.0",
    val deviceModel: String? = null,
    val deviceType: String = "mobile",
    val fingerprint: String,
    val port: Int = PROTOCOL_PORT,
    val protocol: String = "http",
    // 仅组播 announce 报文带 true，其余请求省略
    val announce: Boolean? = null,
)

/** 文件元数据 */
@Serializable
data class FileMeta(
    val id: String,
    val fileName: String,
    val size: Long,
    val fileType: String = "application/octet-stream",
    val sha256: String? = null,
)

/** POST /prepare-upload 请求体 */
@Serializable
data class PrepareRequest(
    val info: DeviceInfo,
    val files: Map<String, FileMeta>,
)

/** POST /prepare-upload 200 应答体：fileId -> token */
@Serializable
data class PrepareResponse(
    val sessionId: String,
    val files: Map<String, String>,
)

// ===================== 运行期状态（Compose 可观察） =====================

/** 发现的局域网对端设备 */
data class PeerDevice(
    val info: DeviceInfo,
    val ip: String,
)

/** 设备表 */
object DeviceStore {
    val devices = mutableStateListOf<PeerDevice>()

    @Synchronized
    fun upsert(info: DeviceInfo, ip: String) {
        val idx = devices.indexOfFirst { it.info.fingerprint == info.fingerprint }
        if (idx >= 0) devices[idx] = PeerDevice(info, ip) else devices.add(PeerDevice(info, ip))
    }

    @Synchronized
    fun clear() {
        devices.clear()
    }
}

/** 传输状态 */
enum class TransferStatus(val label: String) {
    WAITING("等待确认"),
    TRANSFERRING("传输中"),
    DONE("完成"),
    FAILED("失败"),
    REJECTED("被拒绝"),
    CANCELED("已取消"),
}

/** 一条传输记录 */
class TransferRecord(
    val id: String,
    val outgoing: Boolean,
    val peerAlias: String,
    val fileName: String,
    val size: Long,
) {
    var progress by mutableStateOf(0L)
    var status by mutableStateOf(TransferStatus.WAITING)
    var error by mutableStateOf<String?>(null)
    var speedBps by mutableStateOf(0L)   // EMA 平滑后的传输速度（字节/秒）
    var fileUri: String? = null          // 接收=落盘文件，发送=源文件（点击行跳所在目录用）
    var savedTreeUri: String? = null     // 接收时选定的 SAF 目录；null 表示默认系统 Download

    private var lastTickAt = 0L
    private var lastTickProgress = 0L

    /** 进度帧采样：增量算瞬时速度并做指数平滑（供 UI 显示速度与剩余时间） */
    fun sampleSpeed() {
        val now = System.currentTimeMillis()
        if (lastTickAt == 0L) {
            lastTickAt = now
            lastTickProgress = progress
            return
        }
        val dt = now - lastTickAt
        val dp = progress - lastTickProgress
        if (dp > 0 && dt > 200) {
            val instant = dp * 1000L / dt
            speedBps = if (speedBps == 0L) instant else speedBps / 2 + instant / 2
            lastTickAt = now
            lastTickProgress = progress
        }
    }
}

/** 传输记录表 */
object TransferStore {
    val records = mutableStateListOf<TransferRecord>()

    @Synchronized
    fun add(record: TransferRecord) {
        records.add(0, record)
    }
}

/** 把底层英文异常信息翻译成用户可读的中文提示（记录页展示用） */
fun friendlyNetError(e: Throwable, fallback: String): String = when (e) {
    is java.net.ConnectException -> "无法连接对方设备（对方可能已退出或换了网络）"
    is java.net.SocketTimeoutException -> "连接或传输超时，请重试"
    is java.net.SocketException -> "连接被中断"
    is java.net.UnknownHostException -> "找不到对方设备"
    else -> {
        val msg = e.message ?: ""
        when {
            msg.contains("ENOSPC") || msg.contains("No space left", true) -> "存储空间不足"
            msg.contains("EACCES") || msg.contains("Permission denied", true) -> "没有存储权限"
            msg == "cannot open input stream" -> "无法读取源文件"
            else -> fallback
        }
    }
}