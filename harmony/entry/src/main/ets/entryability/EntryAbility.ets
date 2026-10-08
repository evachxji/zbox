/**
 * 入口 Ability：初始化设置/日志、服务生命周期（前台起服务+发现、退后台无活动时停）、
 * 系统分享入口（Share Kit）、传输中切后台的长时任务保活。
 * 分享入口与工具初始化模式参考 LocalSendLite_HarmonyOS_NEXT（MIT，见 harmony/NOTICE）。
 */
import { AbilityConstant, UIAbility, Want, wantAgent } from '@kit.AbilityKit'
import { window } from '@kit.ArkUI'
import { systemShare } from '@kit.ShareKit'
import { backgroundTaskManager } from '@kit.BackgroundTasksKit'
import { BusinessError } from '@kit.BasicServicesKit'
import { AppUtil, LogUtil, ToastUtil } from '@pura/harmony-utils'
import { initSettings } from '../utils/Settings'
import { TransferServer } from '../utils/Server'
import { Receiver, hasActiveReceiving, registerReceiver, unregisterReceiver } from '../utils/Receiver'
import { hasActiveSending } from '../utils/Sender'
import { refreshDiscovery, startDiscovery, stopDiscovery } from '../utils/Discovery'

export default class EntryAbility extends UIAbility {
  private server: TransferServer | null = null
  private bgRunning: boolean = false

  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    AppUtil.init(this.context)
    LogUtil.init(0x1010, 'ZboxTransfer', true)
    initSettings(this.context)
    this.handleShareWant(want)
  }

  onNewWant(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    this.handleShareWant(want)
  }

  /** 系统分享进件：want 里的文件 uri 放进 shareUris，交给主界面选设备（对齐 Android ShareInbox） */
  private handleShareWant(want: Want): void {
    if (want.action !== 'ohos.want.action.sendData') {
      return
    }
    systemShare.getSharedData(want)
      .then((data: systemShare.SharedData) => {
        const uris: string[] = []
        data.getRecords().forEach((record: systemShare.SharedRecord) => {
          if (record.uri && record.uri.length > 0) {
            uris.push(record.uri)
          }
        })
        if (uris.length > 0) {
          AppStorage.setOrCreate('shareUris', uris)
        }
      })
      .catch((err: BusinessError) => {
        LogUtil.error(`getSharedData failed: ${err.code} ${err.message}`)
      })
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        LogUtil.error(`loadContent failed: ${JSON.stringify(err)}`)
      }
    })
  }

  /** 仅前台传输：回到前台才起 HTTP 服务与组播发现（对齐 Android onStart） */
  onForeground(): void {
    this.stopBackgroundTask()
    if (this.server !== null) {
      return
    }
    const receiver = new Receiver(this.context.filesDir)
    registerReceiver(receiver)
    const server = new TransferServer(receiver)
    try {
      server.start()
      this.server = server
    } catch (e) {
      // 端口被占用时降级：仅发送方功能可用，门禁层提示「不可用」
      LogUtil.error(`server start failed: ${JSON.stringify(e)}`)
      AppStorage.setOrCreate('serverOn', false)
    }
    startDiscovery()
    refreshDiscovery()  // 进入前台自动刷新一次设备列表
  }

  onBackground(): void {
    // 有传输在进行时保持服务与发现（对齐 Android onStop 语义），并申请长时任务防断流
    if (hasActiveReceiving() || hasActiveSending()) {
      this.startBackgroundTask()
      return
    }
    this.stopServices()
  }

  onDestroy(): void {
    this.stopServices()
  }

  private stopServices(): void {
    stopDiscovery()
    try {
      this.server?.stop()
    } catch (e) {
    }
    this.server = null
    unregisterReceiver()
    AppStorage.setOrCreate('serverOn', false)
    this.stopBackgroundTask()
  }

  private async startBackgroundTask(): Promise<void> {
    if (this.bgRunning) {
      return
    }
    try {
      const agent = await wantAgent.getWantAgent({
        wants: [{
          bundleName: this.context.abilityInfo.bundleName,
          abilityName: this.context.abilityInfo.name,
        }],
        actionType: wantAgent.OperationType.START_ABILITY,
        requestCode: 0,
        actionFlags: [wantAgent.WantAgentFlags.UPDATE_PRESENT_FLAG],
      })
      await backgroundTaskManager.startBackgroundRunning(this.context,
        backgroundTaskManager.BackgroundMode.DATA_TRANSFER, agent)
      this.bgRunning = true
    } catch (e) {
      // 申请失败退化：传输中保持前台即可，不阻塞主流程
      ToastUtil.showToast('后台保活失败，传输中请保持前台')
    }
  }

  private async stopBackgroundTask(): Promise<void> {
    if (!this.bgRunning) {
      return
    }
    try {
      await backgroundTaskManager.stopBackgroundRunning(this.context)
    } catch (e) {
    }
    this.bgRunning = false
  }
}