package com.zviber.transfer.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
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
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Done
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.OutlinedButton
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
import com.zviber.transfer.ShareInbox
import com.zviber.transfer.TransferStore
import kotlinx.coroutines.delay

/** 主页（单页）：本机别名卡片 + 附近设备（最多 2.5 行、超出内部滚动）+ 底部传输记录 */
@Composable
fun HomeScreen(discovery: Discovery) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var pickedDevice by remember { mutableStateOf<PeerDevice?>(null) }
    var showSourceDialog by remember { mutableStateOf(false) }
    var refreshing by remember { mutableStateOf(false) }
    // 分享进件：有待发送文件时自动刷新一次设备列表（手动刷新按钮照常可用）
    val shareUris = ShareInbox.uris
    LaunchedEffect(shareUris.isNotEmpty()) {
        if (shareUris.isNotEmpty()) discovery.refresh()
    }
    // 刷新中的无限旋转动效
    val spinAngle by rememberInfiniteTransition(label = "refreshSpin").animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(900, easing = LinearEasing)),
        label = "refreshSpinAngle",
    )
    // 相册（图片/视频）与文件共用的选中回调：拿到 uri 列表就发给点中的设备
    val onPicked: (List<android.net.Uri>?) -> Unit = { uris ->
        val device = pickedDevice
        if (device != null && !uris.isNullOrEmpty()) {
            Sender.send(context, device, uris, scope)
        }
        pickedDevice = null
    }
    val filePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments(), onPicked
    )
    val mediaPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(), onPicked
    )

    // 点中设备后先问来源：相册 or 文件（风格对齐接收确认弹窗）
    if (showSourceDialog) {
        val device = pickedDevice
        AlertDialog(
            onDismissRequest = {
                showSourceDialog = false
                pickedDevice = null
            },
            title = { Text("发送到 " + (device?.info?.alias ?: "")) },
            confirmButton = {},
            text = {
                Column {
                    Text("选择要发送的内容来源")
                    Spacer(modifier = Modifier.height(12.dp))
                    OutlinedButton(
                        onClick = {
                            showSourceDialog = false
                            mediaPicker.launch(
                                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo)
                            )
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("从相册选择")
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = {
                            showSourceDialog = false
                            filePicker.launch(arrayOf("*/*"))
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("从文件选择")
                    }
                }
            },
        )
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
        if (shareUris.isNotEmpty()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Row(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "待发送 " + shareUris.size + " 个文件，点选下方设备发送",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = { ShareInbox.uris = emptyList() }) {
                        Text("取消")
                    }
                }
            }
            Spacer(modifier = Modifier.height(8.dp))
        }
        val devices = DeviceStore.devices
        if (devices.isEmpty()) {
            Text(
                text = "未发现设备\n请确认对方在同一局域网并已打开应用，或点右上角刷新扫描",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        // 设备列表限高约 2.5 行，超出内部滚动翻找；剩余空间留给传输记录
        LazyColumn(
            modifier = Modifier.heightIn(max = 176.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(devices, key = { it.info.fingerprint }) { device ->
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            if (shareUris.isNotEmpty()) {
                                Sender.send(context, device, shareUris, scope)
                                ShareInbox.uris = emptyList()
                            } else {
                                pickedDevice = device
                                showSourceDialog = true
                            }
                        },
                ) {
                    Row(
                        modifier = Modifier.padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(device.info.alias, style = MaterialTheme.typography.titleSmall)
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = deviceTypeLabel(device.info.deviceType) + " · " + device.ip + " · 在线",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        // 在线状态绿点
                        Box(
                            modifier = Modifier
                                .size(10.dp)
                                .background(Color(0xFF4CAF50), CircleShape),
                        )
                    }
                }
            }
        }
        // 无任何传输记录时不显示记录区；有记录时与上方间距约为半个设备项高度
        if (TransferStore.records.isNotEmpty()) {
            Spacer(modifier = Modifier.height(32.dp))
            RecordsSection()
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
