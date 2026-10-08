/**
 * 局域网发现：UDP 组播 announce / 监听 + /register 应答 + 手动 /24 子网扫描。
 * 行为对齐 Android 端 Discovery.kt：
 *   启动时宣告一次；收到他人 announce 回 POST /register；不做 TTL 剔除；
 *   刷新 = 清空列表重新宣告，3 秒组播宽限内无设备才回退子网扫描（并发 64、500ms 超时）。
 * 组播收发 API 用法参考 LocalSendLite_HarmonyOS_NEXT 的 utils/UDPBroadcast.ets
 * （MIT，见 harmony/NOTICE）；它只发不收（未 addMembership），这里补上了入组监听。
 */
import { connection, socket } from '@kit.NetworkKit'
import axios, { AxiosResponse } from '@ohos/axios'
import { LogUtil } from '@pura/harmony-utils'
import { util } from '@kit.ArkTS'
import {
  API_PREFIX,
  DeviceInfo,
  DeviceStore,
  MULTICAST_GROUP,
  PROTOCOL_PORT,
  deviceInfoToJson,
  parseDeviceInfo,
} from '../protocol/Protocol'
import { fingerprint, localInfo } from './Settings'

let running = false
let listenSock: socket.MulticastSocket | null = null
let sendSock: socket.UDPSocket | null = null

export function startDiscovery(): void {
  if (running) {
    return
  }
  running = true
  startListen()
  sendAnnounce()  // LocalSend 语义：只在启动时宣告一次
}

export function stopDiscovery(): void {
  running = false
  try {
    listenSock?.close()
  } catch (e) {
  }
  try {
    sendSock?.close()
  } catch (e) {
  }
  listenSock = null
  sendSock = null
}

/** 手动刷新：清空设备列表并重新宣告一次，只信本次应答；
 *  组播宽限（3 秒）内一台都没有才回退 /24 子网扫描；完成后回调 onDone */
export function refreshDiscovery(onDone?: () => void): void {
  DeviceStore.clear()
  sendAnnounce()
  setTimeout(async () => {
    if (DeviceStore.isEmpty()) {
      await scanSubnet()
    }
    onDone?.()
  }, 3000)
}

/** 手动按 IP 添加设备：GET /info 探活并登记。
 *  组播失效时的兜底；也用于模拟器联调（模拟器里宿主机固定 10.0.2.2）。 */
export async function addDeviceByIp(ip: string): Promise<boolean> {
  try {
    const url = `http://${ip}:${PROTOCOL_PORT}${API_PREFIX}/info`
    const resp: AxiosResponse<Object> = await axios.get<Object, AxiosResponse<Object>>(url, { timeout: 2000 })
    const info = parseDeviceInfo(JSON.stringify(resp.data))
    if (info !== null && info.fingerprint !== fingerprint()) {
      DeviceStore.upsert(info, ip)
      return true
    }
  } catch (e) {
  }
  return false
}

// ---------- 组播监听 ----------

async function startListen(): Promise<void> {
  try {
    const udp = socket.constructMulticastSocketInstance()
    const localAddr: socket.NetAddress = { address: '0.0.0.0', port: PROTOCOL_PORT, family: 1 }
    await udp.bind(localAddr)
    try {
      await udp.addMembership({ address: MULTICAST_GROUP, port: PROTOCOL_PORT, family: 1 })
      LogUtil.info('addMembership 224.0.0.168 ok')
    } catch (err) {
      // 组播入组失败不致命：降级为仅子网扫描（参考项目就是纯扫描路线）
      LogUtil.error(`addMembership failed: ${JSON.stringify(err)}`)
    }
    udp.on('message', (value: socket.SocketMessageInfo) => {
      if (!running) {
        return
      }
      const text = decodeUtf8(value.message)
      handleAnnounce(text, value.remoteInfo.address)
    })
    listenSock = udp
  } catch (err) {
    LogUtil.error(`discovery listen failed: ${JSON.stringify(err)}`)
  }
}

