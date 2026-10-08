/**
 * 发送方：prepare-upload 协商（403 = 对方拒绝）→ 逐文件流式上传 → 失败调 cancel。
 * 流程对齐 Android 端 Sender.kt；上传用 TCPSocket 手写 HTTP POST
 * （axios 要整文件读进内存，大文件与进度/取消都不可行——参考项目就有这个内存炸弹）。
 */
import axios, { AxiosError, AxiosResponse } from '@ohos/axios'
import { socket } from '@kit.NetworkKit'
import { fileIo as fs } from '@kit.CoreFileKit'
import { util } from '@kit.ArkTS'
import { LogUtil } from '@pura/harmony-utils'
import {
  API_PREFIX,
  FileMeta,
  PeerDevice,
  PROTOCOL_PORT,
  TransferRecord,
  TransferStatus,
  TransferStore,
  deviceInfoToJson,
} from '../protocol/Protocol'
import { localInfo } from './Settings'

const PREPARE_TIMEOUT_MS = 5 * 60_000   // prepare-upload 需等对方用户确认（对齐 Android 端 5 分钟）
const CONNECT_TIMEOUT_MS = 5_000
const READ_CHUNK = 64 * 1024

class OutFile {
  meta: FileMeta
  uri: string
  record: TransferRecord

  constructor(meta: FileMeta, uri: string, record: TransferRecord) {
    this.meta = meta
    this.uri = uri
    this.record = record
  }
}

/** 进行中的发送会话：供 UI 按记录取消 */
class ActiveSession {
  records: TransferRecord[] = []
  cancelled: boolean = false
  tcp: socket.TCPSocket | null = null
  base: string = ''
  sessionId: string = ''
}

// 记录 id -> 发送会话（仅进行中保留在表里）
const activeByRecord: Map<string, ActiveSession> = new Map()

/** 是否有正在发送中的会话（供 UIAbility 判断退后台是否保持服务） */
export function hasActiveSending(): boolean {
  return activeByRecord.size > 0
}

/** 入口：收集元数据 → prepare → 逐文件上传 */
export function sendFiles(device: PeerDevice, uris: string[]): void {
  const session = new ActiveSession()
  doSend(device, uris, session).catch((e: Object) => {
    LogUtil.error(`send failed: ${JSON.stringify(e)}`)
  })
}

/** 取消某条记录所属的发送会话：中断当前请求，通知对端 cancel，记录置「已取消」 */
export function cancelRecord(recordId: string): void {
  const session = activeByRecord.get(recordId)
  if (session === undefined) {
    return
  }
  session.cancelled = true
  try {
    session.tcp?.close()
  } catch (e) {
  }
  session.records.forEach((r) => {
    if (r.status !== TransferStatus.DONE) {
      r.status = TransferStatus.CANCELED
    }
  })
  TransferStore.notify()
  if (session.base.length > 0 && session.sessionId.length > 0) {
    postCancel(session.base, session.sessionId)
  }
}

