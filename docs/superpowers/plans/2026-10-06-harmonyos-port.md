# 鸿蒙（HarmonyOS NEXT）移植计划 —— Zbox 传输 Android 端

日期：2026-10-06（同日更新：纳入 LocalSendLite_HarmonyOS_NEXT 参考分析）
状态：待实施
目标读者：实施者（人或 agent），要求按本文件即可动手，无需再做技术决策

## 一、背景与结论

HarmonyOS NEXT（5.0+，纯血鸿蒙）移除了 AOSP 兼容层，APK 无法安装。
现有 `android/` 工程（Kotlin + Compose，9 个源文件约 60KB）无法在鸿蒙上运行，
**必须用 ArkTS + ArkUI 在 DevEco Studio 中重写**。

关键利好：已有开源的鸿蒙 LocalSend 实现 **LocalSendLite_HarmonyOS_NEXT**
（Gokr-ble，MIT 协议，允许直接借鉴代码，需保留 LICENSE 署名）——它跑通了
鸿蒙端的 HTTP 服务端、UDP 广播、子网扫描、分享入口全链路，证明技术路线可行。
本计划的 API 选型以其为实证基础，但其功能比 zbox 传输简陋（无进度/取消/会话冲突），
**借鉴其 API 用法，不照抄其行为**（差异见第四节）。

工作量估计：有参考实现后明显降低——熟悉 ArkTS 者约 2~3 天；从零学 DevEco/ArkTS
约 1.5~2 周业余时间。

## 二、目标与成功标准

**目标**：产出鸿蒙版「Zbox 传输」，与 PC 端面板（`transfer.py` 协议实现）双向互传文件。

**成功标准**（全部可验证）：

1. PC 端传输页能发现鸿蒙设备（组播 announce → register 应答链路通）
2. PC → 鸿蒙发文件：鸿蒙弹接收确认，接受后文件逐字节一致（sha256 比对）
3. 鸿蒙 → PC 发文件：PC 弹接收确认，接受后文件逐字节一致
4. 拒绝 / 取消 / 会话冲突 / 对端离线等异常路径的状态与 PC 端语义一致（对照
   `transfer_selftest.py` 13 用例逐条过）
5. PC 端回归：`python transfer_selftest.py` 仍输出 `SELFTEST OK`（移植不动 PC 代码）

## 三、现状盘点（被移植对象）

`android/app/src/main/java/com/zbox/transfer/` 下的行为清单（实施时逐项对照）：

| 文件 | 职责 | 关键行为 |
| --- | --- | --- |
| `Protocol.kt` | 协议常量与数据类 | 端口 53327、组播 224.0.0.168、前缀 `/api/localsend/v2`；DeviceInfo/FileMeta/PrepareRequest/PrepareResponse；JSON 容忍未知字段、null 省略 |
| `Discovery.kt` | UDP 组播发现 | 启动时 announce 一次；监听组播并回 POST /register；手动刷新=清空列表+重新 announce，3 秒组播宽限内无设备回退 /24 子网扫描（并发上限 64、500ms 超时）；不做 TTL 剔除 |
| `TransferServer.kt` | 接收方 HTTP 服务端 | NanoHTTPD 监听 53327，路由 register / info / prepare-upload / upload / cancel 五端点；422 自定义状态；错误体 `{"message": ...}` |
| `Receiver.kt` | 接收会话状态机 | PENDING/ACTIVE 两态；并发 prepare 冲突回 409；10 分钟未确认清过期会话；错误码 400/403/409/422/500；文件名消毒防目录穿越；重名加 ` (2)` 后缀；默认存系统 Download/Zbox |
| `Sender.kt` | 发送方 | prepare-upload（读超时 5 分钟等对方确认；403=拒绝）→ 逐文件 POST upload 流式上传（64KB 分块报进度）→ 任一失败中止整批并 POST cancel；cancel 幂等 |
| `MainActivity.kt` | 生命周期与设置 | 前台起服务+发现、退后台无活动时停；有传输时持 WifiLock 保持；指纹=首启 16 字节随机 hex；别名默认 `Android-<型号>`；分享入口（SEND/SEND_MULTIPLE）进 ShareInbox |
| `ui/DevicesScreen.kt` | 主界面 | 单页：别名卡片 + 设备列表（限高约 2.5 行内滚）+ 传输记录区；点设备先问来源（相册/文件）；刷新旋转动效 |
| `ui/ReceiveDialog.kt` | 接收确认弹窗 | 显示对方别名、文件清单与总大小；接受/拒绝 |
| `ui/TransfersScreen.kt` | 传输记录 | 进度条平滑动画、速度 EMA 平滑与剩余时间、发送中可取消、点击记录跳文件所在目录 |

