/**
 * 单页主界面：别名卡片 + 设备列表 + 传输记录 + 接收确认弹层（对齐 Android 端单页布局）。
 * 深色单主题；picker 用法参考 LocalSendLite_HarmonyOS_NEXT 的 utils/PickFile.ets
 * （MIT，见 harmony/NOTICE）。
 */
import { picker, fileIo as fs } from '@kit.CoreFileKit'
import { photoAccessHelper } from '@kit.MediaLibraryKit'
import { ToastUtil } from '@pura/harmony-utils'
import {
  DeviceStore,
  FileMeta,
  PeerDevice,
  TransferRecord,
  TransferStatus,
  TransferStore,
  statusLabel,
} from '../protocol/Protocol'
import { addDeviceByIp, refreshDiscovery } from '../utils/Discovery'
import { IncomingState, PendingRequest } from '../utils/Receiver'
import { cancelRecord, sendFiles } from '../utils/Sender'
import { getAlias, setAlias } from '../utils/Settings'

const BG: string = '#FF14161A'
const CARD: string = '#FF1F232A'
const TEXT_MAIN: string = '#FFE6E8EB'
const TEXT_DIM: string = '#FF9AA0A8'
const ACCENT: string = '#FF4C8DFF'
const RED: string = '#FFE5534B'
const GREEN: string = '#FF3FB950'

@Entry
@Component
struct Index {
  @State devices: PeerDevice[] = []
  @State records: TransferRecord[] = []
  @State pending: PendingRequest | null = null
  @State refreshing: boolean = false
  @State aliasEdit: string = ''
  @State pickTarget: PeerDevice | null = null
  @State showManualIp: boolean = false
  @State manualIp: string = ''
  @StorageLink('shareUris') shareUris: string[] = []
  @StorageLink('serverOn') serverOn: boolean = true

  private onExportRecord = (r: TransferRecord): void => {
    this.exportRecord(r)
  }
  private onDevices = (): void => {
    this.devices = DeviceStore.snapshot()
  }
  private onRecords = (): void => {
    this.records = TransferStore.snapshot()
  }
  private onPending = (): void => {
    this.pending = IncomingState.pending
  }

  aboutToAppear(): void {
    this.aliasEdit = getAlias()
    DeviceStore.onChange(this.onDevices)
    TransferStore.onChange(this.onRecords)
    IncomingState.onChange(this.onPending)
    this.onDevices()
    this.onRecords()
    this.onPending()
  }

  aboutToDisappear(): void {
    DeviceStore.offChange(this.onDevices)
    TransferStore.offChange(this.onRecords)
    IncomingState.offChange(this.onPending)
  }

  // ---------- 发送 ----------

  onDeviceTap(device: PeerDevice): void {
    if (this.shareUris.length > 0) {
      // 分享进件优先：直接发，发完清空
      sendFiles(device, this.shareUris.slice())
      AppStorage.setOrCreate('shareUris', [] as string[])
      return
    }
    this.pickTarget = device
  }

  async pickAndSend(fromAlbum: boolean): Promise<void> {
    const device = this.pickTarget
    this.pickTarget = null
    if (device === null) {
      return
    }
    try {
      let uris: string[] = []
      if (fromAlbum) {
        const photoPicker = new photoAccessHelper.PhotoViewPicker()
        const result = await photoPicker.select(new photoAccessHelper.PhotoSelectOptions())
        uris = result.photoUris
      } else {
        const docPicker = new picker.DocumentViewPicker(getContext(this))
        const options = new picker.DocumentSelectOptions()
        options.maxSelectNumber = 9
        const result = await docPicker.select(options)
        uris = result
      }
      if (uris.length > 0) {
        sendFiles(device, uris)
      }
    } catch (e) {
      // 用户取消选择走这里，静默
    }
  }

  // ---------- 记录导出 ----------

