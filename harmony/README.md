# Zbox 传输 · 鸿蒙端（HarmonyOS NEXT）

PC 端 zbox 面板「传输」的鸿蒙配套 App：局域网内与 PC 互传文件。
协议是 LocalSend v2 的**私有实例**（组播 `224.0.0.168`、端口 `53327`，
与官方 LocalSend 不互通），协议语义以仓库根目录 `transfer.py` 与
`transfer_selftest.py` 为准。移植计划与参考项目分析见
`docs/superpowers/plans/2026-10-06-harmonyos-port.md`。

## 构建

1. 安装 **DevEco Studio 5.x**（HarmonyOS NEXT SDK，API 12+），注册华为开发者账号并实名认证。
2. 用 DevEco Studio 打开本目录（`harmony/`）。
3. 安装三方依赖：DevEco 打开后按提示同步，或命令行在本目录执行 `ohpm install`
   （依赖：`@ohos/polka` / `@ohos/axios` / `@pura/harmony-utils` / `@pura/harmony-dialog`）。
4. 签名：File → Project Structure → Signing Configs，勾选「Automatically generate signature」
   （登录开发者账号后自动生成调试签名）。
5. 构建：Build → Build Hap(s)/APP(s) → Build Hap(s)，产物在
   `entry/build/default/outputs/default/`；命令行等价：`hvigorw assembleHap`。
6. 安装到调试真机：DevEco 直接 Run，或 `hdc install <hap路径>`。

## 没有真机时的联调（模拟器）

- 预览器（Previewer）没有真实网络栈，**发现与传输都测不了**，只能看 UI。
- 模拟器网络是虚拟 NAT（`10.0.2.x` 网段），不在真实局域网内，组播发现用不了的，
  但宿主机固定是 `10.0.2.2`：
  - **鸿蒙 → PC 发送**：PC 面板启用传输，模拟器里点「手动添加」输 `10.0.2.2`，
    出现设备后正常发送即可全链路验证。
  - **PC → 鸿蒙发送（服务端点验证）**：`hdc fport tcp:53327 tcp:53327` 转发后，
    PC 上 `curl http://127.0.0.1:53327/api/localsend/v2/info` 应返回本机 JSON；
    PC 面板手动添加 `127.0.0.1` 亦可向模拟器发文件。
- 组播发现、真实 Wi-Fi 互传的最终验收仍需真机（连同一 Wi-Fi）。

## 验证状态（2026-10-08，deveco-cli + Mate 90 Pro 模拟器实测）

已验证（全链路自动化跑通）：

- 构建/装包/启动/日志/UI 自动化闭环：`devecocli build` → `run` → `log` → `ui screenshot/layout/click/text`
- 子网扫描发现（模拟器扫描 10.0.2.x 网段发现 PC）、手动输 IP 添加设备
- PC → 鸿蒙：接收弹窗 → 接受 → 落沙箱，1.8KB 与 2MB 均 sha256 逐字节一致；重名自动加 ` (2)` 后缀
- 鸿蒙 → PC：文件选择器选文件 → TCPSocket 流式上传 → PC 接收，128KB sha256 逐字节一致
- 传输记录状态实时刷新（等待确认 → 传输中 → 完成）、「导出」按钮

待真机验证：组播发现（模拟器 addMembership EINVAL）、后台长时任务保活、Share Kit 分享入口、
拒绝/取消/会话冲突等异常路径（协议语义与 PC selftest 13 用例对齐，代码已按语义实现）。

## 验收（对照移植计划第八节）

- 模拟器（DevEco 自带，免费）可验证：UI、别名设置持久化、打包签名流程；
  模拟器网络是虚拟 NAT，**组播发现与真实互传必须真机**（与 PC 连同一 Wi-Fi）。
- 与 PC 端互传双向验收：PC 面板传输页启用传输 → 互发现 → PC→鸿蒙、鸿蒙→PC 发文件，
  接受后 sha256 一致；拒绝 / 取消 / 对方正忙（409）等异常路径对照 `transfer_selftest.py`
  的 13 用例逐条过。
- PC 端回归：仓库根目录 `python transfer_selftest.py` 输出 `SELFTEST OK`。

## 已知限制（v1）

- 接收文件落应用沙箱（`files/received/`），在记录页点「导出」经系统保存面板放到公共目录。
- 接收侧 HTTP 服务端（polka）会把上传请求体整块缓冲进内存，超大文件（数百 MB 以上）
  接收有内存压力；发送侧已是流式（TCPSocket 手写，64KB 分块），无此限制。
- 组播收不到时自动退化为子网扫描（刷新按钮：清空→宣告→3 秒宽限→/24 扫描）。
- 传输中切后台会申请长时任务保活；申请失败会提示「请保持前台」。
- hap 只能装进开发者账号签名的调试设备；分发给他人需上架 AppGallery（第二阶段）。

## 第三方致谢

API 用法参考了 LocalSendLite_HarmonyOS_NEXT（MIT），署名见 `NOTICE`。
版本号跟随仓库根目录 `version.py` 的 `APP_VERSION`，发版时同步 `AppScope/app.json5`
的 `versionName` / `versionCode`。