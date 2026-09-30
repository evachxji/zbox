package com.zviber.transfer.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.documentfile.provider.DocumentFile
import com.zviber.transfer.IncomingState
import com.zviber.transfer.Settings

/** 接收确认对话框：来源别名、文件清单、总大小、选择保存位置、接受/拒绝 */
@Composable
fun ReceiveDialogHost() {
    val pending = IncomingState.pending ?: return
    val context = LocalContext.current

    // 首次进入默认填入已记住的保存目录
    LaunchedEffect(pending.sessionId) {
        if (pending.dirUri == null) {
            Settings.saveTreeUri?.let { pending.dirUri = Uri.parse(it) }
        }
    }

    val dirPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri ->
        if (uri != null) {
            try {
                context.contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                )
            } catch (_: Exception) {
            }
            Settings.saveTreeUri = uri.toString()
            pending.dirUri = uri
        }
    }

    AlertDialog(
        onDismissRequest = { pending.onReject() },
        title = { Text("接收文件") },
        text = {
            Column {
                Text("来自：" + pending.fromAlias, style = MaterialTheme.typography.bodyLarge)
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    "共 " + pending.files.size + " 个文件 · " + fmtSize(pending.totalSize),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(modifier = Modifier.height(8.dp))
                LazyColumn(modifier = Modifier.heightIn(max = 200.dp)) {
                    items(pending.files, key = { it.id }) { file ->
                        Text(
                            text = file.fileName + "（" + fmtSize(file.size) + "）",
                            style = MaterialTheme.typography.bodySmall,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
                Spacer(modifier = Modifier.height(12.dp))
                OutlinedButton(
                    onClick = { dirPicker.launch(defaultTreeUri()) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    val label = pending.dirUri?.let { "保存到：" + dirName(it) } ?: "保存到：Download（系统默认，点我更改）"
                    Text(text = label, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        },
        confirmButton = {
            TextButton(
                // 未选目录也能直接接受：默认存到系统 Download（API 29+）
                onClick = { pending.onAccept(pending.dirUri) },
            ) {
                Text("接受")
            }
        },
        dismissButton = {
            TextButton(onClick = { pending.onReject() }) {
                Text("拒绝")
            }
        },
    )
}

/** 首次引导到 Download/Zviber；已记住目录则回到该目录 */
private fun defaultTreeUri(): Uri {
    val saved = Settings.saveTreeUri
    if (saved != null) return Uri.parse(saved)
    return android.provider.DocumentsContract.buildTreeDocumentUri(
        "com.android.externalstorage.documents",
        "primary:Download/Zviber",
    )
}

private fun dirName(uri: Uri): String {
    return uri.lastPathSegment?.substringAfter(':') ?: uri.toString()
}
