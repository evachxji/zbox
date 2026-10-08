/**
 * 协议常量、数据类型与运行期状态 store。
 * 常量与 PC 端 transfer.py / Android 端 Protocol.kt 逐字节一致：
 * zbox 是 LocalSend v2 的私有实例（组播 224.0.0.168、端口 53327），与官方 LocalSend 不互通。
 */

export const PROTOCOL_PORT: number = 53327
export const MULTICAST_GROUP: string = '224.0.0.168'
export const API_PREFIX: string = '/api/localsend/v2'

/** 设备信息（announce / register / info / prepare-upload 共用） */
export interface DeviceInfo {
  alias: string
  version: string
  deviceModel: string
  deviceType: string
  fingerprint: string
  port: number
  protocol: string
  announce: boolean  // 仅组播 announce 报文带 true，其余请求为 false（序列化时省略）
}

/** 文件元数据 */
export interface FileMeta {
  id: string
  fileName: string
  size: number
  fileType: string
  sha256: string
}

/** 序列化本机 DeviceInfo：announce=false 时省略该字段（对齐 Android 端 null 省略语义） */
export function deviceInfoToJson(info: DeviceInfo, announce: boolean): string {
  const obj: Record<string, Object> = {
    'alias': info.alias,
    'version': info.version,
    'deviceModel': info.deviceModel,
    'deviceType': info.deviceType,
    'fingerprint': info.fingerprint,
    'port': info.port,
    'protocol': info.protocol,
  }
  if (announce) {
    obj['announce'] = true
  }
  return JSON.stringify(obj)
}

/** 容忍未知字段的 DeviceInfo 解析；缺关键字段返回 null */
export function parseDeviceInfo(text: string): DeviceInfo | null {
  try {
    const obj = JSON.parse(text) as Record<string, Object>
    if (typeof obj['alias'] !== 'string' || typeof obj['fingerprint'] !== 'string') {
      return null
    }
    const portNum = Number(obj['port'] ?? PROTOCOL_PORT)
    const info: DeviceInfo = {
      alias: obj['alias'] as string,
      version: typeof obj['version'] === 'string' ? obj['version'] as string : '2.0',
      deviceModel: typeof obj['deviceModel'] === 'string' ? obj['deviceModel'] as string : '',
      deviceType: typeof obj['deviceType'] === 'string' ? obj['deviceType'] as string : 'mobile',
      fingerprint: obj['fingerprint'] as string,
      port: portNum > 0 && Number.isInteger(portNum) ? portNum : PROTOCOL_PORT,
      protocol: typeof obj['protocol'] === 'string' ? obj['protocol'] as string : 'http',
      announce: obj['announce'] === true,
    }
    return info
  } catch (e) {
    return null
  }
}

// ===================== 运行期状态（listener 通知 UI 重渲染） =====================

type ChangeListener = () => void

/** 发现的局域网对端设备 */
export class PeerDevice {
  info: DeviceInfo
  ip: string

  constructor(info: DeviceInfo, ip: string) {
    this.info = info
    this.ip = ip
  }
}

/** 设备表：按 fingerprint 去重，LocalSend 语义不做 TTL 剔除（刷新=清空重建） */
export class DeviceStore {
  private static list: PeerDevice[] = []
  private static listeners: Set<ChangeListener> = new Set()

  static onChange(cb: ChangeListener): void {
    DeviceStore.listeners.add(cb)
  }

  static offChange(cb: ChangeListener): void {
    DeviceStore.listeners.delete(cb)
  }

  private static notify(): void {
    DeviceStore.listeners.forEach((cb) => cb())
  }

  static upsert(info: DeviceInfo, ip: string): void {
    const idx = DeviceStore.list.findIndex((d) => d.info.fingerprint === info.fingerprint)
    if (idx >= 0) {
      DeviceStore.list[idx] = new PeerDevice(info, ip)
    } else {
      DeviceStore.list.push(new PeerDevice(info, ip))
    }
    DeviceStore.notify()
  }

  static clear(): void {
    DeviceStore.list = []
    DeviceStore.notify()
  }

  static snapshot(): PeerDevice[] {
    return DeviceStore.list.slice()
  }

  static isEmpty(): boolean {
    return DeviceStore.list.length === 0
  }
}

/** 传输状态 */
export enum TransferStatus {
  WAITING,
  TRANSFERRING,
  DONE,
  FAILED,
  REJECTED,
  CANCELED,
}

export function statusLabel(s: TransferStatus): string {
  switch (s) {
    case TransferStatus.WAITING: return '等待确认'
    case TransferStatus.TRANSFERRING: return '传输中'
    case TransferStatus.DONE: return '完成'
    case TransferStatus.FAILED: return '失败'
    case TransferStatus.REJECTED: return '被拒绝'
    case TransferStatus.CANCELED: return '已取消'
    default: return ''
  }
}

/** 一条传输记录（@Observed：进度/状态原地修改直接驱动记录行重渲染） */
@Observed
export class TransferRecord {
  id: string
  outgoing: boolean
  peerAlias: string
  fileName: string
  size: number
  progress: number = 0
  status: TransferStatus = TransferStatus.WAITING
  error: string = ''
  speedBps: number = 0      // EMA 平滑后的传输速度（字节/秒）
  savedPath: string = ''    // 接收=沙箱落盘路径，发送=源文件 uri（导出/定位用）

  private lastTickAt: number = 0
  private lastTickProgress: number = 0

  constructor(id: string, outgoing: boolean, peerAlias: string, fileName: string, size: number) {
    this.id = id
    this.outgoing = outgoing
    this.peerAlias = peerAlias
    this.fileName = fileName
    this.size = size
  }

  /** 进度帧采样：增量算瞬时速度并做指数平滑（对齐 Android 端 TransferRecord.sampleSpeed） */
  sampleSpeed(): void {
    const now = Date.now()
    if (this.lastTickAt === 0) {
      this.lastTickAt = now
      this.lastTickProgress = this.progress
      return
    }
    const dt = now - this.lastTickAt
    const dp = this.progress - this.lastTickProgress
    if (dp > 0 && dt > 200) {
      const instant = dp * 1000 / dt
      this.speedBps = this.speedBps === 0 ? instant : Math.floor(this.speedBps / 2 + instant / 2)
      this.lastTickAt = now
      this.lastTickProgress = this.progress
    }
  }

  isActive(): boolean {
    return this.status === TransferStatus.WAITING || this.status === TransferStatus.TRANSFERRING
  }
}

/** 传输记录表（新记录插到最前） */
export class TransferStore {
  private static list: TransferRecord[] = []
  private static listeners: Set<ChangeListener> = new Set()

  static onChange(cb: ChangeListener): void {
    TransferStore.listeners.add(cb)
  }

  static offChange(cb: ChangeListener): void {
    TransferStore.listeners.delete(cb)
  }

  /** 进度/状态原地修改后调用，驱动 UI 重渲染 */
  static notify(): void {
    TransferStore.listeners.forEach((cb) => cb())
  }

  static add(record: TransferRecord): void {
    TransferStore.list.unshift(record)
    TransferStore.notify()
  }

  static snapshot(): TransferRecord[] {
    return TransferStore.list.slice()
  }
}