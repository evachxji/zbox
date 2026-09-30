package com.zviber.transfer

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.lifecycleScope
import com.zviber.transfer.ui.DevicesScreen
import com.zviber.transfer.ui.ReceiveDialogHost
import com.zviber.transfer.ui.TransfersScreen
import fi.iki.elonen.NanoHTTPD
import java.security.SecureRandom

/** 本机设置：指纹（首次启动生成 32 位随机 hex）、别名、记住的保存目录 */
object Settings {
    private lateinit var prefs: SharedPreferences

    fun init(context: Context) {
        prefs = context.getSharedPreferences("zviber_transfer", Context.MODE_PRIVATE)
        if (prefs.getString("fingerprint", null) == null) {
            val bytes = ByteArray(16)
            SecureRandom().nextBytes(bytes)
            prefs.edit().putString("fingerprint", bytes.joinToString("") { "%02x".format(it) }).apply()
        }
    }

    val fingerprint: String
        get() = prefs.getString("fingerprint", "") ?: ""

    var alias: String
        get() = prefs.getString("alias", null) ?: ("Android-" + Build.MODEL)
        set(value) = prefs.edit().putString("alias", value).apply()

    var saveTreeUri: String?
        get() = prefs.getString("save_tree_uri", null)
        set(value) = prefs.edit().putString("save_tree_uri", value).apply()

    /** 本机 DeviceInfo（协议字段与 PC 端一致） */
    fun localInfo(): DeviceInfo = DeviceInfo(
        alias = alias,
        deviceModel = Build.MODEL,
        fingerprint = fingerprint,
    )
}

class MainActivity : ComponentActivity() {

    private lateinit var receiver: Receiver
    private lateinit var discovery: Discovery
    private var server: TransferServer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Settings.init(applicationContext)
        enableEdgeToEdge()

        receiver = Receiver(applicationContext)
        discovery = Discovery(applicationContext, lifecycleScope)

        setContent {
            ZviberApp(discovery)
        }
    }

    /** 仅前台传输：回到前台才起 HTTP 服务与组播发现 */
    override fun onStart() {
        super.onStart()
        val s = TransferServer(receiver)
        try {
            s.start(NanoHTTPD.SOCKET_READ_TIMEOUT, false)
            server = s
        } catch (_: Exception) {
            // 端口被占用时降级：仅发送方功能可用
        }
        discovery.start()
    }

    override fun onStop() {
        discovery.stop()
        try { server?.stop() } catch (_: Exception) {}
        server = null
        super.onStop()
    }
}

@androidx.compose.runtime.Composable
fun ZviberApp(discovery: Discovery) {
    var tab by remember { mutableIntStateOf(0) }
    MaterialTheme(colorScheme = darkColorScheme()) {
        Scaffold(
            bottomBar = {
                NavigationBar {
                    NavigationBarItem(
                        selected = tab == 0,
                        onClick = { tab = 0 },
                        icon = { Icon(Icons.Filled.Home, contentDescription = null) },
                        label = { Text("设备") },
                    )
                    NavigationBarItem(
                        selected = tab == 1,
                        onClick = { tab = 1 },
                        icon = { Icon(Icons.AutoMirrored.Filled.List, contentDescription = null) },
                        label = { Text("记录") },
                    )
                }
            },
        ) { padding ->
            Box(modifier = Modifier.padding(padding)) {
                if (tab == 0) DevicesScreen(discovery) else TransfersScreen()
                ReceiveDialogHost()
            }
        }
    }
}
