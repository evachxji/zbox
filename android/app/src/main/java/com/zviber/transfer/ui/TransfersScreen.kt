package com.zviber.transfer.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.webkit.MimeTypeMap

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.zviber.transfer.Sender
import com.zviber.transfer.TransferRecord
import com.zviber.transfer.TransferStatus
import com.zviber.transfer.TransferStore

/** 记录区（嵌入主页底部）：方向、文件名、进度条、状态；占满剩余空间内部滚动 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ColumnScope.RecordsSection() {
    val haptics = LocalHapticFeedback.current
    val context = LocalContext.current
    val records = TransferStore.records
    Column(modifier = Modifier.weight(1f)) {
        Text("传输记录", style = MaterialTheme.typography.titleMedium)
        Spacer(modifier = Modifier.height(8.dp))
        if (records.isEmpty()) {
            Text(
                text = "暂无记录",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(records, key = { it.id }) { record ->
                // animateItem：新记录插入平滑铺开，其余记录平滑让位
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(enabled = canOpen(record)) { openRecordLocation(context, record) }
                        .animateItem(),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        val dirColor = if (record.outgoing) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.tertiary
                        Icon(
                            imageVector = if (record.outgoing) Icons.Filled.KeyboardArrowUp
                            else Icons.Filled.KeyboardArrowDown,
                            contentDescription = if (record.outgoing) "发送" else "接收",
                            tint = dirColor,
                            modifier = Modifier
                                .size(26.dp)
                                .background(dirColor.copy(alpha = 0.15f), CircleShape)
                                .padding(4.dp),
                        )
                        Text(
                            text = record.fileName,
                            style = MaterialTheme.typography.bodyLarge,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                        )
                        val statusColor = when (record.status) {
                            TransferStatus.DONE -> MaterialTheme.colorScheme.primary
                            TransferStatus.FAILED, TransferStatus.REJECTED -> MaterialTheme.colorScheme.error
                            else -> MaterialTheme.colorScheme.onSurfaceVariant
                        }
                        // 状态切换淡入淡出 + 微滑动，不硬跳
                        AnimatedContent(
                            targetState = record.status.label to statusColor,
                            transitionSpec = {
                                (fadeIn(tween(160)) + slideInVertically(tween(160)) { it / 4 }) togetherWith
                                    (fadeOut(tween(120)) + slideOutVertically(tween(120)) { -it / 4 })
                            },
                            label = "status",
                        ) { (label, color) ->
                            Text(text = label, style = MaterialTheme.typography.labelMedium, color = color)
                        }
                        // 发送中（等待确认 / 传输中）允许取消；终态不显示
                        if (record.outgoing &&
                            (record.status == TransferStatus.WAITING || record.status == TransferStatus.TRANSFERRING)
                        ) {
                            TextButton(onClick = {
                                haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                                Sender.cancel(record.id)
                            }) {
                                Text("取消")
                            }
                        }
                    }
                    val metaText = StringBuilder()
                        .append(if (record.outgoing) "发往 " else "来自 ")
                        .append(record.peerAlias).append(" · ").append(fmtSize(record.size))
                    if (record.status == TransferStatus.TRANSFERRING && record.speedBps > 0) {
                        metaText.append(" · ").append(fmtSize(record.speedBps)).append("/s")
                        if (record.size > 0) {
                            val eta = (record.size - record.progress) / record.speedBps
                            if (eta > 0) metaText.append(" · 剩 ").append(fmtEta(eta))
                        }
                    }
                    Text(
                        text = metaText.toString(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    val rawProgress = when {
                        record.size <= 0 -> if (record.status == TransferStatus.DONE) 1f else 0f
                        else -> (record.progress.toFloat() / record.size).coerceIn(0f, 1f)
                    }
                    // 进度平滑过渡，消除阶梯跳变
                    val animatedProgress by animateFloatAsState(
                        targetValue = rawProgress,
                        animationSpec = tween(220),
                        label = "progress",
                    )
                    LinearProgressIndicator(
                        progress = { animatedProgress },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    record.error?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
            }
        }
    }
}

/** 文件大小格式化 */
internal fun fmtSize(bytes: Long): String {
    if (bytes < 0) return "未知大小"
    if (bytes < 1024) return bytes.toString() + " B"
    val kb = bytes / 1024.0
    if (kb < 1024) return "%.1f KB".format(kb)
    val mb = kb / 1024.0
    if (mb < 1024) return "%.1f MB".format(mb)
    return "%.2f GB".format(mb / 1024.0)
}

