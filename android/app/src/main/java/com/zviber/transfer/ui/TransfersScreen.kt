package com.zviber.transfer.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.zviber.transfer.Sender
import com.zviber.transfer.TransferStatus
import com.zviber.transfer.TransferStore

/** 记录页：方向、文件名、进度条、状态 */
@Composable
fun TransfersScreen() {
    val records = TransferStore.records
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("传输记录", style = MaterialTheme.typography.titleMedium)
        Spacer(modifier = Modifier.height(8.dp))
        if (records.isEmpty()) {
            Text(
                text = "暂无记录",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            items(records, key = { it.id }) { record ->
                Column(modifier = Modifier.fillMaxWidth()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = if (record.outgoing) Icons.Filled.KeyboardArrowUp
                            else Icons.Filled.KeyboardArrowDown,
                            contentDescription = if (record.outgoing) "发送" else "接收",
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Text(
                            text = record.fileName,
                            style = MaterialTheme.typography.bodyLarge,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                        )
                        Text(
                            text = record.status.label,
                            style = MaterialTheme.typography.labelMedium,
                            color = when (record.status) {
                                TransferStatus.DONE -> MaterialTheme.colorScheme.primary
                                TransferStatus.FAILED, TransferStatus.REJECTED -> MaterialTheme.colorScheme.error
                                else -> MaterialTheme.colorScheme.onSurfaceVariant
                            },
                        )
                        // 发送中（等待确认 / 传输中）允许取消；终态不显示
                        if (record.outgoing &&
                            (record.status == TransferStatus.WAITING || record.status == TransferStatus.TRANSFERRING)
                        ) {
                            TextButton(onClick = { Sender.cancel(record.id) }) {
                                Text("取消")
                            }
                        }
                    }
                    Text(
                        text = (if (record.outgoing) "发往 " else "来自 ") + record.peerAlias +
                            " · " + fmtSize(record.size),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    LinearProgressIndicator(
                        progress = {
                            when {
                                record.size <= 0 -> if (record.status == TransferStatus.DONE) 1f else 0f
                                else -> (record.progress.toFloat() / record.size).coerceIn(0f, 1f)
                            }
                        },
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
