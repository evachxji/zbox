package com.zviber.transfer

import android.content.Context
import android.net.wifi.WifiManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.serialization.encodeToString
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.MulticastSocket
import java.net.NetworkInterface
import java.util.concurrent.TimeUnit

/**
 * 局域网发现：UDP 组播 announce / 监听 + /register 应答 + 手动 /24 子网扫描。
 * 协议：组播 224.0.0.168:53327，每 5 秒重发 announce，30 秒未见剔除。
 */
class Discovery(private val context: Context, private val scope: CoroutineScope) {

    @Volatile
    private var running = false

    private var listenSocket: MulticastSocket? = null
    private var sendSocket: DatagramSocket? = null
    private var multicastLock: WifiManager.MulticastLock? = null

    // 子网扫描专用短超时客户端
    private val scanClient = OkHttpClient.Builder()
        .connectTimeout(500, TimeUnit.MILLISECONDS)
        .readTimeout(500, TimeUnit.MILLISECONDS)
        .writeTimeout(500, TimeUnit.MILLISECONDS)
        .callTimeout(800, TimeUnit.MILLISECONDS)
        .build()

    // register 应答客户端
    private val replyClient = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .build()

    fun start() {
        if (running) return
        running = true
        // Android 接收组播必须持 MulticastLock
        val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        multicastLock = wifi.createMulticastLock("zviber-transfer").apply {
            setReferenceCounted(true)
            acquire()
        }
        scope.launch(Dispatchers.IO) { listenLoop() }
        scope.launch(Dispatchers.IO) { announceLoop() }
        scope.launch(Dispatchers.IO) { pruneLoop() }
    }

    fun stop() {
        running = false
        try { listenSocket?.close() } catch (_: Exception) {}
        try { sendSocket?.close() } catch (_: Exception) {}
        multicastLock?.let { if (it.isHeld) it.release() }
        multicastLock = null
    }

    /** 手动刷新：立即发一次 announce，并对本机 /24 子网逐 IP POST /register 扫描 */
    fun refresh() {
        scope.launch(Dispatchers.IO) {
            sendAnnounce()
            scanSubnet()
        }
    }

    // ---------- 组播监听 ----------

    private fun listenLoop() {
        try {
            val socket = MulticastSocket(PROTOCOL_PORT)
            val group = InetAddress.getByName(MULTICAST_GROUP)
            val nif = wifiInterface()
            if (nif != null) {
                socket.joinGroup(InetSocketAddress(group, PROTOCOL_PORT), nif)
            } else {
                @Suppress("DEPRECATION")
                socket.joinGroup(group)
            }
            listenSocket = socket
            val buf = ByteArray(8192)
            while (running) {
                val packet = DatagramPacket(buf, buf.size)
                try {
                    socket.receive(packet)
                } catch (e: Exception) {
                    if (!running) break
                    // 避免原地 continue 忙循环：等 1 秒再重试
                    try { Thread.sleep(1000) } catch (_: InterruptedException) {}
                    continue
                }
                val ip = packet.address?.hostAddress ?: continue
                val text = String(packet.data, 0, packet.length, Charsets.UTF_8)
                handleAnnounce(text, ip)
            }
        } catch (_: Exception) {
            // 组播不可用时静默退化，仍可用手动扫描
        }
    }

    private fun handleAnnounce(text: String, ip: String) {
        val info = try {
            protoJson.decodeFromString<DeviceInfo>(text)
        } catch (_: Exception) {
            return
        }
        if (info.fingerprint == Settings.fingerprint) return
        DeviceStore.upsert(info, ip)
        // 收到他人 announce → 向其 POST /register 应答，让对方也登记本机
        if (info.announce == true) {
            postRegister(ip, info.port, replyClient)
        }
    }

    // ---------- announce 广播 ----------

    private suspend fun announceLoop() {
        while (running) {
            sendAnnounce()
            delay(5_000)
        }
    }

    private fun sendAnnounce() {
        try {
            if (sendSocket == null || sendSocket?.isClosed == true) {
                sendSocket = DatagramSocket()
            }
            val payload = protoJson.encodeToString(Settings.localInfo().copy(announce = true))
                .toByteArray(Charsets.UTF_8)
            val packet = DatagramPacket(
                payload, payload.size,
                InetAddress.getByName(MULTICAST_GROUP), PROTOCOL_PORT,
            )
            sendSocket?.send(packet)
        } catch (_: Exception) {
        }
    }

    // ---------- register 应答 / 子网扫描 ----------

    /** 向指定 IP 的指定端口 POST /register；成功则登记对方设备（port <= 0 时回退 53327） */
    private fun postRegister(ip: String, port: Int, client: OkHttpClient) {
        try {
            val body = protoJson.encodeToString(Settings.localInfo())
                .toRequestBody("application/json".toMediaType())
            val request = Request.Builder()
                .url("http://$ip:${if (port > 0) port else PROTOCOL_PORT}$API_PREFIX/register")
                .post(body)
                .build()
            client.newCall(request).execute().use { resp ->
                if (resp.isSuccessful) {
                    val text = resp.body?.string() ?: return
                    val info = try { protoJson.decodeFromString<DeviceInfo>(text) } catch (_: Exception) { return }
                    if (info.fingerprint != Settings.fingerprint) {
                        DeviceStore.upsert(info, ip)
                    }
                }
            }
        } catch (_: Exception) {
        }
    }

    private suspend fun scanSubnet() {
        val localIp = localIpAddress() ?: return
        val prefix = localIp.substringBeforeLast('.')
        val semaphore = Semaphore(64)
        coroutineScope {
            (1..254).map { i ->
                async(Dispatchers.IO) {
                    val ip = "$prefix.$i"
                    if (ip == localIp) return@async
                    semaphore.withPermit { postRegister(ip, PROTOCOL_PORT, scanClient) }
                }
            }.forEach { it.await() }
        }
    }

    // ---------- 30 秒剔除 ----------

    private suspend fun pruneLoop() {
        while (running) {
            delay(5_000)
            DeviceStore.prune()
        }
    }

    // ---------- 网卡工具 ----------

    private fun wifiInterface(): NetworkInterface? {
        val interfaces = NetworkInterface.getNetworkInterfaces() ?: return null
        for (nif in interfaces) {
            try {
                if (!nif.isUp || nif.isLoopback) continue
                val hasV4 = nif.inetAddresses.toList().any { it is Inet4Address && !it.isLoopbackAddress }
                if (hasV4) return nif
            } catch (_: Exception) {
            }
        }
        return null
    }

    private fun localIpAddress(): String? {
        val nif = wifiInterface() ?: return null
        return nif.inetAddresses.toList()
            .firstOrNull { it is Inet4Address && !it.isLoopbackAddress }
            ?.hostAddress
    }
}
