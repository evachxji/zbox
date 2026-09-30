package com.zviber.transfer.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.zviber.transfer.DeviceStore
import com.zviber.transfer.Discovery
import com.zviber.transfer.PeerDevice
import com.zviber.transfer.Sender
import com.zviber.transfer.Settings
import kotlinx.coroutines.delay

/** 设备页：本机别名卡片 + 附近设备列表 + 手动刷新；点设备选文件发送 */
@Composable
fun DevicesScreen(discovery: Discovery) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var pickedDevice by remember { mutableStateOf<PeerDevice?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    // 刷新中的无限旋转动效
    val spinAngle by rememberInfiniteTransition(label = "refreshSpin").animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(900, easing = LinearEasing)),
        label = "refreshSpinAngle",
    )
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
            IconButton(
                onClick = {
                    refreshing = true
                    discovery.refresh { refreshing = false }
                },
                enabled = !refreshing,
            ) {
                Icon(
                    Icons.Filled.Refresh,
                    contentDescription = "刷新",
                    modifier = Modifier.graphicsLayer {
                        rotationZ = if (refreshing) spinAngle else 0f
                    },
                )
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

/** 本机别名卡片（可编辑，保存有动效反馈） */
@Composable
private fun AliasCard() {
    var alias by remember { mutableStateOf(Settings.alias) }
    var saved by remember { mutableStateOf(false) }      // 保存成功：短暂高亮反馈
    var emptyError by remember { mutableStateOf(false) } // 空别名：错误反馈
    val iconScale = remember { Animatable(1f) }
    val successColor = Color(0xFF66BB6A)
    val iconTint by animateColorAsState(
        targetValue = if (saved) successColor else MaterialTheme.colorScheme.onSurfaceVariant,
        animationSpec = tween(200),
        label = "aliasSaveTint",
    )
    if (saved) {
        // 勾选图标弹跳一次后自动复原
        LaunchedEffect(Unit) {
            iconScale.animateTo(1.35f, tween(120))
            iconScale.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy))
            delay(1400)
            saved = false
        }
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text("本机", style = MaterialTheme.typography.titleSmall)
            Spacer(modifier = Modifier.height(8.dp))
            OutlinedTextField(
                value = alias,
                onValueChange = {
                    alias = it
                    emptyError = false
                    saved = false
                },
                singleLine = true,
                isError = emptyError,
                supportingText = when {
                    emptyError -> ({ Text("别名不能为空") })
                    saved -> ({ Text("已保存", color = successColor) })
                    else -> null
                },
                label = { Text("别名") },
                modifier = Modifier.fillMaxWidth(),
                trailingIcon = {
                    IconButton(onClick = {
                        val trimmed = alias.trim()
                        if (trimmed.isEmpty()) {
                            emptyError = true
                            saved = false
                        } else {
                            Settings.alias = trimmed
                            alias = trimmed
                            emptyError = false
                            saved = true
                        }
                    }) {
                        Icon(
                            Icons.Filled.Done,
                            contentDescription = "保存别名",
                            tint = iconTint,
                            modifier = Modifier.graphicsLayer {
                                scaleX = iconScale.value
                                scaleY = iconScale.value
                            },
                        )
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
