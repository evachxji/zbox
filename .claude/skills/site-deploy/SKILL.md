---
name: site-deploy
description: "把 website/ 产品介绍页一键部署到腾讯云 COS 静态托管（https://zbox.wzyjc.cn）。当用户说以下情况时触发：(1) 部署/上线 website、官网、介绍页；(2) 改了 website/ 后要发布更新；(3) zbox.wzyjc.cn 证书续期、域名或 COS 配置排查。触发词：部署网站、上线、发布官网、deploy、site-deploy、证书续期。"
---

# site-deploy —— zbox 官网（website/）部署说明书

website/ 是纯静态单页（index.html + css + js + assets 截图，无构建步骤），
托管在**腾讯云 COS 静态网站托管**，自定义域名 `https://zbox.wzyjc.cn`（免费 DV 证书，强制 HTTPS）。
与 ycblog（blog.wzyjc.cn）、ss-score（CloudBase）共用同一对腾讯云密钥与 DNSPod 域名 wzyjc.cn。

## 日常一键部署（改完 website/ 后）

```bash
python website/deploy-cos.py
```

脚本干的事：
- 逐文件上传到桶 `zbox-wzyjc-cn-1257727321`（ap-shanghai），覆盖同名 key
- html/css/js 文本资源 gzip 预压缩（`Content-Encoding: gzip`；COS 静态托管不会自动压缩）
- 全部 `Cache-Control: no-cache`（ETag 回源验证；本站文件名不带内容哈希，保证改完即时生效）
- 自动跳过：`.` 开头目录/文件（`.file-versions/`、`.od-frames/`）、`*.artifact.json`、脚本自身

**不清理远端多余 key**——若删了网站里的文件，需手动删远端对应 key：
`python -c "..." client.delete_object(Bucket='zbox-wzyjc-cn-1257727321', Key='<相对路径>')`

凭证读 `~/.tccli/default.credential`（与 tccli 同一份密钥），依赖 `qcloud_cos`（随 tccli 安装）。

## 部署后验证

```bash
# ① 默认域名（绕开自定义域名，排除域名层干扰）
curl -s -o /dev/null -w "%{http_code}" http://zbox-wzyjc-cn-1257727321.cos-website.ap-shanghai.myqcloud.com/
# ② 正式域名（应 200；http 会 302 到 https）
curl -s -o /dev/null -w "%{http_code}" https://zbox.wzyjc.cn/
```

⚠️ 本机装有 Clash 等代理时浏览器可能打不开（fake-ip 劫持）——以 curl 结果为准，真机用 4G 验证。

## 证书续期（每 ~3 个月必做）

免费 DV 证书有效期只有 3 个月，到期前网站会 https 报错。续期 = 重新申请 + 重新绑定：

```bash
# ① 重新申请（声明 DNS_AUTO；但实测自动加 _dnsauth 记录会失败，走②的手动验证）
PYTHONUTF8=1 tccli ssl ApplyCertificate --DvAuthMethod DNS_AUTO --DomainName zbox.wzyjc.cn --region ap-shanghai
#    → 记下 CertificateId；留意「进入域名验证阶段」短信
# ② 手动 DNS 验证（自动加记录失败时；DvAuths 有几分钟生成延迟，为空就等会儿再查）
PYTHONUTF8=1 tccli ssl DescribeCertificateDetail --CertificateId <新ID> --region ap-shanghai   # 取 DvAuths
PYTHONUTF8=1 tccli dnspod CreateRecord --Domain wzyjc.cn --SubDomain "_dnsauth.zbox" \
  --RecordType TXT --RecordLine 默认 --Value "<DvAuthValue>" --TTL 600 --region ap-guangzhou
# ③ 轮询直到 Status=1
PYTHONUTF8=1 tccli ssl DescribeCertificate --CertificateId <新ID> --region ap-shanghai
# ④ 绑定到 COS 域名
python website/deploy-cos.py --bind-cert <新ID>
```

⚠️ 申请若卡死（50+ 分钟无 DvAuths、无 SubmitTime）：`CancelCertificateOrder --CertificateId <ID>` 取消后重新申请。

