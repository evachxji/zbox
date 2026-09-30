package com.zviber.transfer.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.filled.Done
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.zviber.transfer.DeviceStore
import com.zviber.transfer.Discovery
import com.zviber.transfer.PeerDevice
import com.zviber.transfer.Sender
import com.zviber.transfer.Settings

/** 设备页：本机别名卡片 + 附近设备列表 + 手动刷新；点设备选文件发送 */
@Composable
fun DevicesScreen(discovery: Discovery) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var pickedDevice by remember { mutableStateOf<PeerDevice?>(null) }
    val filePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments()
    ) { uris ->
        val device = pickedDevice
        if (device != null && !uris.isNullOrEmpty()) {
            Sender.send(context, device, uris, scope)
        }
        pickedDevice = null
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        AliasCard()
        Spacer(modifier = Modifier.height(16.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = "附近设备",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = { discovery.refresh() }) {
                Icon(Icons.Filled.Refresh, contentDescription = "刷新")
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        val devices = DeviceStore.devices
        if (devices.isEmpty()) {
            Text(
                text = "未发现设备\n请确认对方在同一局域网并已打开应用，或点右上角刷新扫描",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(devices, key = { it.info.fingerprint }) { device ->
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            pickedDevice = device
                            filePicker.launch(arrayOf("*/*"))
                        },
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(device.info.alias, style = MaterialTheme.typography.titleSmall)
                        Spacer(modifier = Modifier.height(4.dp))
                        val seenSec = ((System.currentTimeMillis() - device.lastSeen) / 1000).coerceAtLeast(0)
                        Text(
                            text = deviceTypeLabel(device.info.deviceType) + " · " + device.ip +
                                " · 最后见到 " + seenSec + " 秒前",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

/** 本机别名卡片（可编辑） */
@Composable
private fun AliasCard() {
    var alias by remember { mutableStateOf(Settings.alias) }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text("本机", style = MaterialTheme.typography.titleSmall)
            Spacer(modifier = Modifier.height(8.dp))
            OutlinedTextField(
                value = alias,
                onValueChange = { alias = it },
                singleLine = true,
                label = { Text("别名") },
                modifier = Modifier.fillMaxWidth(),
                trailingIcon = {
                    IconButton(onClick = { Settings.alias = alias.trim().ifEmpty { Settings.alias } }) {
                        Icon(Icons.Filled.Done, contentDescription = "保存别名")
                    }
                },
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "指纹 " + Settings.fingerprint.take(8) + "… · 端口 53327",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private fun deviceTypeLabel(type: String?): String = when (type) {
    "mobile" -> "手机"
    "desktop" -> "电脑"
    "web" -> "网页"
    "headless" -> "终端"
    "server" -> "服务器"
    else -> type ?: "设备"
}
