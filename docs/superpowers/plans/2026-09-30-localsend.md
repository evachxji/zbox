# LocalSend 局域网文件传输 实现计划

> **面向 AI 代理的工作者**：必需子技能：使用 subagent-driven-development 逐任务实现此计划。步骤使用复选框（`- [x]`）语法来跟踪进度。

**目标：** 参照 LocalSend Protocol v2，在 Zviber 面板新增「传输」tab，并构建配套 Android 应用，实现同一局域网下 PC ↔ 手机双向文件传输。

**架构：** 实现 LocalSend 公开协议（v2.2，HTTP 模式）的私有实例：UDP 组播发现 + HTTP REST 文件传输。**端口与组播地址均为自定义值**（TCP/UDP 53327、组播 224.0.0.168），与官方 LocalSend（53317 / 224.0.0.167）完全隔离，不互通、不冲突。PC 端纯标准库实现（零新依赖），协议核心与 UI 分离；Android 端 Kotlin + Compose 原生实现，独立 `android/` 目录，不与 PC 代码杂糅。

**技术栈：** PC：Python 3.8 标准库（socket / http.server / urllib / hashlib / json）+ PyQt5；Android：Kotlin + Jetpack Compose + OkHttp + NanoHTTPD，Gradle wrapper 构建。

---

## 关键设计决策（已确认）