/** 该行是否可跳转：接收完成 / 发送（有源文件 uri 即可，含发送中） */
private fun canOpen(record: TransferRecord): Boolean =
    if (record.outgoing) record.fileUri != null
    else record.status == TransferStatus.DONE && record.fileUri != null

/** 点击记录：媒体文件（图/视/音）直接打开文件交给相册/播放器；其余跳转到文件所在目录，拿不到目录时退化为打开文件本身 */
private fun openRecordLocation(context: Context, record: TransferRecord) {
    val fileUri = record.fileUri?.let { Uri.parse(it) }
    if (fileUri != null) {
        val mime = context.contentResolver.getType(fileUri) ?: mimeFromName(record.fileName)
        if (mime.startsWith("image/") || mime.startsWith("video/") || mime.startsWith("audio/")) {
            try {
                context.startActivity(Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(fileUri, mime)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                })
                return
            } catch (_: Exception) {
            }
        }
    }
    val ext = "com.android.externalstorage.documents"
    val dirDoc = when {
        // 接收且选了 SAF 目录：tree uri 转 document uri
        record.savedTreeUri != null -> {
            val tree = Uri.parse(record.savedTreeUri)
            DocumentsContract.buildDocumentUri(tree.authority, DocumentsContract.getTreeDocumentId(tree))
        }
        // 接收且走默认：系统 Download/Zviber
        !record.outgoing -> DocumentsContract.buildDocumentUri(ext, "primary:Download/Zviber")
        // 发送：从源文件 uri 推导父目录（仅 externalstorage 文档可推导）
        else -> deriveParentDocUri(Uri.parse(record.fileUri ?: return))
    }
    if (dirDoc != null) {
        try {
            // DocumentsUI 打开目录：VIEW + directory 类型（BROWSE 动作在很多机型上解析不到）
            context.startActivity(
                Intent(Intent.ACTION_VIEW, dirDoc).setType("vnd.android.document/directory")
            )
            return
        } catch (_: Exception) {
        }
    }
    // 退化：打开文件本身
    val file = Uri.parse(record.fileUri ?: return)
    try {
        context.startActivity(Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(file, context.contentResolver.getType(file) ?: "*/*")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        })
    } catch (_: Exception) {
    }
}

/** externalstorage 文档 uri 推导父目录（形如 primary:Download/x.jpg → primary:Download） */
private fun deriveParentDocUri(uri: Uri): Uri? {
    if (uri.authority != "com.android.externalstorage.documents") return null
    val docId = DocumentsContract.getDocumentId(uri)
    val parent = docId.substringBeforeLast('/', "")
    if (parent.isEmpty() || parent == docId) return null
    return DocumentsContract.buildDocumentUri(uri.authority, parent)
}

/** 按文件名后缀推 MIME（contentResolver.getType 拿不到时兜底） */
private fun mimeFromName(fileName: String): String {
    val ext = MimeTypeMap.getFileExtensionFromUrl(fileName)
    if (!ext.isNullOrEmpty()) {
        MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext.lowercase())?.let { return it }
    }
    return "application/octet-stream"
}

/** 剩余秒数格式化 */
internal fun fmtEta(seconds: Long): String {
    if (seconds < 60) return seconds.toString() + " 秒"
    if (seconds < 3600) return (seconds / 60).toString() + " 分 " + (seconds % 60) + " 秒"
    return (seconds / 3600).toString() + " 小时"
}