**协议常量注意**：zbox 是 LocalSend v2 的**私有实例**——组播 `224.0.0.168`、
端口 `53327`，与官方 LocalSend（`224.0.0.167` / `53317`）和参考项目都不同。
参考项目里的常量**一个都不能抄**，只抄 API 用法。

## 四、参考项目分析：LocalSendLite_HarmonyOS_NEXT（MIT）

仓库已下载研读（zip 经 ghproxy 拉取）。逐文件结论：

### 可以直接借鉴的

| 参考项目文件 | 证明了什么 | zbox 对应模块 |
| --- | --- | --- |
| `utils/Server.ets` | **`@ohos/polka`（ohpm 三方库）可在鸿蒙跑 HTTP 服务端**，Express 风格路由，5 个端点它全实现了 | 替代手写 `TCPSocketServer` 方案，`HttpServer.ets` 基于 polka |
| `utils/ScanLocalNetwork.ets` | 子网扫描=`taskpool.TaskGroup` + `@Concurrent` 函数 + `@ohos/axios` 短超时 POST /register | `Discovery.ets` 的扫描分支 |
| `utils/SendFile.ets` | 发送链路：axios GET /info 探活 → POST prepare-upload → POST upload | `Sender.ets` 骨架 |
| `utils/PickFile.ets` | `picker.DocumentViewPicker`（文件）/ `photoAccessHelper.PhotoViewPicker`（相册）选文件 | 发送选文件 |
| `entryability/EntryAbility.ets` + `module.json5` | 分享入口完整模式：skills 声明 `ohos.want.action.sendData` + utd 列表，UIAbility `onNewWant` 里 `systemShare.getSharedData(want)` 取 uri 列表 | 分享进 ShareInbox |
| `utils/ReadConfig.ets` | `preferences.getPreferencesSync` 设置持久化 | `Settings.ets` |
| `model/DeviceInfo.ets` | 协议 DeviceInfo 的 ArkTS 表达 | `protocol/` 类型 |

依赖清单（全在 ohpm 官方三方库中心仓，DevEco 内 `ohpm install` 即可）：
`@ohos/polka`、`@ohos/axios`、`@pura/harmony-utils`、`@pura/harmony-dialog`。

### 不能照抄的（参考项目的缺陷，zbox 要做得更好）

1. **组播只发不收**：`UDPBroadcast.ets` 只 bind 临时端口向官方组播组发包，
   **没有 `addMembership` 加入组播组**，收不到别人的 announce——它的"发现"实际全靠
   子网扫描。zbox 要尝试 `socket.UDPSocket.addMembership`（API 12+）实现真组播监听，
   收不到再退化扫描。**spike 步骤保留**。
2. **大文件内存炸弹**：接收侧 polka 把整个请求体缓冲成 ArrayBuffer
   （`req.files.get('postData')`），发送侧 `new ArrayBuffer(stat.size)` 整文件读进内存
   ——超过几百 MB 的文件必崩。zbox 必须改流式（见第五节决策）。
3. **register 应答错误**：它回 `'{}'`，而 LocalSend v2 /register 应回**本机 DeviceInfo**
   （zbox 的 PC/Android 端都从应答体登记对方）——必须修正，否则互发现少一条链路。
4. **无会话管理**：全局单个 `sessionId`，无 409 冲突、无过期清理、无取消清理半成品。
   zbox 按 `Receiver.kt` 状态机完整移植。
5. **无进度/无取消**：发送无进度回报、无 cancel 端点调用。zbox 保留 64KB 分块进度与
   双向取消。
6. **接收 UX 别扭**：upload 处理中才弹 `DocumentSavePicker` 逐文件问保存位置。
   zbox 用「接受即落沙箱 + 记录页事后导出」。
7. **指纹来源**：它用设备 ID 的 SHA256；zbox 沿用自己的约定（首启 16 字节随机 hex
   持久化），与 Android 端行为一致。

## 五、技术选型（已决策，不再讨论）

- IDE/语言：**DevEco Studio + ArkTS（Stage 模型，单 UIAbility）**，compileSdk 用当前
  稳定的 HarmonyOS 5.x（API 12+）。
- 包名：`com.zbox.transfer`，应用名「Zbox 传输」。
- 依赖（ohpm 三方库，均经参考项目实证可用）：`@ohos/polka`（HTTP 服务端）、
  `@ohos/axios`（JSON 端点客户端）、`@pura/harmony-utils`、`@pura/harmony-dialog`。