  async exportRecord(record: TransferRecord): Promise<void> {
    try {
      const savePicker = new picker.DocumentViewPicker(getContext(this))
      const options = new picker.DocumentSaveOptions()
      options.newFileNames = [record.fileName]
      options.pickerMode = picker.DocumentPickerMode.DOWNLOAD
      const result = await savePicker.save(options)
      if (result.length === 0) {
        return
      }
      copyFile(record.savedPath, result[0])
      ToastUtil.showToast('已导出')
    } catch (e) {
      ToastUtil.showToast('导出失败')
    }
  }

  // ---------- UI ----------

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        Text('Zbox 传输')
          .fontSize(24)
          .fontWeight(FontWeight.Bold)
          .fontColor(TEXT_MAIN)
          .width('100%')
          .margin({ top: 16, bottom: 12 })

        // 别名卡片
        Row() {
          TextInput({ text: this.aliasEdit, placeholder: '本机别名' })
            .fontColor(TEXT_MAIN)
            .backgroundColor(CARD)
            .layoutWeight(1)
            .onChange((value: string) => {
              this.aliasEdit = value
            })
          Button('保存')
            .fontSize(14)
            .margin({ left: 8 })
            .onClick(() => {
              const name = this.aliasEdit.trim()
              if (name.length === 0) {
                ToastUtil.showToast('别名不能为空')
                return
              }
              setAlias(name)
              ToastUtil.showToast('已保存')
            })
        }
        .width('100%')

        if (!this.serverOn) {
          Text('接收服务不可用（端口 53327 被占用），仅可发送')
            .fontSize(12)
            .fontColor(RED)
            .width('100%')
            .margin({ top: 8 })
        }

        if (this.shareUris.length > 0) {
          Text(`待发送 ${this.shareUris.length} 个分享文件，点选设备发送`)
            .fontSize(13)
            .fontColor(ACCENT)
            .width('100%')
            .margin({ top: 8 })
        }

        // 设备区
        Row() {
          Text('设备')
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor(TEXT_MAIN)
            .layoutWeight(1)
          Text('手动添加')
            .fontSize(13)
            .fontColor(ACCENT)
            .margin({ right: 12 })
            .onClick(() => {
              this.manualIp = ''
              this.showManualIp = true
            })
          Button(this.refreshing ? '扫描中…' : '刷新')
            .fontSize(13)
            .enabled(!this.refreshing)
            .onClick(() => {
              this.refreshing = true
              refreshDiscovery(() => {
                this.refreshing = false
              })
            })
        }
        .width('100%')
        .margin({ top: 12, bottom: 4 })

        if (this.devices.length === 0) {
          Text('未发现设备\n确认电脑端已启用传输，且与本机在同一局域网')
            .fontSize(13)
            .fontColor(TEXT_DIM)
            .textAlign(TextAlign.Center)
            .width('100%')
            .padding(16)
        } else {
          List() {
            ForEach(this.devices, (device: PeerDevice) => {
              ListItem() {
                Row() {
                  Row()
                    .width(8)
                    .height(8)
                    .borderRadius(4)
                    .backgroundColor(GREEN)
                    .margin({ right: 10 })
                  Column() {
                    Text(device.info.alias)
                      .fontSize(15)
                      .fontColor(TEXT_MAIN)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                    Text(`${device.info.deviceModel} · ${device.ip}`)
                      .fontSize(12)
                      .fontColor(TEXT_DIM)
                      .margin({ top: 2 })
                  }
                  .alignItems(HorizontalAlign.Start)
                  .layoutWeight(1)
                }
                .width('100%')
                .padding(10)
                .backgroundColor(CARD)
                .borderRadius(10)
              }
              .margin({ bottom: 6 })
              .onClick(() => {
                this.onDeviceTap(device)
              })
            }, (device: PeerDevice) => device.info.fingerprint)
          }
          .width('100%')
          .height(200)
          .scrollBar(BarState.Auto)
        }

