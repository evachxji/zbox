---
name: zbox-release
description: "发布 zbox 新版本 release 的完整流程：改版本号 → 三端构建 → 打 tag → 建 GitHub release 传 assets → 更新并部署官网。当用户说以下情况时触发：(1) 发布/发版新版 release；(2) 打个新版本 tag 并发布；(3) 构建安装包上传到 release。触发词：发布 release、发版、新版本、打 tag、上传 assets、release。"
---

# zbox-release —— zbox 发版流程说明书

发版 = 询问是否发布鸿蒙端 → 改版本号 → 全量构建 → tag → GitHub release（带安装包 assets）→ 官网同步并上线 →（可选）AppGallery Connect 提交审核。
全程在仓库根目录操作，工具链要求：Python+PySide6+PyInstaller、JDK 17、DevEco Studio（D:\Program Files\Huawei）+ devecocli、gh CLI（已登录 evachxji）。

## 0. 确认版本号（必须先做）

**用户没给新版本号就必须问，不许自己编。** 当前版本在 `version.py` 的 `APP_VERSION`（唯一来源）。
把用户给的版本记为 `<VER>`（如 `0.4.2`），tag 名 `v<VER>`。先确认该 tag 不存在：`git tag -l "v<VER>"` 应为空。

**每次发版都必须询问用户本次是否需要同步发布鸿蒙端到 AppGallery Connect**；用户已经明确说明时直接记录选择，不重复询问。需要时执行第 7 步，不需要时跳过，不要默认发布。

## 1. 改版本号并提交

- 只改 `version.py` 里 `APP_VERSION` 一行。**必须用 python 读写**（UTF-8 无 BOM、文件末尾无换行）——
  PowerShell 的 `Get-Content|Set-Content` 会把中文注释搅成乱码，已踩过：

```powershell
@"
import io
p = 'version.py'
s = io.open(p, encoding='utf-8').read()
assert "APP_VERSION = '<旧版本>'" in s
io.open(p, 'w', encoding='utf-8', newline='').write(s.replace("APP_VERSION = '<旧版本>'", "APP_VERSION = '<VER>'"))
"@ | python -
```

- 同步移动端包内版本，避免只改安装包文件名：
  - `harmony/AppScope/app.json5`：`versionName = <VER>`，`versionCode` 比上一版 +1。
  - `android/app/build.gradle.kts`：`versionName = <VER>`，`versionCode` 比上一版 +1。
- 验证：`git diff version.py` 只有一行变化，移动端 `versionName` 均为 `<VER>` 且 `versionCode` 已递增。提交：`git commit -m "chore: 版本号更新至 v<VER>"`。

## 2. 全量构建（Win exe + Android APK + 鸿蒙 HAP + APP）

```powershell
echo 7 | cmd /c build.cmd > dist\release-build.log 2>&1
```

build.cmd 是交互式的（`set /p` 读选项、结尾 `pause`），管道喂 `7`（全量）即可，stdin 关闭后 pause 自动返回。
耗时约 4-10 分钟（PyInstaller 为主）。**构建后必须查日志，不能只看退出码**：

```powershell
Select-String -Path dist\release-build.log -Pattern '\[错误\]|\[跳过\]|BUILD FAILED'
```

已知坑（全部实测踩过）：

1. **鸿蒙 APP 段假失败**：hvigor daemon 环境陈旧时 assembleApp 报 `Invalid value of 'DEVECO_SDK_HOME'`
   且 BUILD FAILED，**但 errorlevel 仍是 0**，build.cmd 会继续跑并把**旧的 .app 改名拷成新版**。
   判断法：`Get-FileHash` 对比新旧两版 `.app`，hash 相同 = 旧货。修复：

```powershell
$env:DEVECO_SDK_HOME = "D:\Program Files\Huawei\DevEco Studio\sdk"
Push-Location harmony
& "D:\Program Files\Huawei\DevEco Studio\tools\node\node.exe" "D:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.js" --stop-daemon
& "D:\Program Files\Huawei\DevEco Studio\tools\node\node.exe" "D:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.js" assembleApp -p "product=default" -p "buildMode=release" --analyze=normal --parallel --incremental
Pop-Location
Copy-Item harmony\build\outputs\default\harmony-default-signed.app "dist\release\zbox-HarmonyOS-v<VER>.app" -Force
```

