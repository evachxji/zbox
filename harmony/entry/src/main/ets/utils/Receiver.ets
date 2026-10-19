/**
 * 接收方核心：prepare-upload 会话状态机 + upload 落盘 + cancel 清理半成品。
 * 语义逐条对齐 PC 端 transfer.py 与 Android 端 Receiver.kt：
 *   错误码 400 参数/会话无效，403 拒绝或 token/IP 错误，409 会话冲突/状态不可写，
 *   422 sha256 校验失败，500 内部错误；并发 prepare 冲突回 409；
 *   等待确认超 180 秒按拒绝处理；PENDING 会话超 10 分钟清过期。
 * 与 Android 端的差异（鸿蒙平台约束）：接收一律落应用沙箱 files/received/，
 * 由记录页「导出」经系统保存面板放到用户指定位置（picker 用法参考
 * LocalSendLite_HarmonyOS_NEXT，MIT，见 harmony/NOTICE）。
 */
import { Request, ServerResponse } from '@ohos/polka'
import { fileIo as fs } from '@kit.CoreFileKit'
import { cryptoFramework } from '@kit.CryptoArchitectureKit'
import { url, util } from '@kit.ArkTS'
import { LogUtil } from '@pura/harmony-utils'
import {
  DeviceStore,
  FileMeta,
  TransferRecord,
  TransferStatus,
  TransferStore,
  parseDeviceInfo,
} from '../protocol/Protocol'
import { fingerprint } from './Settings'

const PREPARE_TIMEOUT_MS = 180_000   // prepare-upload 等用户确认的最长时长（对齐 PC PREPARE_TIMEOUT）
const STALE_PENDING_MS = 10 * 60_000 // PENDING 会话过期时长（对齐 Android purgeStaleSessions）
const WRITE_CHUNK = 64 * 1024

type SessionState = 'pending' | 'accepted' | 'transferring' | 'rejected' | 'cancelled' | 'done'

class Session {
  sessionId: string
  remoteAlias: string
  remoteIp: string
  files: FileMeta[]
  tokens: Map<string, string>
  record: TransferRecord           // 整会话一条记录（对齐 PC 端）：总大小 + 聚合进度
  createdAt: number = Date.now()
  state: SessionState = 'pending'
  cancelled: boolean = false
  currentPath: string = ''         // 正在写入的半成品路径（cancel 时删除）
  saved: Set<string> = new Set()   // 已完整落盘的 fileId
  bytesDone: number = 0            // 已完整落盘的累计字节（当前文件进度 = bytesDone + 本文件已收）
  decisionResolve: (accepted: boolean) => void = () => {}

  constructor(sessionId: string, remoteAlias: string, remoteIp: string,
    files: FileMeta[], tokens: Map<string, string>, record: TransferRecord) {
    this.sessionId = sessionId
    this.remoteAlias = remoteAlias
    this.remoteIp = remoteIp
    this.files = files
    this.tokens = tokens
    this.record = record
  }
}

/** 等待用户确认的接收请求（驱动接收弹窗） */
export class PendingRequest {
  sessionId: string
  fromAlias: string
  files: FileMeta[]
  onAccept: () => void
  onReject: () => void

  constructor(sessionId: string, fromAlias: string, files: FileMeta[],
    onAccept: () => void, onReject: () => void) {
    this.sessionId = sessionId
    this.fromAlias = fromAlias
    this.files = files
    this.onAccept = onAccept
    this.onReject = onReject
  }

  totalSize(): number {
    let total = 0
    this.files.forEach((f) => { total += f.size })
    return total
  }
}

/** 当前待确认的接收请求（UI 监听） */
export class IncomingState {
  static pending: PendingRequest | null = null
  private static listeners: Set<() => void> = new Set()

  static onChange(cb: () => void): void {
    IncomingState.listeners.add(cb)
  }

  static offChange(cb: () => void): void {
    IncomingState.listeners.delete(cb)
  }

  private static notify(): void {
    IncomingState.listeners.forEach((cb) => cb())
  }

  static show(request: PendingRequest): void {
    IncomingState.pending = request
    IncomingState.notify()
  }

  static clear(sessionId: string): void {
    if (IncomingState.pending?.sessionId === sessionId) {
      IncomingState.pending = null
      IncomingState.notify()
    }
  }
}

export class Receiver {
  private sessions: Map<string, Session> = new Map()
  private saveDir: string

  /** saveDir = 应用沙箱 files 目录（接收文件落在其下 received/ 子目录） */
  constructor(filesDir: string) {
    this.saveDir = filesDir + '/received'
  }

  /** 是否有已接受/传输中的接收会话（供 UIAbility 判断退后台是否保持服务） */
  hasActive(): boolean {
    let active = false
    this.sessions.forEach((s) => {
      if (s.state === 'accepted' || s.state === 'transferring') {
        active = true
      }
    })
    return active
  }

