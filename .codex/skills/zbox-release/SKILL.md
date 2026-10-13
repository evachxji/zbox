---
name: zbox-release
description: "发布 zbox 新版本 release 的完整流程：改版本号 → 三端构建 → 打 tag → 建 GitHub release 传 assets → 更新并部署官网。当用户说以下情况时触发：(1) 发布/发版新版 release；(2) 打个新版本 tag 并发布；(3) 构建安装包上传到 release。触发词：发布 release、发版、新版本、打 tag、上传 assets、release。"
---

# zbox-release —— zbox 发版流程说明书

发版 = 改版本号 → 全量构建 → tag → GitHub release（带安装包 assets）→ 官网同步并上线。
全程在仓库根目录操作，工具链要求：Python+PySide6+PyInstaller、JDK 17、DevEco Studio（D:\Program Files\Huawei）+ devecocli、gh CLI（已登录 evachxji）。

## 0. 确认版本号（必须先做）

**用户没给新版本号就必须问，不许自己编。** 当前版本在 `version.py` 的 `APP_VERSION`（唯一来源）。
把用户给的版本记为 `<VER>`（如 `0.4.2`），tag 名 `v<VER>`。先确认该 tag 不存在：`git tag -l "v<VER>"` 应为空。

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

- 验证：`git diff version.py` 只有一行变化。提交：`git commit -m "chore: 版本号更新至 v<VER>"`。

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

## 3. 推送 + 打 tag

```powershell
git push origin main
git tag v<VER> <版本号commit的hash>
git push origin v<VER>
```

tag 打在版本号提交上（website 等后续提交在 tag 之后，没关系）。

## 4. 建 GitHub release 并传 assets

notes 参考上一版格式（`gh release view <上一tag>`）：开头一句定位 + 「## 本版变化」
（从 `git log <上一tag>..HEAD --oneline` 归纳，面向用户语言，不写 commit hash）+ 「## 下载」分端说明。
写到 `dist\release-notes.md` 再用 `--notes-file` 传，避免 PowerShell 引号地狱。

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

## 5. 官网同步并上线

- `website/index.html` + `website/js/app.js` 里所有旧版本号全局替换为新版本号
  （下载链接同样含版本号，替换 `0.x.y` 串即一并更新；同样用 python 读写）。替换后 grep 旧版本号应为 0。
- 部署与验证按 `.claude/skills/site-deploy/SKILL.md`：`python website/deploy-cos.py`，
  然后 curl 验证 `https://zbox.wzyjc.cn/` 返回 200 且页面里是新版版本号。
- 提交：`git commit -m "feat(website): 版本号与下载链接更新至 v<VER>"` 并 push。

## 验收清单

- [ ] `version.py` = 新版本，一行 diff，已提交已推送
- [ ] `dist\release\` 四个 v<VER> 产物齐全，`.app` 与上一版 hash 不同
- [ ] `git ls-remote --tags origin` 有 `v<VER>`，指向版本号提交
- [ ] `gh release view v<VER>`：非 draft，4 个 assets（exe/apk/hap/app.zip），大小与本地一致
- [ ] 官网首页与 js 里版本号为 v<VER>，下载链接指向 v<VER> assets
