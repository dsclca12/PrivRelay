# PrivRelay Web 控制台

Vue 3 + TypeScript + Element Plus，提供消息、隔离、设备、规则、纠错审核与运行监控。

当前登录配对采用 E2EE，需要与 Android 相同的共享口令。消息在浏览器下载并解密后搜索、筛选和分页，服务端无法按正文检索；下面关于服务端搜索／审核的行为只适用于旧明文协议。当前客户端纠错保存为密文内的独立 `corrected_category` 字段，保留原预测，不进入服务器审核队列。E2EE 不提供服务端 AI 分类，详情中的分类可来自迁移的历史消息。详见[端到端加密](../docs/END_TO_END_ENCRYPTION.md)。

## 前后端一起启动

仓库根目录执行 `./tools/start.ps1`，浏览器打开 `http://127.0.0.1:8787`。脚本需要 Node.js 22+ 和 Go 1.25（支持本仓库 `.tools/go`），首次自动安装 Web 依赖；沿用 `server/data/privrelay.enc`，不会清除已有数据。

登录页输入服务端终端打印的 10 分钟一次性配对码。设备中心填写手机可访问的 HTTPS 地址后生成二维码，安卓设置中点「扫码绑定服务器」并确认同步目的地；也可手动输入配对码。生成新码会使旧码失效，使用或过期后页面自动移除二维码。开发代理模式需将二维码地址改成手机实际可连接的后端地址，详见 [扫码契约与回环测试](../docs/BACKEND_API.md#android-扫码绑定)。

## 开发

先启动 Go 后端，再在此目录执行 `npm ci`、`npm run dev`。Vite 将 `/api`（包括 WebSocket）和 `/healthz` 代理至 `http://127.0.0.1:8787`，保留 Host / Origin 以通过同源校验。PowerShell 可用 `$env:PRIVRELAY_API='http://其他后端地址:8787'` 修改代理目标。

`npm run build` 执行 TypeScript 检查和生产构建；`npm run preview` 仅预览静态产物，联调请用开发服务器或 Go 的 `-web` 托管。

## 登录与同步

- WebCrypto 生成 P-256 签名，原始文本交给 ECDSA + SHA-256，签名从 r || s 转为 ASN.1 DER 后注册。
- 注册令牌仅暂存在内存，随后调用 session 接口换取 HttpOnly、SameSite=Strict Cookie；已有 localStorage 令牌登录时会自动迁移并移除。
- 页面刷新通过 `GET /api/v1/session` 恢复身份，退出调用 `DELETE /api/v1/session` 清除服务端 Cookie。
- WebSocket 使用同源 Cookie 连接 `/api/v1/ws`，不把令牌放进 URL。收到 changed 立即补拉，重连后补拉历史，5 秒轮询兜底。
- 消息和拦截箱使用服务端搜索、筛选与分页，每页最多 50 条，不再预先下载全部正文。后台刷新只读取聚合状态并重新查询当前页；Android 的 revision 增量同步接口保留。
- 当前查询未完成时，定时推送刷新不会反复作废该请求；更改筛选或页码仍立即使旧查询失效。同一页面内，重复恢复／相同类别纠错共用未完成请求，网络失败后重试复用操作 ID，避免服务已保存但响应丢失时重复生成纠错。
- 纠错审核页支持待审核、已通过、已驳回筛选，查看原短信、审核记录和已通过纠错的类别分布。审核不直接改分类或模型，不自动上传训练数据。
- 规则中心保存完整规则。

## 部署

执行仓库根目录的 `docker compose up --build -d`，同一容器提供网页与 API。也可构建后执行 `server -web <web_client/dist绝对路径>`。网页使用 hash 路由，直接刷新不需要服务器 SPA 回退。生产使用 HTTPS 反向代理并保留公网 Host。

API 与网页必须同源，不直接跨域部署。CSP 允许 Element Plus 所需的内联样式，脚本与网络请求仍限制为同源。服务端不开放 CORS。

## 验证

原版分类器和不含 Android 的全面测试可运行根目录 `./tools/test-all.ps1 -AuditDependencies`，实际范围、上游 Windows 平台失败和 Docker 未运行项见[测试报告](../docs/NON_ANDROID_TEST_REPORT.md)。规则页的模型决策采用上游 `/sms/score`，详情保留上游建议、依据与实际阈值；本地旧阈值字段只作兼容。

仓库根目录：

```powershell
npm test --prefix web_client
npm run build --prefix web_client
cd server
../.tools/go/bin/go.exe test ./...
../.tools/go/bin/go.exe build -o ../artifacts/privrelay-server.exe .
cd ..
node tools/smoke_web.mjs
```

冒烟脚本实际打包并调用前端签名和 API 代码，使用隔离的加密存储与合成短信验证配对、Cookie、手机身份上传、规则、恢复、反馈、撤销和退出，不依赖分类器，不修改日常数据。

演示模式可用 `$env:VITE_MOCK='1'; npm run dev`，不连接真实 API。WebCrypto 配对需 localhost 或 HTTPS。

## 当前边界

单用户，无多租户或角色权限。消息历史按服务端实时列表分页；有新消息或恢复时，页内内容可能移动，非快照分页。分类器未配置时照常保存并显示待分类；真实 Android 收信、后台运行及真实模型效果需另外实机验收。


2026-10-22 新增消息页归档筛选、详情归档／取消归档，以及纠错页的授权 JSON 导出。导出默认不包含短信正文和发送方；选择用途、勾选数据使用授权后才能下载，不会自动上传至外部服务。隔离箱始终包含归档消息，恢复时取消归档。