  // ---------- POST /prepare-upload ----------

  async handlePrepare(req: Request, res: ServerResponse): Promise<void> {
    const text = bodyText(req)
    let body: Record<string, Object>
    try {
      body = JSON.parse(text) as Record<string, Object>
    } catch (e) {
      sendError(res, 400, 'invalid json')
      return
    }
    const infoRaw = body['info']
    const filesRaw = body['files']
    if (infoRaw === undefined || filesRaw === undefined) {
      sendError(res, 400, 'missing info or files')
      return
    }
    const info = parseDeviceInfo(JSON.stringify(infoRaw))
    const filesObj = filesRaw as Record<string, Record<string, Object>>
    const fileIds = Object.keys(filesObj)
    if (info === null || fileIds.length === 0) {
      sendError(res, 400, 'missing info or files')
      return
    }
    const metas: FileMeta[] = []
    for (const id of fileIds) {
      const m = filesObj[id]
      const size = m['size']
      if (typeof size !== 'number' || size < 0) {
        sendError(res, 400, 'invalid file size')
        return
      }
      const meta: FileMeta = {
        id: id,
        fileName: typeof m['fileName'] === 'string' ? m['fileName'] as string : id,
        size: size,
        fileType: typeof m['fileType'] === 'string' ? m['fileType'] as string : 'application/octet-stream',
        sha256: typeof m['sha256'] === 'string' ? m['sha256'] as string : '',
      }
      const p = m['path']
      if (typeof p === 'string') {
        meta.path = p as string
      }
      metas.push(meta)
    }

    const remoteIp = req.getRemoteIpAddress() ?? ''
    if (remoteIp.length > 0) {
      DeviceStore.upsert(info, remoteIp)
    }
    this.purgeStaleSessions()

    // PENDING 检查 + 插入必须原子，并发 prepare 不能双通过（对齐 Android 端）
    const conflict = this.hasPending()
    if (conflict) {
      sendError(res, 409, 'another session is waiting for confirmation')
      return
    }

    const sessionId = util.generateRandomUUID(false)
    const tokens = new Map<string, string>()
    let totalSize = 0
    metas.forEach((meta) => {
      tokens.set(meta.id, util.generateRandomUUID(false).replace(/-/g, ''))
      totalSize += meta.size
    })
    const record = new TransferRecord(sessionId, false, info.alias, sessionDisplayName(metas), totalSize)
    TransferStore.add(record)
    const session = new Session(sessionId, info.alias, remoteIp, metas, tokens, record)
    this.sessions.set(sessionId, session)

    const decision = new Promise<boolean>((resolve) => {
      session.decisionResolve = resolve
      IncomingState.show(new PendingRequest(sessionId, info.alias, metas,
        () => { this.decide(session, true) },
        () => { this.decide(session, false) }))
    })
    const timeout = new Promise<boolean>((resolve) => {
      setTimeout(() => resolve(false), PREPARE_TIMEOUT_MS)
    })
    const accepted = await Promise.race([decision, timeout])
    IncomingState.clear(sessionId)

    if (session.cancelled) {
      sendError(res, 403, 'cancelled')
      return
    }
    if (!accepted) {
      session.state = 'rejected'
      session.record.status = TransferStatus.REJECTED
      TransferStore.notify()
      this.sessions.delete(sessionId)
      sendError(res, 403, 'rejected')
      return
    }
    session.state = 'accepted'
    const filesResp: Record<string, string> = {}
    session.tokens.forEach((token, id) => {
      filesResp[id] = token
    })
    sendJson(res, 200, { 'sessionId': sessionId, 'files': filesResp })
  }

  private decide(session: Session, accepted: boolean): void {
    if (session.state !== 'pending') {
      return
    }
    session.decisionResolve(accepted)
  }

  private hasPending(): boolean {
    let found = false
    this.sessions.forEach((s) => {
      if (s.state === 'pending') {
        found = true
      }
    })
    return found
  }

  // ---------- POST /upload ----------