2. **assembleApp 会覆写 entry 的 hap 产物**（release 模式），手动补跑过 assembleApp 后必须在
   `harmony\` 下重跑 `devecocli build` 把 debug hap 打回来（build.cmd 内部顺序就是这样设计的）。
3. **UP-TO-DATE 误判恐慌**：gradle/hvigor 增量构建让产物保持旧 mtime，看起来像没构建。
   核对法：相关源码文件的 LastWriteTime 早于产物 mtime = 内容就是当前的，不是旧货（提交时间无关，看文件 mtime）。

验证产物（4 个，都在 `dist\release\`）：
`zbox-Setup-v<VER>-x64.exe`、`zbox-Android-v<VER>.apk`、`zbox-HarmonyOS-v<VER>-unsigned.hap`、`zbox-HarmonyOS-v<VER>.app`。

还要验证包内版本而不是只看文件名：Android 用 SDK `aapt dump badging` 检查 `versionName/versionCode`；鸿蒙用 Python `zipfile` 读取 `.app` 内 `pack.info`，确认 `summary.app.version` 为 `<VER>` 和新的构建号。

## 3. 推送 + 打 tag

```powershell
git push origin main
git tag v<VER> <版本号commit的hash>
git push origin v<VER>
```

tag 打在版本号提交上（website 等后续提交在 tag 之后，没关系）。

## 4. 建 GitHub release 并传 assets

notes 参考上一版内容范围（`gh release view <上一tag>`），但格式必须双语：**中文在前，英文在后**。
两部分都要包含开头定位、「本版变化」和分端「下载」说明，内容保持一致，不写 commit hash；
中文使用自然措辞，不做逐字机翻。两部分之间用一行 `---` 分隔。
写入 `dist\release-notes.md` 后，用 `--notes-file` 传，避免 PowerShell 引号地狱。模板：

```markdown
一句话概括本版更新。

## 本版变化

- 对应的用户可感知变化。

## 下载

- Windows：...
- Android：...
- HarmonyOS：...

---

A concise English summary of this release.

## What's Changed

- User-facing change in English.

## Downloads

- Windows: ...
- Android: ...
- HarmonyOS: ...
```

两个坑：

1. **`.app` 扩展名被 GitHub 拒**（HTTP 422 "file extension that is not allowed"）——先打包再传：
   `Compress-Archive -Path dist\release\zbox-HarmonyOS-v<VER>.app -DestinationPath dist\release\zbox-HarmonyOS-v<VER>.app.zip -Force`
2. **exe 有 108MB，上传慢，gh 命令可能超时被杀**：被杀后 release 留在 **draft** 态、asset 缺 exe。
   补传：`gh release upload v<VER> "dist\release\zbox-Setup-v<VER>-x64.exe" --clobber`
   （可 Start-Process 挂后台慢慢传）。全部传完后发布：`gh release edit v<VER> --draft=false`

```powershell
gh release create v<VER> --title "zbox v<VER>" --notes-file dist\release-notes.md `
  "dist\release\zbox-Setup-v<VER>-x64.exe" "dist\release\zbox-Android-v<VER>.apk" `
  "dist\release\zbox-HarmonyOS-v<VER>-unsigned.hap" "dist\release\zbox-HarmonyOS-v<VER>.app.zip"