        // 记录区（无记录时整块不显示，对齐 Android 端）
        if (this.records.length > 0) {
          Text('传输记录')
            .fontSize(16)
            .fontWeight(FontWeight.Medium)
            .fontColor(TEXT_MAIN)
            .width('100%')
            .margin({ top: 12, bottom: 4 })
          List() {
            ForEach(this.records, (record: TransferRecord) => {
              ListItem() {
                RecordRow({ record: record, onExport: this.onExportRecord })
              }
              .margin({ bottom: 6 })
            }, (record: TransferRecord) => record.id)
          }
          .width('100%')
          .layoutWeight(1)
          .scrollBar(BarState.Auto)
        }
      }
      .width('100%')
      .height('100%')
      .padding({ left: 16, right: 16 })
      .backgroundColor(BG)

      // 手动输 IP 添加设备弹层
      if (this.showManualIp) {
        Column() {
          Column() {
            Text('手动添加设备')
              .fontSize(16)
              .fontColor(TEXT_MAIN)
              .margin({ bottom: 12 })
            TextInput({ text: this.manualIp, placeholder: '对方 IP，如 192.168.1.8（模拟器联调填 10.0.2.2）' })
              .fontColor(TEXT_MAIN)
              .backgroundColor('#FF14161A')
              .onChange((value: string) => {
                this.manualIp = value
              })
            Row() {
              Button('取消')
                .layoutWeight(1)
                .backgroundColor('#FF3A3F47')
                .onClick(() => {
                  this.showManualIp = false
                })
              Button('添加')
                .layoutWeight(1)
                .margin({ left: 12 })
                .onClick(() => {
                  const ip = this.manualIp.trim()
                  if (ip.length === 0) {
                    return
                  }
                  this.showManualIp = false
                  addDeviceByIp(ip).then((ok: boolean) => {
                    ToastUtil.showToast(ok ? '已添加' : '连不上该设备，确认 IP 与对方已启用传输')
                  })
                })
            }
            .width('100%')
            .margin({ top: 16 })
          }
          .width('85%')
          .padding(20)
          .backgroundColor(CARD)
          .borderRadius(16)
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor('#99000000')
      }

      // 来源选择弹层：相册 or 文件（对齐 Android 端点设备后的询问）
      if (this.pickTarget !== null) {
        Column() {
          Column() {
            Text(`发送到 ${this.pickTarget.info.alias}`)
              .fontSize(16)
              .fontColor(TEXT_MAIN)
              .margin({ bottom: 16 })
            Button('从相册选择')
              .width('100%')
              .margin({ bottom: 8 })
              .onClick(() => {
                this.pickAndSend(true)
              })
            Button('从文件选择')
              .width('100%')
              .margin({ bottom: 8 })
              .onClick(() => {
                this.pickAndSend(false)
              })
            Button('取消')
              .width('100%')
              .backgroundColor('#FF3A3F47')
              .onClick(() => {
                this.pickTarget = null
              })
          }
          .width('80%')
          .padding(20)
          .backgroundColor(CARD)
          .borderRadius(16)
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor('#99000000')
      }

      // 接收确认弹层
      if (this.pending !== null) {
        Column() {
          Column() {
            Text(`${this.pending.fromAlias} 想发送 ${this.pending.files.length} 个文件`)
              .fontSize(16)
              .fontColor(TEXT_MAIN)
              .margin({ bottom: 12 })
            List() {
              ForEach(this.pending.files, (meta: FileMeta) => {
                ListItem() {
                  Row() {
                    Text(meta.fileName)
                      .fontSize(14)
                      .fontColor(TEXT_MAIN)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                      .layoutWeight(1)
                    Text(fmtSize(meta.size))
                      .fontSize(12)
                      .fontColor(TEXT_DIM)
                      .margin({ left: 8 })
                  }
                  .width('100%')
                }
                .margin({ bottom: 6 })
              }, (meta: FileMeta) => meta.id)
            }
            .width('100%')
            .constraintSize({ maxHeight: 200 })
            Text(`共 ${fmtSize(this.pending.totalSize())}，接受后保存到应用内，可在记录中导出`)
              .fontSize(12)
              .fontColor(TEXT_DIM)
              .margin({ top: 8, bottom: 16 })
            Row() {
              Button('拒绝')
                .layoutWeight(1)
                .backgroundColor('#FF3A3F47')
                .onClick(() => {
                  this.pending?.onReject()
                })
              Button('接受')
                .layoutWeight(1)
                .margin({ left: 12 })
                .onClick(() => {
                  this.pending?.onAccept()
                })
            }
            .width('100%')
          }
          .width('85%')
          .padding(20)
          .backgroundColor(CARD)
          .borderRadius(16)
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor('#99000000')
      }
    }
    .width('100%')
    .height('100%')
  }
}