async function doSend(device: PeerDevice, uris: string[], session: ActiveSession): Promise<void> {
  const base = `http://${device.ip}:${PROTOCOL_PORT}${API_PREFIX}`
  session.base = base

  // 1. 收集元数据（id = uuid；协议要求必须知道长度，读不出大小的文件直接拒发）
  const files: OutFile[] = []
  for (const uri of uris) {
    const meta = queryMeta(uri)
    if (meta === null) {
      const record = new TransferRecord(util.generateRandomUUID(false), true, device.info.alias,
        displayName(uri), -1)
      record.status = TransferStatus.FAILED
      record.error = '无法读取文件'
      record.savedPath = uri
      TransferStore.add(record)
      continue
    }
    const record = new TransferRecord(meta.id, true, device.info.alias, meta.fileName, meta.size)
    record.savedPath = uri
    TransferStore.add(record)
    files.push(new OutFile(meta, uri, record))
    session.records.push(record)
    activeByRecord.set(record.id, session)
  }
  if (files.length === 0) {
    return
  }

  try {
    // 2. prepare-upload（读超时放宽到 5 分钟，等对方手动确认）
    const filesMap: Record<string, FileMeta> = {}
    files.forEach((f) => {
      filesMap[f.meta.id] = f.meta
    })
    const reqBody: Record<string, Object> = {
      'info': JSON.parse(deviceInfoToJson(localInfo(), false)) as Object,
      'files': filesMap as Object,
    }
    let prepareResp: AxiosResponse<Object>
    try {
      prepareResp = await axios.post<Object, AxiosResponse<Object>, string>(
        `${base}/prepare-upload`, JSON.stringify(reqBody), {
          timeout: PREPARE_TIMEOUT_MS,
          headers: { 'Content-Type': 'application/json' },
        })
    } catch (e) {
      handlePrepareError(e as AxiosError, files)
      return
    }
    const data = JSON.parse(JSON.stringify(prepareResp.data)) as Record<string, Object>
    const sessionId = data['sessionId'] as string
    const tokens = data['files'] as Record<string, string>
    session.sessionId = sessionId

    // 应答刚到就被取消：补发 cancel 通知对端（幂等）
    if (session.cancelled) {
      postCancel(base, sessionId)
      return
    }

    // 3. 逐文件流式上传
    files.forEach((f) => {
      f.record.status = TransferStatus.TRANSFERRING
    })
    TransferStore.notify()
    for (const file of files) {
      const token = tokens[file.meta.id]
      if (token === undefined) {
        failRecord(file.record, '对方未接受该文件')
        continue
      }
      const ok = await uploadOne(device.ip, sessionId, token, file, session)
      if (!ok) {
        if (session.cancelled) {
          return
        }
        // 失败即中止整批：通知对方 cancel，其余未传文件标记为已取消
        postCancel(base, sessionId)
        files.filter((f) => f.record.status === TransferStatus.TRANSFERRING && f.meta.id !== file.meta.id)
          .forEach((f) => {
            f.record.status = TransferStatus.CANCELED
          })
        TransferStore.notify()
        return
      }
    }
  } finally {
    files.forEach((f) => {
      activeByRecord.delete(f.record.id)
    })
  }
}

/** 单文件上传：TCPSocket 手写 HTTP POST，64KB 分块从文件读，边发边报进度 */
async function uploadOne(ip: string, sessionId: string, token: string,
  file: OutFile, session: ActiveSession): Promise<boolean> {
  const tcp = socket.constructTCPSocketInstance()
  session.tcp = tcp
  try {
    await tcp.connect({
      address: { address: ip, port: PROTOCOL_PORT, family: 1 },
      timeout: CONNECT_TIMEOUT_MS,
    })
  } catch (e) {
    if (!session.cancelled) {
      failRecord(file.record, '无法连接对方设备（对方可能已退出或换了网络）')
    }
    return false
  }

  const url = `${API_PREFIX}/upload?sessionId=${sessionId}&fileId=${file.meta.id}&token=${token}`
  const header = `POST ${url} HTTP/1.1\r\n` +
    `Host: ${ip}:${PROTOCOL_PORT}\r\n` +
    `Content-Type: application/octet-stream\r\n` +
    `Content-Length: ${file.meta.size}\r\n` +
    `Connection: close\r\n\r\n`

  // 响应收取：连接关闭前累计报文，看到 \r\n\r\n 就能解析状态行
  const responsePromise = new Promise<number>((resolve) => {
    let raw = ''
    tcp.on('message', (value: socket.SocketMessageInfo) => {
      const decoder = util.TextDecoder.create('utf-8')
      raw += decoder.decodeToString(new Uint8Array(value.message))
      const headEnd = raw.indexOf('\r\n\r\n')
      if (headEnd >= 0) {
        const statusLine = raw.substring(0, raw.indexOf('\r\n'))
        const parts = statusLine.split(' ')
        resolve(parts.length >= 2 ? Number(parts[1]) : 0)
      }
    })
    tcp.on('close', () => {
      resolve(0)
    })
    setTimeout(() => resolve(0), PREPARE_TIMEOUT_MS)
  })

  try {
    await tcp.send({ data: header })
    const fdFile = fs.openSync(file.uri, fs.OpenMode.READ_ONLY)
    try {
      let offset = 0
      const buf = new ArrayBuffer(READ_CHUNK)
      while (offset < file.meta.size) {
        if (session.cancelled) {
          return false
        }
        const n = fs.readSync(fdFile.fd, buf, { offset: offset, length: READ_CHUNK })
        if (n <= 0) {
          break
        }
        await tcp.send({ data: n === READ_CHUNK ? buf : buf.slice(0, n) })
        offset += n
        file.record.progress = offset
        file.record.sampleSpeed()
        TransferStore.notify()
      }
    } finally {
      fs.closeSync(fdFile)
    }

    const status = await responsePromise
    if (status === 200) {
      file.record.progress = file.meta.size
      file.record.status = TransferStatus.DONE
      TransferStore.notify()
      return true
    }
    if (!session.cancelled) {
      failRecord(file.record, status > 0 ? `上传失败：HTTP ${status}` : '连接被中断')
    }
    return false
  } catch (e) {
    if (!session.cancelled) {
      failRecord(file.record, friendlySendError(e))
    }
    return false
  } finally {
    session.tcp = null
    try {
      tcp.close()
    } catch (e) {
    }
    tcp.off('message')
    tcp.off('close')
  }
}