- **HTTP 服务端用 polka**（参考项目实证路线），路由 5 端点。**例外**：polka 会把
  /upload 请求体整块缓冲进内存，大文件接收有 OOM 风险——v1 先接受此限制并记录
  （见风险表），v1.1 再评估把 /upload 拆到手写 `TCPSocketServer` 通道。
- **发送上传手写流式**：axios 上传也要整文件 ArrayBuffer，不可接受（进度+大文件+
  取消都是核心 UX）。改用 `socket.TCPSocket` 手写 HTTP POST（Content-Length 已知，
  64KB 分块从文件 fd 读，边发边报进度，可随时中断后补 POST cancel）。
  这是全项目**最大的一块手写代码**，单独里程碑。
- 组播：`socket.UDPSocket` + `addMembership(224.0.0.168)` 监听 + send announce；
  扫描分支照参考项目的 taskpool + axios 模式（并发上限 64、500ms 超时对齐 Android 端）。
- 持久化：`preferences`（指纹/别名），模式照 `ReadConfig.ets`。
- UI：ArkUI 单页（设备 + 记录同屏，对齐 Android 端单页布局），深色单主题。

## 六、行为差异（鸿蒙平台约束导致的，接受为既定事实）

1. **接收文件落沙箱**：鸿蒙不能写公共 Download 目录。接收一律落应用沙箱
   `files/received/`（重名加 ` (2)` 后缀），记录页「保存到…」经
   `picker.DocumentSavePicker` 导出（参考项目 `handleUpload` 里有现成 picker 用法，
   但时机改为事后导出而非传输中弹窗）。
2. **后台传输**：传输中切后台申请长时任务（`ohos.permission.KEEP_BACKGROUND_RUNNING`，
   类型 `DATA_TRANSFER`），活动会话结束时释放；申请失败退化为「传输中请保持前台」提示。
3. **组播锁不存在**：Android 的 MulticastLock/WifiLock 在鸿蒙无对应物，跳过。
4. **分享入口**：照参考项目实证模式——module.json5 skills 声明
   `ohos.want.action.sendData` + utd 列表（`maxFileSupported` 按需放大），
   `onNewWant` 里 `systemShare.getSharedData` 取 uri 进 ShareInbox。
5. **分发方式**（重要认知）：hap 只能装进开发者账号签名的调试设备；给其他华为手机
   用必须上架 AppGallery。v1 只到「自己的调试真机可装可跑」，上架是第二阶段。

## 七、工程结构

新建 `harmony/` 目录（与 `android/` 平级，DevEco 标准工程，布局向参考项目靠拢
以便对照借鉴）：

```
harmony/
  AppScope/                    # app.json5：包名、版本（跟随 version.py 的 APP_VERSION）
  entry/src/main/
    module.json5               # UIAbility、权限（INTERNET/GET_NETWORK_INFO/GET_WIFI_INFO/
                               #   KEEP_BACKGROUND_RUNNING）、分享 skills（照参考项目）
    ets/
      entryability/EntryAbility.ets   # 生命周期 + systemShare 分享入口
      pages/Index.ets          # 单页主界面（设备 + 别名卡 + 记录区 + 接收弹窗）
      protocol/Protocol.ets    # 协议常量与类型（常量逐字节对齐 PC/Android）
      utils/
        Discovery.ets          # 组播 announce/监听 + 子网扫描
        Server.ets             # polka 服务端：5 端点路由
        Receiver.ets           # 接收会话状态机（对齐 Receiver.kt）
        Sender.ets             # 发送流程 + TCPSocket 流式上传
        Settings.ets           # preferences 封装（指纹/别名）
```

版本号唯一来源仍是 `version.py`：打包前手工同步到 `AppScope/app.json5`。
参考项目为 MIT 协议：借鉴的代码片段在文件头注明出处，仓库根目录或 `harmony/`
下保留其 LICENSE 署名（NOTICE 文件）。

## 八、实施步骤（每步带验证，全过才进下一步）

1. **技术 spike：组播收发 + polka 冒烟**（最高风险，最先做）
   建空工程：`UDPSocket.addMembership(224.0.0.168)` 收包 + 发包；polka 起 53327
   端口回 `/api/localsend/v2/info`。
   → 验证：真机（或云真机）上能收到 PC 端 announce 且 PC 能收到它的；
   PC 浏览器/curl 访问 `http://<手机IP>:53327/api/localsend/v2/info` 拿到 JSON。
   **若组播被拦**：降级=启动即子网扫描 + 手输 IP（参考项目就是这条路线，兜底已实证）。