  async handleUpload(req: Request, res: ServerResponse): Promise<void> {
    LogUtil.info(`handleUpload enter, bodySize=${req.getBodySize()}`)
    const sessionId = queryParam(req, 'sessionId')
    const fileId = queryParam(req, 'fileId')
    const token = queryParam(req, 'token')
    if (sessionId.length === 0 || fileId.length === 0 || token.length === 0) {
      sendError(res, 400, 'missing sessionId/fileId/token')
      return
    }
    this.purgeStaleSessions()
    const session = this.sessions.get(sessionId)
    if (session === undefined || session.state === 'rejected' || session.state === 'cancelled') {
      sendError(res, 403, 'invalid session')
      return
    }
    if (session.state !== 'accepted' && session.state !== 'transferring') {
      sendError(res, 409, 'session conflict')
      return
    }
    const meta = session.files.find((f) => f.id === fileId)
    if (meta === undefined) {
      sendError(res, 400, 'unknown fileId')
      return
    }
    if (session.tokens.get(fileId) !== token) {
      sendError(res, 403, 'invalid token')
      return
    }
    // session.remoteIp 为空 = prepare 时没查到对端 IP（fport/时序问题），跳过校验；token 仍是主要凭证
    if (session.remoteIp.length > 0 && (req.getRemoteIpAddress() ?? '') !== session.remoteIp) {
      sendError(res, 403, 'ip mismatch')
      return
    }
    const record = session.record

    const buf = bodyBuffer(req)
    if (buf === null || buf.byteLength !== meta.size) {
      sendError(res, 400, 'bad or mismatched content-length')
      return
    }

    // 文件夹传输：path 分段消毒后还原目录树（目录冲突=合并）；无有效段退回扁平逻辑
    const relParts = safeRelParts(meta.path ?? '')
    const dirParts = relParts.length > 1 ? relParts.slice(0, relParts.length - 1) : []
    const fileName = relParts.length > 0 ? relParts[relParts.length - 1] : sanitizeName(meta.fileName)
    // 防目录穿越：只取文件名部分；重名加 " (2)" 后缀
    const target = this.createUniqueTarget(fileName, dirParts)
    session.state = 'transferring'
    session.createdAt = Date.now()
    session.currentPath = target
    record.status = TransferStatus.TRANSFERRING
    TransferStore.notify()

    let ok = false
    try {
      ok = this.writeFile(target, buf, record, session)
    } catch (e) {
      LogUtil.error(`write failed: ${JSON.stringify(e)}`)
      ok = false
    }

    if (session.cancelled || !ok) {
      deleteQuietly(target)
      session.currentPath = ''
      if (!session.cancelled) {
        record.status = TransferStatus.FAILED
        record.error = '传输中断'
        TransferStore.notify()
      }
      sendError(res, 500, 'transfer failed')
      return
    }

    if (meta.sha256.length > 0 && sha256Hex(buf) !== meta.sha256) {
      deleteQuietly(target)
      session.currentPath = ''
      record.status = TransferStatus.FAILED
      record.error = 'sha256 校验失败'
      TransferStore.notify()
      sendError(res, 422, 'sha256 mismatch')
      return
    }

    session.currentPath = ''
    session.saved.add(fileId)
    session.bytesDone += meta.size
    record.progress = session.bytesDone
    if (record.savedPath.length === 0) {
      record.savedPath = target
    }
    // 聚合导出清单：相对路径从落盘目标反推（含 " (2)" 重命名后缀）
    const rel = target.startsWith(`${this.saveDir}/`) ? target.substring(this.saveDir.length + 1) : fileName
    record.savedPaths.push(target)
    record.savedRels.push(rel)
    if (session.saved.size === session.files.length) {
      record.status = TransferStatus.DONE
      session.state = 'done'
      this.sessions.delete(sessionId)
    }
    TransferStore.notify()
    sendJson(res, 200, { 'message': 'ok' })
  }

  /** 流式写盘 + 进度回报；返回是否完整写完 */
  private writeFile(target: string, buf: ArrayBuffer, record: TransferRecord, session: Session): boolean {
    const file = fs.openSync(target, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC)
    try {
      let offset = 0
      while (offset < buf.byteLength) {
        if (session.cancelled) {
          return false
        }
        const n = Math.min(WRITE_CHUNK, buf.byteLength - offset)
        // WriteOptions.offset 是文件位置（buffer 永远从头写），按块切片后顺序写
        fs.writeSync(file.fd, buf.slice(offset, offset + n))
        offset += n
        record.progress = session.bytesDone + offset
        record.sampleSpeed()
        TransferStore.notify()
      }
      return true
    } finally {
      fs.closeSync(file)
    }
  }

  // ---------- POST /cancel ----------

  handleCancel(req: Request, res: ServerResponse): void {
    const sessionId = queryParam(req, 'sessionId')
    if (sessionId.length === 0) {
      sendError(res, 400, 'missing sessionId')
      return
    }
    const session = this.sessions.get(sessionId)
    this.sessions.delete(sessionId)
    if (session !== undefined) {
      session.cancelled = true
      session.state = 'cancelled'
      // 正在写入的半成品删掉；已完整落盘的文件保留
      if (session.currentPath.length > 0) {
        deleteQuietly(session.currentPath)
        session.currentPath = ''
      }
      if (session.record.status !== TransferStatus.DONE) {
        session.record.status = TransferStatus.CANCELED
      }
      TransferStore.notify()
      IncomingState.clear(sessionId)
      session.decisionResolve(false)  // 若还在等确认，唤醒 prepare 应答
    }
    sendJson(res, 200, { 'message': 'cancelled' })
  }

