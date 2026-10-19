package com.zbox.transfer

import java.util.Locale

/** 界面语言：目前只支持简体中文与英文 */
enum class AppLanguage(val code: String, val displayName: String) {
    ZH("zh-CN", "简体中文"),
    EN("en-US", "English");

    companion object {
        /** 把系统语言标签归一成受支持的语言；无法识别返回 null */
        fun fromLocaleTag(tag: String): AppLanguage? {
            val normalized = tag.trim().lowercase().replace('_', '-')
            return when {
                normalized.startsWith("zh") -> ZH
                normalized.substringBefore('-').length in 2..3 -> EN
                else -> null
            }
        }

        /** 系统语言标签 → 语言；未识别时回落中文 */
        fun detect(tag: String = Locale.getDefault().toLanguageTag()): AppLanguage =
            fromLocaleTag(tag) ?: ZH
    }
}

/** 传输失败原因（记录只保存错误码，展示时按当前语言取文案） */
enum class AppError {
    FILE_SIZE_UNAVAILABLE,
    CONNECT_FAILED,
    TIMEOUT,
    CONNECTION_INTERRUPTED,
    HOST_NOT_FOUND,
    PROTOCOL_MISMATCH,
    NO_SPACE,
    NO_PERMISSION,
    SOURCE_UNREADABLE,
    PEER_BUSY,
    NEGOTIATION_FAILED,
    PEER_REJECTED_FILE,
    SESSION_CONFLICT,
    INCOMPLETE_BODY,
    HASH_MISMATCH,
    UNKNOWN,
}

/** 界面文案接口：中英两套实现覆盖全部用户可见状态与错误 */
interface AppStrings {
    val transferTab: String
    val settingsTab: String
    val language: String
    val nearbyDevices: String

    fun status(status: TransferStatus): String
    fun error(error: AppError): String

    companion object {
        /** 当前语言文案表（读 Settings.language，Compose 会随语言切换重组） */
        val current: AppStrings
            get() = AppLocale.strings(Settings.language)
    }
}

object AppLocale {
    fun strings(language: AppLanguage): AppStrings =
        if (language == AppLanguage.EN) EnglishStrings else ChineseStrings
}

object ChineseStrings : AppStrings {
    override val transferTab = "传输"
    override val settingsTab = "设置"
    override val language = "语言"
    override val nearbyDevices = "附近的设备"

    override fun status(status: TransferStatus): String = when (status) {
        TransferStatus.WAITING -> "等待确认"
        TransferStatus.TRANSFERRING -> "传输中"
        TransferStatus.DONE -> "完成"
        TransferStatus.FAILED -> "失败"
        TransferStatus.REJECTED -> "被拒绝"
        TransferStatus.CANCELED -> "已取消"
    }

    override fun error(error: AppError): String = when (error) {
        AppError.FILE_SIZE_UNAVAILABLE -> "无法获取文件大小"
        AppError.CONNECT_FAILED -> "无法连接对方设备（对方可能已退出或换了网络）"
        AppError.TIMEOUT -> "连接或传输超时，请重试"
        AppError.CONNECTION_INTERRUPTED -> "连接被中断"
        AppError.HOST_NOT_FOUND -> "找不到对方设备"
        AppError.PROTOCOL_MISMATCH -> "文件内容与声明大小不符，请在相册里重新保存该图片后重试"
        AppError.NO_SPACE -> "存储空间不足"
        AppError.NO_PERMISSION -> "没有存储权限"
        AppError.SOURCE_UNREADABLE -> "无法读取源文件"
        AppError.PEER_BUSY -> "对方正忙"
        AppError.NEGOTIATION_FAILED -> "协商失败"
        AppError.PEER_REJECTED_FILE -> "对方未接受该文件"
        AppError.SESSION_CONFLICT -> "会话冲突"
        AppError.INCOMPLETE_BODY -> "传输数据不完整"
        AppError.HASH_MISMATCH -> "文件校验失败"
        AppError.UNKNOWN -> "传输失败"
    }
}

object EnglishStrings : AppStrings {
    override val transferTab = "Transfer"
    override val settingsTab = "Settings"
    override val language = "Language"
    override val nearbyDevices = "Nearby devices"

    override fun status(status: TransferStatus): String = when (status) {
        TransferStatus.WAITING -> "Waiting for confirmation"
        TransferStatus.TRANSFERRING -> "Transferring"
        TransferStatus.DONE -> "Done"
        TransferStatus.FAILED -> "Failed"
        TransferStatus.REJECTED -> "Rejected"
        TransferStatus.CANCELED -> "Canceled"
    }

    override fun error(error: AppError): String = when (error) {
        AppError.FILE_SIZE_UNAVAILABLE -> "Unable to get the file size"
        AppError.CONNECT_FAILED -> "Cannot connect to the other device (it may have exited or changed networks)"
        AppError.TIMEOUT -> "Connection or transfer timed out. Please try again."
        AppError.CONNECTION_INTERRUPTED -> "Connection interrupted"
        AppError.HOST_NOT_FOUND -> "Device not found"
        AppError.PROTOCOL_MISMATCH -> "File content does not match the declared size. Re-save the image in the gallery and try again."
        AppError.NO_SPACE -> "Not enough storage space"
        AppError.NO_PERMISSION -> "No storage permission"
        AppError.SOURCE_UNREADABLE -> "Cannot read the source file"
        AppError.PEER_BUSY -> "The other device is busy"
        AppError.NEGOTIATION_FAILED -> "Negotiation failed"
        AppError.PEER_REJECTED_FILE -> "The other device did not accept the file"
        AppError.SESSION_CONFLICT -> "Session conflict"
        AppError.INCOMPLETE_BODY -> "Transfer data is incomplete"
        AppError.HASH_MISMATCH -> "File checksum failed"
        AppError.UNKNOWN -> "Transfer failed"
    }
}