2. **工程骨架 + 协议层**：建 `harmony/` 工程、接 ohpm 依赖、移植 `Protocol.kt`
   常量与类型、`Settings`（preferences、指纹生成）。
   → 验证：模拟器跑起空壳页面；指纹首启生成且重启不变。
3. **发现层**：`Discovery.ets`（announce 一次、监听+register 应答、手动刷新、
   子网扫描 taskpool 并发 64）。register 应答**回本机 DeviceInfo**（修参考项目的缺陷）。
   → 验证：真机与 PC 互发现；刷新行为对齐 Android 端（清空→announce→3 秒宽限→扫描）。
4. **接收链路**：`Server.ets`（polka 5 端点）+ `Receiver.ets` 状态机（409 冲突、
   10 分钟过期、文件名消毒、重名后缀）+ 接收弹窗 + 沙箱落盘。
   → 验证：PC 面板向鸿蒙发文件，确认后落沙箱，sha256 一致；curl 逐端点过错误码
   （400/403/409/422/500 语义对齐 selftest）。
5. **发送链路**：`Sender.ets` + TCPSocket 流式上传（64KB 分块、进度、取消）+
   文件/相册 picker（照 `PickFile.ets`）。
   → 验证：鸿蒙向 PC 发文件（含 >500MB 大文件），PC 确认后一致；进度/速度显示正常；
   取消后 PC 收到 cancel 且半成品被清理。
6. **异常路径全过**：对照 `transfer_selftest.py` 13 用例逐条复现：拒绝、双方取消、
   会话冲突（409）、token 错误（403）、sha256 不符（422）、对端离线、传输中断网。
   → 验证：每条记录现象并与 PC 端语义比对，全部一致。
7. **生命周期与后台**：`onForeground/onBackground` 对齐 Android `onStart/onStop`；
   长时任务申请/释放；Share Kit 分享入口。
   → 验证：退后台无活动后服务停止；传输中切后台不中断；系统分享面板能唤起。
8. **收尾**：记录页「保存到…」导出、点击记录定位文件、图标与应用名、
   NOTICE 署名、README 与 AGENTS.md 同步（新增 `harmony/` 章节与构建命令：
   DevEco 内 Build APP(s)/HAP(s) 或 `hvigorw assembleHap`）。
   → 验证：全新 clone 按 README 能构建出 hap 并装进调试真机。

## 九、测试策略与真机方案

- **模拟器分工**：DevEco 自带手机模拟器（Windows 10/11 64 位 + Hyper-V，需华为
  开发者账号实名认证，免费）负责 UI、设置持久化、polka 端点的 curl 冒烟
  （经 hdc 端口转发可从 PC 访问模拟器内服务）、打包签名流程。
- **模拟器测不了的**：模拟器网络是虚拟 NAT，不在真实局域网内——**组播发现与真实
  互传必须真机**。步骤 1/3/4/5/6 的验收都依赖真机。
- **真机获取**（按优先级）：
  1. 借/淘一台 HarmonyOS NEXT 设备（nova/Pura/Mate 系列，二手几百到一千多）；
  2. 过渡期用 AppGallery Connect 云调试远程真机（免费额度有限，只适合验证 UI 与
     端点行为，不适合验收组播）。
- **PC 端回归**：移植全程不改 PC 代码，每个里程碑跑 `python transfer_selftest.py`
  确认 `SELFTEST OK`。

## 十、风险登记

| 风险 | 概率 | 缓解 |
| --- | --- | --- |
| `addMembership` 组播监听在真机不可用 | 中 | 步骤 1 spike 最先验证；兜底=子网扫描+手输 IP（参考项目实证可行） |
| polka 缓冲整个 upload 体，大文件接收 OOM | 中 | v1 限制并文档化；v1.1 把 /upload 拆到手写 TCPSocketServer 通道 |
| 手写流式上传的 HTTP 细节 bug（分块、中断恢复） | 中 | 协议只有定长 POST 一种形态；>500MB 实测；PC 端 selftest 语义对照 |
| 长时任务申请被拒或行为不符预期 | 低 | 退化提示「传输中请保持前台」，不阻塞主流程 |
| 分发受限（hap 无法随意侧载） | 确定 | v1 仅调试真机；上架为独立第二阶段 |

## 十一、明确不做（v1 范围外）

- 上架 AppGallery（第二阶段，需个人开发者实名认证）
- 浅色主题 / 主题切换（沿用 Android 端深色单主题）
- 接收时选保存目录（由「落沙箱 + 事后导出」替代）
- HTTPS 与加密（协议本身是明文 HTTP，与 PC/Android 端保持一致）
- 文件夹传输、文本/剪贴板传输（参考项目 roadmap 里的这些项同样不做）
- iOS 端