/** 通知对端中止会话（幂等，失败静默） */
function postCancel(base: string, sessionId: string): void {
  axios.post(`${base}/cancel?sessionId=${sessionId}`, '', { timeout: 5000 })
    .catch(() => {
    })
}

function handlePrepareError(e: AxiosError, files: OutFile[]): void {
  const status = e.response?.status ?? 0
  let message: string
  if (status === 403) {
    files.forEach((f) => {
      f.record.status = TransferStatus.REJECTED
    })
    TransferStore.notify()
    return
  } else if (status === 409) {
    message = '对方正忙'
  } else if (status > 0) {
    message = `协商失败：HTTP ${status}`
  } else {
    message = friendlySendError(e)
  }
  files.forEach((f) => {
    failRecord(f.record, message)
  })
}

function failRecord(record: TransferRecord, message: string): void {
  record.status = TransferStatus.FAILED
  record.error = message
  TransferStore.notify()
}

/** 从 picker uri 读出文件名与大小；读不出大小返回 null（协议必须知道长度） */
function queryMeta(uri: string): FileMeta | null {
  try {
    const file = fs.openSync(uri, fs.OpenMode.READ_ONLY)
    try {
      const stat = fs.statSync(file.fd)
      const id = util.generateRandomUUID(false)
      return {
        id: id,
        fileName: displayName(uri),
        size: stat.size,
        fileType: mimeFromName(displayName(uri)),
        sha256: '',
      }
    } finally {
      fs.closeSync(file)
    }
  } catch (e) {
    LogUtil.error(`queryMeta failed for ${uri}: ${JSON.stringify(e)}`)
    return null
  }
}

function displayName(uri: string): string {
  const slash = uri.lastIndexOf('/')
  const raw = slash >= 0 ? uri.substring(slash + 1) : uri
  const decoded = decodeURI(raw)
  return decoded.length > 0 ? decoded : 'file'
}

function mimeFromName(fileName: string): string {
  const dot = fileName.lastIndexOf('.')
  if (dot < 0) {
    return 'application/octet-stream'
  }
  const ext = fileName.substring(dot + 1).toLowerCase()
  const table: Record<string, string> = {
    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif',
    'webp': 'image/webp', 'mp4': 'video/mp4', 'mp3': 'audio/mpeg', 'wav': 'audio/wav',
    'pdf': 'application/pdf', 'zip': 'application/zip', 'txt': 'text/plain',
    'doc': 'application/msword', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xls': 'application/vnd.ms-excel', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  }
  return table[ext] ?? 'application/octet-stream'
}

/** 把底层异常翻译成用户可读的中文提示（记录页展示用，对齐 Android friendlyNetError） */
function friendlySendError(e: Object): string {
  const msg = JSON.stringify(e)
  if (msg.indexOf('timeout') >= 0 || msg.indexOf('timed out') >= 0) {
    return '连接或传输超时，请重试'
  }
  if (msg.indexOf('ECONNREFUSED') >= 0 || msg.indexOf('refused') >= 0) {
    return '无法连接对方设备（对方可能已退出或换了网络）'
  }
  if (msg.indexOf('ENOSPC') >= 0 || msg.indexOf('No space left') >= 0) {
    return '存储空间不足'
  }
  return '发送失败'
}