| # | 决策点 | 方案 |
|---|--------|------|
| 1 | 协议 | LocalSend Protocol v2 **HTTP 模式**（`"protocol": "http"`），v1 不做 HTTPS |
| 2 | PC 端依赖 | 零新增，只用标准库；`build.py` / 打包流程不变 |
| 3 | Android 技术栈 | Kotlin + Compose 原生（本机 Java 17 + Android SDK android-36） |
| 4 | 端口 / 组播 | **TCP+UDP 53327，组播 224.0.0.168**（在 224.0.0.0/24 内，Android 兼容）；与官方 LocalSend 隔离，官方 App 看不到我们 |
| 5 | 组播失效回退 | 组播 announce 之外，加 /24 子网 `/register` 扫描（协议 3.2 节） |
| 6 | 接收确认 | 每次接收**手动确认**，确认时**让用户选择保存路径**（PC 默认 `Downloads\Zviber\`、记住上次；Android 用 SAF 目录选择器、persistable 权限记住授权） |
| 7 | 反向下载 API / PIN | v1 不做 |
| 8 | Android 目录 | 独立 `android/` Gradle 工程，与 PC 代码完全分离 |

## 假设

- PC 与手机同一 WiFi / 二层网段，无 AP 隔离（有隔离走决策 5 扫描回退）
- 「双向互传」= 两端都实现发送方（HTTP client）与接收方（HTTP server）
- PC 首次启动服务端触发 Windows 防火墙授权弹窗，属一次性正常行为
- Android minSdk 26（Android 8.0+）
- Android v1 仅前台传输

## PC 端文件结构

- **创建 `transfer.py`** — 协议核心，纯标准库、无 Qt 依赖（可独立测试）：
  - 常量：`MULTICAST_GROUP='224.0.0.168'`、`PORT=53327`、API 前缀 `/api/localsend/v2/`
  - `DeviceInfo`：alias / version / deviceModel / deviceType / fingerprint / port / protocol 数据类
  - `Discovery`（线程）：UDP 组播监听 + announce 发送 + `/register` HTTP 响应 + 子网扫描回退；维护 `devices: {fingerprint: (DeviceInfo, ip, last_seen)}`，30 秒未再见剔除
  - `TransferServer`（`http.server.ThreadingHTTPServer` 子类）：`POST register` / `GET info` / `POST prepare-upload` / `POST upload` / `POST cancel`；接收会话状态机（等待确认 → 接受/拒绝 → 传输中 → 完成/取消）；upload 流式写盘（64KB 块）+ sha256 校验；**接受会话前由 UI 层选定保存目录**（server 回调询要路径，拒绝/取消时删除半成品文件）
  - `send_files(ip, port, files, on_progress, on_done)`：prepare-upload 拿 sessionId/tokens → 逐文件 POST upload 二进制流；出错调 cancel
  - 指纹：随机 32 位 hex，存 `config.json` 的 `transfer_fingerprint` 键
- **创建 `transfer_ui.py`** — `TransferWidget(QWidget)`：
  - 上区：设备列表（别名 + 设备类型 + IP，「刷新」按钮触发重新 announce + 扫描）
  - 中区：「选择文件发送」按钮 + 拖拽区（`setAcceptDrops`），选中设备后发送
  - 下区：传输记录列表（方向箭头、文件名、进度条、状态：等待确认/传输中/完成/失败/被拒绝/已取消）
  - 接收请求弹层：「XXX 想发送 N 个文件（总大小）」+ **保存路径选择**（显示当前目录 + 「更改…」按钮，默认记住的上次目录）+ 接受 / 拒绝
  - 后台桥接：`_Bridge(QThread)` 沿用 `_HolidayWorker` 模式——工作线程跑阻塞 IO，`pyqtSignal` 回主线程，**绝不跨线程动 UI**
- **修改 `app.py`**：tab 栏加「传输」（约 2171 行 `['日历', '待办']` → 三项）；`set_tab()` 支持 idx==2；`set_dual()` 双栏仍只放日历+待办，双栏态点「传输」沿用现有退出双栏逻辑；构造 `TransferWidget` 注入 `single_stack`
- **修改 `main.pyw`**：创建 `Discovery` + `TransferServer` 随面板生命周期启停；收到接收请求 / 传输完成时托盘气泡
- **修改 `themes.py`**：传输页 QSS 追加进两套主题
- **修改 `CLAUDE.md` / `AGENTS.md` / `README.md`**：三份同步（仓库约定）
- **创建 `transfer_selftest.py`** — 自动化协议自检（不依赖手机）：
  - 起两个 `TransferServer`（53327 + 53328）+ 直连 register（跳过组播）
  - A→B 传 3 文件（0 字节、10MB 随机、中文文件名），校验落盘 sha256
  - 覆盖：拒绝路径、cancel 路径、错误 token 返回 403
  - 运行：`python transfer_selftest.py`，全过打印 `SELFTEST OK`

## Android 端文件结构（`android/` 独立 Gradle 工程）

```
android/
  settings.gradle.kts / build.gradle.kts   # AGP 8.x，Kotlin 2.x
  gradle/wrapper/                          # gradlew.bat wrapper
  app/
    build.gradle.kts                       # Compose BOM、OkHttp 4.x、NanoHTTPD 2.3.x
    src/main/AndroidManifest.xml
    src/main/java/com/zviber/transfer/
      MainActivity.kt                      # Compose 单 Activity，底部两页：设备 / 记录
      Protocol.kt                          # DeviceInfo 数据类 + JSON（kotlinx.serialization）
      Discovery.kt                         # MulticastSocket（224.0.0.168:53327）+ announce + 扫描；
                                           #   必须持 WifiManager.MulticastLock
      TransferServer.kt                    # NanoHTTPD 53327：register/info/prepare-upload/upload/cancel
      Sender.kt                            # OkHttp：prepare-upload → upload（流式 RequestBody）
      Receiver.kt                          # 会话管理 + SAF 落盘（用户选定目录）
      ui/DevicesScreen.kt / TransfersScreen.kt / ReceiveDialog.kt