// ---------- 格式化 ----------

function fmtSize(bytes: number): string {
  if (bytes < 0) {
    return ''
  }
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function fmtEta(record: TransferRecord): string {
  if (record.speedBps <= 0) {
    return '--'
  }
  const seconds = Math.ceil((record.size - record.progress) / record.speedBps)
  if (seconds < 60) {
    return `${seconds} 秒`
  }
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

/** 沙箱文件复制到系统保存面板返回的 uri（记录「导出」用） */
function copyFile(srcPath: string, dstUri: string): void {
  const src = fs.openSync(srcPath, fs.OpenMode.READ_ONLY)
  const dst = fs.openSync(dstUri, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC)
  try {
    const buf = new ArrayBuffer(64 * 1024)
    let offset = 0
    while (true) {
      const n = fs.readSync(src.fd, buf, { offset: offset, length: buf.byteLength })
      if (n <= 0) {
        break
      }
      fs.writeSync(dst.fd, buf.slice(0, n))
      offset += n
    }
  } finally {
    fs.closeSync(src)
    fs.closeSync(dst)
  }
}

// ---------- 记录行子组件（@ObjectLink 驱动单行重渲染；整表 ForEach 按 key 复用，builder 实测不刷新） ----------

@Component
struct RecordRow {
  @ObjectLink record: TransferRecord
  onExport: (record: TransferRecord) => void = () => {}

  build() {
    Column() {
      Row() {
        Text(this.record.fileName)
          .fontSize(14)
          .fontColor(TEXT_MAIN)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .layoutWeight(1)
        // 发送中（等待确认/传输中）允许取消；接收完成可导出；终态不显示按钮
        if (this.record.outgoing && this.record.isActive()) {
          Button('取消')
            .fontSize(12)
            .height(28)
            .backgroundColor('#FF3A3F47')
            .onClick(() => {
              cancelRecord(this.record.id)
            })
        } else if (!this.record.outgoing && this.record.status === TransferStatus.DONE && this.record.savedPath.length > 0) {
          Button('导出')
            .fontSize(12)
            .height(28)
            .onClick(() => {
              this.onExport(this.record)
            })
        }
      }
      .width('100%')

      Row() {
        Text(`${this.record.outgoing ? '到' : '来自'} ${this.record.peerAlias} · ${statusLabel(this.record.status)}`)
          .fontSize(12)
          .fontColor(this.record.status === TransferStatus.FAILED ? RED : TEXT_DIM)
          .layoutWeight(1)
        Text(fmtSize(this.record.size))
          .fontSize(12)
          .fontColor(TEXT_DIM)
      }
      .width('100%')
      .margin({ top: 2 })

      if (this.record.status === TransferStatus.TRANSFERRING && this.record.size > 0) {
        Progress({ value: this.record.progress, total: this.record.size, type: ProgressType.Linear })
          .width('100%')
          .color(ACCENT)
          .margin({ top: 6 })
        Text(`${fmtSize(this.record.speedBps)}/s · 剩余 ${fmtEta(this.record)}`)
          .fontSize(11)
          .fontColor(TEXT_DIM)
          .width('100%')
          .margin({ top: 2 })
      }

      if (this.record.error.length > 0) {
        Text(this.record.error)
          .fontSize(12)
          .fontColor(RED)
          .width('100%')
          .margin({ top: 2 })
      }
    }
    .width('100%')
    .padding(10)
    .backgroundColor(CARD)
    .borderRadius(10)
    .alignItems(HorizontalAlign.Start)
  }
}