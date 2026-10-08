/**
 * 接收方 HTTP 服务端：polka 监听 53327，路由 /api/localsend/v2 下五个端点。
 * polka 用法参考 LocalSendLite_HarmonyOS_NEXT 的 utils/Server.ets（MIT，见 harmony/NOTICE）；
 * 与其差异：register 应答回本机 DeviceInfo（协议要求，它错回 '{}'），
 * 会话冲突/取消/错误码语义对齐 PC 端 transfer.py。
 */
import polka, { Request, ServerResponse } from '@ohos/polka'
import { LogUtil } from '@pura/harmony-utils'
import { API_PREFIX, DeviceStore, PROTOCOL_PORT, parseDeviceInfo } from '../protocol/Protocol'
import { fingerprint, localInfo } from './Settings'
import { Receiver } from './Receiver'

export class TransferServer {
  private app = polka()
  private receiver: Receiver

  constructor(receiver: Receiver) {
    this.receiver = receiver
  }

  start(port: number = PROTOCOL_PORT): void {
    this.app
      .use((req: Request, res: ServerResponse, next: Function) => {
        // 无 content-type 时按 json 处理，polka 才能把请求体收进 postData（参考项目原样保留）
        if (!req.headers['content-type']) {
          req.headers['content-type'] = 'application/json'
        }
        LogUtil.info(`~> ${req.method} ${req.url} from ${req.getRemoteIpAddress()}`)
        next()
      })
      .get(`${API_PREFIX}/info`, (req: Request, res: ServerResponse) => {
        this.handleInfo(req, res)
      })
      .post(`${API_PREFIX}/register`, (req: Request, res: ServerResponse) => {
        this.handleRegister(req, res)
      })
      .post(`${API_PREFIX}/prepare-upload`, async (req: Request, res: ServerResponse) => {
        await this.receiver.handlePrepare(req, res)
      })
      .post(`${API_PREFIX}/upload`, async (req: Request, res: ServerResponse) => {
        await this.receiver.handleUpload(req, res)
      })
      .post(`${API_PREFIX}/cancel`, (req: Request, res: ServerResponse) => {
        this.receiver.handleCancel(req, res)
      })
      .listen(port, () => {
        LogUtil.info(`listening on ${port}`)
        AppStorage.setOrCreate('serverOn', true)
      })
    // 端口被占等绑定失败：门禁层提示「不可用」（对齐 PC 端传输页语义）
    this.app.server?.on('error', (err: Object) => {
      LogUtil.error(`server error: ${JSON.stringify(err)}`)
      AppStorage.setOrCreate('serverOn', false)
    })
  }

  stop(): void {
    this.app.server?.stop()
  }

  /** GET /info：回本机 DeviceInfo */
  private handleInfo(req: Request, res: ServerResponse): void {
    this.sendInfo(res)
  }

  /** POST /register：登记对端 + 回本机 info（协议要求，参考项目错回 '{}'，已修正） */
  private handleRegister(req: Request, res: ServerResponse): void {
    try {
      const pd = req.files.get('postData')
      const text = pd !== undefined ? pd.toString() : ''
      const info = parseDeviceInfo(text)
      if (info !== null && info.fingerprint !== fingerprint()) {
        DeviceStore.upsert(info, req.getRemoteIpAddress() ?? '')
      }
      this.sendInfo(res)
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' })
      res.end('{"message":"internal error"}')
    }
  }

  private sendInfo(res: ServerResponse): void {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(localInfo()))
  }
}