function decodeUtf8(buf: ArrayBuffer): string {
  const decoder = util.TextDecoder.create('utf-8')
  return decoder.decodeToString(new Uint8Array(buf))
}

function handleAnnounce(text: string, ip: string): void {
  const info = parseDeviceInfo(text)
  if (info === null || info.fingerprint === fingerprint()) {
    return
  }
  DeviceStore.upsert(info, ip)
  // 收到他人 announce → 向其 POST /register 应答，让对方也登记本机
  if (info.announce) {
    postRegister(ip, info.port, 2000)
  }
}

// ---------- announce 广播 ----------

async function sendAnnounce(): Promise<void> {
  try {
    if (sendSock === null) {
      sendSock = socket.constructUDPSocketInstance()
      // OHOS 的 UDPSocket 必须先 bind 才能 send（不 bind 直接发报 Bad file descriptor）
      await sendSock.bind({ address: '0.0.0.0', port: 0, family: 1 })
    }
    const payload = deviceInfoToJson(localInfo(), true)
    const target: socket.NetAddress = { address: MULTICAST_GROUP, port: PROTOCOL_PORT, family: 1 }
    await sendSock.send({ address: target, data: payload })
    LogUtil.info('announce sent')
  } catch (err) {
    LogUtil.error(`announce failed: ${JSON.stringify(err)}`)
  }
}

/** 本机第一个非回环 IPv4 地址；拿不到返回空串 */
function localIpv4(): string {
  try {
    const handle = connection.getDefaultNetSync()
    const props = connection.getConnectionPropertiesSync(handle)
    for (const la of props.linkAddresses) {
      if (la.address.family === 1 && !la.address.address.startsWith('127.')) {
        return la.address.address
      }
    }
  } catch (e) {
    LogUtil.error(`localIpv4 failed: ${JSON.stringify(e)}`)
  }
  return ''
}

// ---------- register 应答 / 子网扫描 ----------

/** 向指定 IP 的指定端口 POST /register；成功则登记对方设备 */
async function postRegister(ip: string, port: number, timeoutMs: number): Promise<void> {
  try {
    const url = `http://${ip}:${port > 0 ? port : PROTOCOL_PORT}${API_PREFIX}/register`
    const resp: AxiosResponse<Object> =
      await axios.post<Object, AxiosResponse<Object>, string>(url, deviceInfoToJson(localInfo(), false), {
        timeout: timeoutMs,
        headers: { 'Content-Type': 'application/json' },
      })
    const info = parseDeviceInfo(JSON.stringify(resp.data))
    if (info !== null && info.fingerprint !== fingerprint()) {
      DeviceStore.upsert(info, ip)
    }
  } catch (e) {
    // 扫不到是常态，静默
  }
}

async function scanSubnet(): Promise<void> {
  // 本机 IPv4 走 connection.getConnectionProperties（NetworkUtil.getIpAddress 靠 Wi-Fi
  // GetIpInfo，模拟器/部分机型拿不到会返回 0.0.0.0——实测坑）
  let localIp = localIpv4()
  LogUtil.info(`scanSubnet start, localIp=${localIp}`)
  if (localIp.length === 0) {
    return
  }
  const prefix = localIp.substring(0, localIp.lastIndexOf('.'))
  const targets: string[] = []
  for (let i = 1; i <= 254; i++) {
    const ip = `${prefix}.${i}`
    if (ip !== localIp) {
      targets.push(ip)
    }
  }
  // 并发上限 64（对齐 Android 端 Semaphore(64)）
  const CHUNK = 64
  for (let off = 0; off < targets.length; off += CHUNK) {
    if (!running) {
      return
    }
    const batch = targets.slice(off, off + CHUNK)
    await Promise.all(batch.map((ip) => postRegister(ip, PROTOCOL_PORT, 500)))
  }
  LogUtil.info(`scanSubnet done, devices=${DeviceStore.snapshot().length}`)
}