  // ---------- 内部工具 ----------

  private purgeStaleSessions(): void {
    const now = Date.now()
    const stale: Session[] = []
    this.sessions.forEach((s) => {
      if (s.state === 'pending' && now - s.createdAt > STALE_PENDING_MS) {
        stale.push(s)
      }
    })
    stale.forEach((s) => {
      this.sessions.delete(s.sessionId)
      IncomingState.clear(s.sessionId)
    })
  }

  private createUniqueTarget(fileName: string, dirParts: string[] = []): string {
    const dir = dirParts.length > 0 ? `${this.saveDir}/${dirParts.join('/')}` : this.saveDir
    if (!fs.accessSync(dir)) {
      fs.mkdirSync(dir, true)   // 递归建目录；已存在则合并（对齐 PC 端 makedirs(exist_ok) 语义）
    }
    let candidate = fileName
    let index = 2
    while (fs.accessSync(`${dir}/${candidate}`)) {
      const dot = fileName.lastIndexOf('.')
      candidate = dot > 0
        ? `${fileName.substring(0, dot)} (${index})${fileName.substring(dot)}`
        : `${fileName} (${index})`
      index++
    }
    return `${dir}/${candidate}`
  }
}

// ---------- 模块级辅助 ----------

/** 是否有已接受/传输中的接收会话（UIAbility 退后台判断用） */
export function hasActiveReceiving(): boolean {
  return currentReceiver?.hasActive() ?? false
}

let currentReceiver: Receiver | null = null

export function registerReceiver(receiver: Receiver): void {
  currentReceiver = receiver
}

export function unregisterReceiver(): void {
  currentReceiver = null
}

function queryParam(req: Request, key: string): string {
  const search = req.search ?? ''
  if (search.length === 0) {
    return ''
  }
  return new url.URLParams(search).get(key) ?? ''
}

function bodyText(req: Request): string {
  const pd = req.files.get('postData')
  return pd !== undefined ? pd.toString() : ''
}

function bodyBuffer(req: Request): ArrayBuffer | null {
  const pd = req.files.get('postData')
  if (pd === undefined || pd.buffer === undefined) {
    return null
  }
  return pd.buffer
}

function sendJson(res: ServerResponse, code: number, obj: Record<string, Object>): void {
  res.writeHead(code, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify(obj))
}

function sendError(res: ServerResponse, code: number, message: string): void {
  const body: Record<string, Object> = { 'message': message }
  sendJson(res, code, body)
}

/** 会话记录显示名：整会话一个文件夹时显示顶层文件夹名；单文件显示文件名；多文件显示「x 等 N 个文件」 */
function sessionDisplayName(files: FileMeta[]): string {
  const first = files[0]
  const top = first.path !== undefined ? first.path.split('/')[0] : ''
  if (top.length > 0 && files.every((f) => f.path !== undefined && f.path.split('/')[0] === top)) {
    return top
  }
  if (files.length === 1) {
    return first.path !== undefined && first.path.length > 0 ? first.path : first.fileName
  }
  return `${first.fileName} 等 ${files.length} 个文件`
}

/** 把发送方声明的 path 相对路径清洗成安全分段（与 PC 端 _safe_rel_parts 同语义） */
function safeRelParts(path: string): string[] {
  const parts: string[] = []
  if (path.length === 0) {
    return parts
  }
  path.split('/').forEach((seg: string) => {
    if (seg === '' || seg === '.' || seg === '..') {
      return
    }
    let cleaned = ''
    for (let i = 0; i < seg.length; i++) {
      const ch = seg.charAt(i)
      cleaned += ('<>:"\\|?*'.indexOf(ch) >= 0 || seg.charCodeAt(i) < 32) ? '_' : ch
    }
    cleaned = cleaned.replace(/[ .]+$/, '')
    parts.push(cleaned.length > 0 ? cleaned : '_')
  })
  return parts
}

/** 文件名消毒：剥掉路径分隔，防目录穿越 */
function sanitizeName(name: string): string {
  let out = name
  const slash = out.lastIndexOf('/')
  if (slash >= 0) {
    out = out.substring(slash + 1)
  }
  const backslash = out.lastIndexOf('\\')
  if (backslash >= 0) {
    out = out.substring(backslash + 1)
  }
  return out.length > 0 ? out : 'file'
}

function deleteQuietly(path: string): void {
  try {
    fs.unlink(path)
  } catch (e) {
  }
}

function sha256Hex(buf: ArrayBuffer): string {
  const md = cryptoFramework.createMd('SHA256')
  md.updateSync({ data: new Uint8Array(buf) })
  const digest = md.digestSync().data
  let hex = ''
  digest.forEach((b) => {
    hex += b.toString(16).padStart(2, '0')
  })
  return hex
}