当前证书：首次部署申请于 2026-10-03（`bHHeKE6h`，2027-01-01 到期；后续续期的新 ID 按 Domain=zbox.wzyjc.cn 在 DescribeCertificates 里找最新的）。

## 架构档案（重建/排障用）

| 组件 | 值 |
|---|---|
| COS 桶 | `zbox-wzyjc-cn-1257727321`，ap-shanghai，公有读，静态托管 index.html |
| 默认域名 | `zbox-wzyjc-cn-1257727321.cos-website.ap-shanghai.myqcloud.com` |
| 自定义域名 | `zbox.wzyjc.cn`（Type=WEBSITE，Redirect https） |
| DNS（DNSPod） | `zbox CNAME → <桶>.cos-website...`（RecordId 2423123639）+ `tencent-cloud-cos-verification=330f9099920642360956aeb752cb0d34` TXT（RecordId 2423123845，所有权长期证明，别删）+ `_dnsauth.zbox` TXT（RecordId 2423181873，证书验证记录，续期时换新值） |
| SSL 证书 | 免费 DV（TrustAsia C1），90 天有效；当前证书 `bHHeKE6h`（2026-10-03 ~ 2027-01-01），PEM 直传绑定后 COS 侧 CertId 为 `bHLrlbdc` |

首次部署顺序（2026-10-03 实操，可复现）：

1. `create_bucket(ACL='public-read')` + `put_bucket_website(IndexDocument=index.html)`
2. `python website/deploy-cos.py`（先传内容，默认域名即可访问）
3. DNSPod 建 `zbox CNAME` → cos-website 域名
4. `put_bucket_domain`（CNAME 生效后调；报 `DNSRecordVerifyFailed` 就是 DNS 没生效，等 1 分钟重试）
5. 从 `get_bucket_domain` 响应拿 `x-cos-domain-txt-verification` 值，补 TXT 记录
6. `ssl ApplyCertificate` 等签发 → `put_bucket_domain_certificate` 绑定

## 坑位（全部来自实战）

- **`UserCnameInvalid`**：绑完域名后 COS 侧 CNAME 映射有 ~5 分钟生效期，期间带 Host 访问 400——等，不用改配置。
- **`DNSRecordVerifyFailed`**（put_bucket_domain 时）：CNAME 记录还没生效/没建——先建 CNAME 再绑域名。
- **证书 CertID 引用绑定报 `InvalidArgument`**（put_bucket_domain_certificate 传 CertID）：COS 侧不引用 SSL 服务的新证书——`deploy-cos.py --bind-cert` 已改为下载 PEM 直传，别改回 CertID 引用。
- **证书绑完不是立即生效**：COS 大陆边缘节点同步证书实测 ~45 分钟，期间 SNI 返回默认 `*.cos.ap-shanghai.myqcloud.com` 证书（浏览器报域名不匹配）——等。**验证别信本机 curl 的单次 200**：本机走 Clash 时代理出口命中海外边缘会假阳性，直连调度 IP（DoH 查 cos-website A 记录）逐个测 SNI 证书 CN 才可靠。
- **证书申请卡死**（50+ 分钟无 DvAuths/SubmitTime）：`CancelCertificateOrder` 取消重新申请；DNS_AUTO 的「自动加 _dnsauth 记录」实测失败（腾讯云短信会提示），手动验证是唯一可靠路径。
- 本机代理（Clash fake-ip，`198.18.x.x`）会劫持浏览器与 curl 的 DNS——`nslookup` 看到 198.18 段属正常，以带 Host 头直连默认域名的测试为准。
- Windows 下 tccli 输出是 GBK，管道给 python 解析会炸——tccli 前置 `PYTHONUTF8=1`（本说明书所有 tccli 命令都已带）。
- `index.html.artifact.json` 是编辑器产物，已在脚本排除；曾误传一次，靠 `delete_object` 清理。
- 不要给 html 配长缓存：本站 css/js 文件名不带哈希，html 若被缓存会拿旧引用对新内容。
