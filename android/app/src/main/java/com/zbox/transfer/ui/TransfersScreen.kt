package com.zbox.transfer.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.MediaStore
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
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.documentfile.provider.DocumentFile
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.zbox.transfer.AppStrings
import com.zbox.transfer.Receiver
import com.zbox.transfer.Sender
import com.zbox.transfer.TransferRecord
import com.zbox.transfer.TransferStatus
import com.zbox.transfer.TransferStore
import kotlinx.coroutines.delay

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
                // 长按弹菜单：传输中=取消（接收方仅传输中，等待确认走弹窗拒绝），已完成=打开文件所在目录
                val canCancel = if (record.outgoing)
                    record.status == TransferStatus.WAITING || record.status == TransferStatus.TRANSFERRING
                else record.status == TransferStatus.TRANSFERRING
                val canOpenDir = record.status == TransferStatus.DONE && record.fileUri != null
                var menuOpen by remember(record.id) { mutableStateOf(false) }
                Box {
                // animateItem：新记录插入平滑铺开，其余记录平滑让位
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .combinedClickable(
                            enabled = canOpen(record) || canCancel || canOpenDir,
                            onClick = { if (canOpen(record)) openRecordLocation(context, record) },
                            onLongClick = {
                                if (canCancel || canOpenDir) {
                                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                                    menuOpen = true
                                }
                            },
                        )
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
                            targetState = AppStrings.current.status(record.status) to statusColor,
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
                    // 传输中三栏（对齐 PC 记录行）：已传/总大小 · 剩余时间 · 速度，统一强调色
                    if (record.status == TransferStatus.TRANSFERRING) {
                        // 数字 2s 节流刷新（进度条仍实时）：快照每 2s 采样一次，状态离开 TRANSFERRING 自动停止
                        var statSnap by remember(record.id) {
                            mutableStateOf(record.progress to record.speedBps)
                        }
                        LaunchedEffect(record.id) {
                            while (true) {
                                delay(2000)
                                statSnap = record.progress to record.speedBps
                            }
                        }
                        val (snapProgress, snapSpeed) = statSnap
                        Spacer(modifier = Modifier.height(4.dp))
                        Row(modifier = Modifier.fillMaxWidth()) {
                            Text(
                                text = fmtSize(snapProgress) + " / " + fmtSize(record.size),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.primary,
                            )
                            Spacer(modifier = Modifier.weight(1f))
                            if (snapSpeed > 0 && record.size > 0) {
                                val eta = (record.size - snapProgress) / snapSpeed
                                if (eta > 0) {
                                    Text(
                                        text = "剩 " + fmtEta(eta),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.primary,
                                    )
                                }
                            }
                            Spacer(modifier = Modifier.weight(1f))
                            if (snapSpeed > 0) {
                                Text(
                                    text = fmtSize(snapSpeed) + "/s",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }
                    record.error?.let {
                        Text(
                            text = AppStrings.current.error(it),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    if (canCancel) {
                        DropdownMenuItem(
                            text = { Text("取消传输") },
                            onClick = {
                                menuOpen = false
                                if (record.outgoing) Sender.cancel(record.id)
                                else Receiver.active?.cancelIncoming(record.id)
                            },
                        )
                    }
                    if (canOpenDir) {
                        DropdownMenuItem(
                            text = { Text("打开文件所在目录") },
                            onClick = {
                                menuOpen = false
                                openRecordLocation(context, record, forceDir = true)
                            },
                        )
                    }
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

/** 点击记录：媒体文件（图/视/音）直接打开文件交给相册/播放器；其余跳转到文件所在目录，拿不到目录时退化为打开文件本身。
 * forceDir = true（长按菜单「打开文件所在目录」）跳过媒体直开分支，一律定位目录。 */
private fun openRecordLocation(context: Context, record: TransferRecord, forceDir: Boolean = false) {
    val fileUri = record.fileUri?.let { Uri.parse(it) }
    if (fileUri != null && !forceDir) {
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
        // 接收且选了 SAF 目录：优先取文件真实父目录（文件夹传输的子目录），拿不到回退树根
        record.savedTreeUri != null -> {
            val parent = record.fileUri?.let {
                DocumentFile.fromSingleUri(context, Uri.parse(it))?.parentFile?.uri
            }
            parent ?: Uri.parse(record.savedTreeUri).let { tree ->
                DocumentsContract.buildDocumentUri(tree.authority, DocumentsContract.getTreeDocumentId(tree))
            }
        }
        // 接收且走默认：按文件真实 RELATIVE_PATH 跳转（文件夹传输含子目录），拿不到回退 Download/Zbox
        !record.outgoing -> {
            val rel = record.fileUri?.let { queryRelativePath(context, Uri.parse(it)) }
                ?.removeSuffix("/")?.takeIf { it.isNotEmpty() }
            DocumentsContract.buildDocumentUri(ext, "primary:" + (rel ?: "Download/Zbox"))
        }
        // 发送：从源文件 uri 推导父目录（仅 externalstorage 文档可推导）
        else -> deriveParentDocUri(Uri.parse(record.fileUri ?: return))
    }
    if (dirDoc != null) {
        try {
            // DocumentsUI 打开目录：VIEW + directory 类型（BROWSE 动作在很多机型上解析不到）；
            // 必须带读授权 flag，否则第三方文件管理器无权读这个 document uri，会退化到默认目录页
            context.startActivity(
                Intent(Intent.ACTION_VIEW, dirDoc)
                    .setType("vnd.android.document/directory")
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
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

/** 从 MediaStore 文件 uri 查 RELATIVE_PATH（形如 Download/Zbox/，末尾带斜杠）；API<29 或非 MediaStore uri 返回 null */
private fun queryRelativePath(context: Context, uri: Uri): String? {
    return try {
        context.contentResolver.query(
            uri, arrayOf(MediaStore.MediaColumns.RELATIVE_PATH), null, null, null
        )?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    } catch (_: Exception) {
        null
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