```

验证：`gh release view v<VER>` 显示 4 个 assets 且非 draft。

## 5. 上传安装包到 CDN（dl.wzyjc.cn）

官网与应用内更新（`updater.py`）的下载都走 CDN 优先——**不传这步，新版 exe/apk 的 CDN 地址 404，静默回落 GitHub 镜像**。
把 exe 和 apk 传到 COS 桶 `dl/` 前缀并校验完整性（hap/app 不上，鸿蒙走 AppGallery）：

`powershell
@'
import json
from pathlib import Path
from qcloud_cos import CosConfig, CosS3Client
cred = json.loads((Path.home()/'.tccli'/'default.credential').read_text(encoding='utf-8'))
client = CosS3Client(CosConfig(Region='ap-shanghai', SecretId=cred['secretId'], SecretKey=cred['secretKey']))
for name in ['zbox-Setup-v<VER>-x64.exe', 'zbox-Android-v<VER>.apk']:
    src = str(Path('dist/release') / name)
    client.upload_file(Bucket='zbox-wzyjc-cn-1257727321', Key='dl/' + name, LocalFilePath=src,
                       ContentType='application/octet-stream',
                       CacheControl='public, max-age=31536000, immutable',
                       EnableMD5=True, PartSize=8, MAXThread=8)
    print('uploaded', name)
'@ | python -
`

验证：`curl.exe -sI https://dl.wzyjc.cn/dl/zbox-Setup-v<VER>-x64.exe` 返回 200 且 Content-Length 与本地一致
（本机有 Clash 时按 site-deploy 说明书的 DoH + `--resolve` 方法直连边缘节点测）。
CRC64 完整性比对脚本见 `.claude/skills/site-deploy/SKILL.md` 下载 CDN 节。

## 6. 官网同步并上线

- `website/index.html` + `website/js/app.js` 里所有旧版本号全局替换为新版本号
  （下载链接同样含版本号，替换 `0.x.y` 串即一并更新；同样用 python 读写）。替换后 grep 旧版本号应为 0。
- 部署与验证按 `.claude/skills/site-deploy/SKILL.md`：`python website/deploy-cos.py`，
  然后 curl 验证 `https://zbox.wzyjc.cn/` 返回 200 且页面里是新版版本号。
- 提交：`git commit -m "feat(website): 版本号与下载链接更新至 v<VER>"` 并 push。

## 7.（可选）鸿蒙端发布到 AppGallery Connect

仅当第 0 步用户选择发布鸿蒙端时执行；上传的是 release 签名的 `dist\release\zbox-HarmonyOS-v<VER>.app`，不是 unsigned.hap 或 app.zip。

1. 先检查本机是否有支持发布的 CLI（`devecocli --help`）。当前 `@deveco/deveco-cli@1.3.0-stable` 只有构建、运行、签名等命令，**没有 AppGallery 发布命令**；不要臆造 `publish` 子命令。没有可用 CLI 时，用已登录开发者账号的浏览器进入 AppGallery Connect。
2. 进入「应用管理 → Zbox 传输（com.zbox.transfer）→ 分发 → 应用上架 → 版本/升级」，在新版本页点「去选择 → 上传新版本」，上传上述 `.app`。
3. 上传后选中版本名为 `<VER>`、构建号为新 `versionCode` 的包，填写「新版本特性」，保留上一版发布国家或地区等设置，复核后点「提交审核」。
4. 记录页面状态。**提交审核不等于已上架**；只有页面明确显示已上架才能宣称发布完成，审核中/待审核要如实说明。
5. 需要手动操作时，把页面保留给用户并交代具体动作：登录华为开发者账号、完成验证码，或在 Chrome 扩展详情中开启「允许访问文件网址」后重试上传。不要索取账号密码或验证码。

验收（仅发布鸿蒙端时）：开发者中心的新版本页显示 `<VER>` / 新构建号，软件包已选中；最终状态至少为「提交审核/审核中」，并记录实际状态。

## 验收清单

- [ ] `version.py` = 新版本，一行 diff；Android / 鸿蒙包内 `versionName` 同步且 `versionCode` 递增，已提交已推送
- [ ] `dist\release\` 四个 v<VER> 产物齐全，`.app` 与上一版 hash 不同
- [ ] `git ls-remote --tags origin` 有 `v<VER>`，指向版本号提交
- [ ] `gh release view v<VER>`：非 draft，4 个 assets（exe/apk/hap/app.zip），大小与本地一致；
      描述为中文在前、英文在后，两部分变化与下载信息一致
- [ ] COS `dl/` 下有 v<VER> 的 exe 与 apk，`https://dl.wzyjc.cn/dl/...` 200 且大小一致
- [ ] 官网首页与 js 里版本号为 v<VER>，下载链接指向 v<VER> assets
