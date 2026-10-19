package com.zbox.transfer

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
    // 文件夹传输：posix 分隔相对路径（含顶层文件夹名）；旧版端无此字段，退化为扁平收文件
    val path: String? = null,
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

/** 传输状态（文案按当前语言由 AppStrings.status 给出） */
enum class TransferStatus {
    WAITING,
    TRANSFERRING,
    DONE,
    FAILED,
    REJECTED,
    CANCELED,
}

/** 一条传输记录 */
class TransferRecord(
    val id: String,
    val outgoing: Boolean,
    val peerAlias: String,
    val fileName: String,
    val size: Long,
    // 接收会话聚合记录：多文件数 / 共同顶层文件夹名（显示名按当前语言动态生成）
    val multiCount: Int = 0,
    val folderName: String? = null,
) {
    var progress by mutableStateOf(0L)
    var status by mutableStateOf(TransferStatus.WAITING)
    var error by mutableStateOf<AppError?>(null)
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

/** 把底层异常归一成错误码（记录只存错误码，展示时按当前语言取文案） */
fun friendlyNetError(e: Throwable, fallback: AppError = AppError.UNKNOWN): AppError = when (e) {
    is java.net.ConnectException -> AppError.CONNECT_FAILED
    is java.net.SocketTimeoutException -> AppError.TIMEOUT
    is java.net.SocketException -> AppError.CONNECTION_INTERRUPTED
    is java.net.UnknownHostException -> AppError.HOST_NOT_FOUND
    // 声明长度与实际流字节数不符（相册 SIZE 列过期等）
    is java.net.ProtocolException -> AppError.PROTOCOL_MISMATCH
    else -> {
        val msg = e.message ?: ""
        when {
            msg.contains("ENOSPC") || msg.contains("No space left", true) -> AppError.NO_SPACE
            msg.contains("EACCES") || msg.contains("Permission denied", true) -> AppError.NO_PERMISSION
            msg == "cannot open input stream" -> AppError.SOURCE_UNREADABLE
            else -> fallback
        }
    }
}