```

- **权限**：`INTERNET`、`ACCESS_NETWORK_STATE`、`ACCESS_WIFI_STATE`、`CHANGE_WIFI_MULTICAST_STATE`、`POST_NOTIFICATIONS`（API 33+）；读写走 SAF，**不需要**存储权限
- **接收确认**：对话框显示来源/文件清单/大小 + 「选择保存位置」按钮（`ACTION_OPEN_DOCUMENT_TREE`，首次默认 `Download/Zviber/`，`takePersistableUriPermission` 记住）+ 接受 / 拒绝
- **构建产物**：`android\app\build\outputs\apk\debug\app-debug.apk`

## 任务分解

### 阶段一：PC 协议核心 + 自检（不碰 UI）

- [x] **任务 1：`transfer.py` 数据结构与指纹** — 验证：模块可导入，`DeviceInfo` 输出合法 JSON
- [x] **任务 2：`TransferServer` 五个路由 + 会话状态机** — 验证：自检 register/info/prepare/upload 用例过
- [x] **任务 3：发送方 `send_files()`** — 验证：自检 A→B 三文件 sha256 一致
- [x] **任务 4：`Discovery` 组播 + 扫描回退** — 验证：自检直连 register 用例过
- [x] **任务 5：`transfer_selftest.py` 全绿** — 验证：`SELFTEST OK`，exit 0
  - commit：`feat: 局域网传输协议核心与自检脚本`

### 阶段二：PC 面板 UI

- [x] **任务 6：`transfer_ui.py` TransferWidget** — 验证：假设备+假记录截图人工核对
- [x] **任务 7：`app.py` 第三 tab + `themes.py` QSS** — 验证：`set ZVIBER_SHOT=designs\verify && python main.pyw` 两主题截图（含传输页）；125% 缩放目测
- [x] **任务 8：`main.pyw` 生命周期 + 托盘气泡 + 接收时目录选择** — 验证：`netstat -ano | findstr 53327` 启动后在听、退出释放
  - commit：`feat: 面板新增传输 tab`
- [x] **任务 9：PC 端双实例手动互传验证**（同机 53327/53328 或两台 PC）：单文件/多文件/100MB/中文名/拒绝/取消

### 阶段三：Android 应用

- [x] **任务 10：`android/` Gradle 骨架 + Compose 空壳** — 验证：`gradlew.bat assembleDebug` 出 APK
- [x] **任务 11：Android 协议层**（Discovery + TransferServer + Sender/Receiver）— 验证：真机 ↔ PC 互传 sha256 一致
- [x] **任务 12：Android UI**（设备页 / 记录页 / 接收确认+选目录 / 通知）— 验证：真机全流程手动测试
- [ ] **任务 13：端到端验收矩阵（待真机验证）**

| 场景 | 预期 |
|------|------|
| 手机 → PC 发 3 个照片 | PC 弹确认并可选目录，接受后落盘所选目录，记录显示完成 |
| PC → 手机发 100MB 视频 | 手机弹确认并可选目录，进度实时，完成可见 |
| 传输中发送方取消 | 接收端记录「已取消」，半成品删除 |
| 接收方拒绝 | 发送端记录「被拒绝」 |
| 两端同时互发 | 各自独立完成不串会话 |
| 关 WiFi 重连 | 设备列表 30 秒内恢复 |
| 官方 LocalSend 同机运行 | 53317/53327 互不干扰，互不可见 |

- [x] **任务 14：文档同步 + 截图自检 + commit** — `CLAUDE.md` / `AGENTS.md` / `README.md`

## 风险与坑位

1. **组播收不到** → 子网扫描回退；Android 必须持 `MulticastLock`
2. **Windows 防火墙** 首次监听拦截 → 文档注明，不静默加规则
3. **53327 被占用**（极小概率）→ 启动失败 UI 明示，不静默失败
4. **槽函数异常 = 进程 abort**（CLAUDE.md 已载）→ 传输回调全包 try/except 落 `debug_due.log`
5. **大文件** 全程流式，禁止整文件 `read()`
6. **Win7 兼容**：只用 Python 3.8 可用标准库 API
7. **Android 后台限网** → v1 仅前台传输，README 注明

## 执行方式

子代理驱动（已确认）：每个任务调度新子代理，任务间审查，快速迭代。
