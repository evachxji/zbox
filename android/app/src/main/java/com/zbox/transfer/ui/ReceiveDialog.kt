package com.zbox.transfer.ui

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
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.documentfile.provider.DocumentFile
import com.zbox.transfer.AppStrings
import com.zbox.transfer.IncomingState
import com.zbox.transfer.Settings

/** 接收确认对话框：来源别名、文件清单、总大小、选择保存位置、接受/拒绝 */
@Composable
fun ReceiveDialogHost() {
    val pending = IncomingState.pending ?: return
    val strings = AppStrings.current
    val context = LocalContext.current
    val haptics = LocalHapticFeedback.current

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
        title = { Text(strings.receiveFiles) },
        text = {
            Column {
                Text(strings.fromAlias(pending.fromAlias), style = MaterialTheme.typography.bodyLarge)
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    strings.fileCountSummary(pending.files.size, fmtSize(pending.totalSize)),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(modifier = Modifier.height(8.dp))
                LazyColumn(modifier = Modifier.heightIn(max = 200.dp)) {
                    items(pending.files, key = { it.id }) { file ->
                        Text(
                            text = strings.fileWithSize(file.fileName, fmtSize(file.size)),
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
                    val label = pending.dirUri?.let { strings.saveTo(dirName(it)) } ?: strings.saveToDefault
                    Text(text = label, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        },
        confirmButton = {
            TextButton(
                // 未选目录也能直接接受：默认存到系统 Download/Zbox（API 29+）
                onClick = {
                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                    pending.onAccept(pending.dirUri)
                },
            ) {
                Text(strings.accept)
            }
        },
        dismissButton = {
            TextButton(onClick = {
                haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                pending.onReject()
            }) {
                Text(strings.reject)
            }
        },
    )
}

/** 首次引导到 Download/Zbox；已记住目录则回到该目录 */
private fun defaultTreeUri(): Uri {
    val saved = Settings.saveTreeUri
    if (saved != null) return Uri.parse(saved)
    return android.provider.DocumentsContract.buildTreeDocumentUri(
        "com.android.externalstorage.documents",
        "primary:Download/Zbox",
    )
}

private fun dirName(uri: Uri): String {
    return uri.lastPathSegment?.substringAfter(':') ?: uri.toString()
}
