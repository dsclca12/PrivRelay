# 后端与客户端对接

后端位于 `server/`，沿用 Android MVP 的单用户、单进程加密持久化服务。前端由另一位开发者独立实现，本次只交付后端与接口契约。PostgreSQL、多租户、多实例尚未实现。

## 启动

```powershell
cd server
go test ./...
go run . -listen 127.0.0.1:8787 -data data/privrelay.enc -classifier http://127.0.0.1:8000
```

`-classifier` 可省略，也可通过 `CLASSIFIER_URL` 设置；不可用时仍持久化并 ACK 短信，每分钟补分类。`CLASSIFIER_API_KEY` 作为 `X-API-Key` 传给上游。首次配对码显示在服务终端，有效 10 分钟，成功一次即失效。已授权客户端可以生成新配对码，无需重启。新码取代尚未使用的旧码。

根目录 `docker compose up --build -d` 启动容器；`docker compose logs server` 查看初始配对码。命名卷保存密文和 `.key`，需一起备份。默认只开放宿主机回环 8787，生产环境由可信反向代理提供 HTTPS。容器中的分类器地址不能用宿主机的 `127.0.0.1`，应填写可达的服务名或宿主机地址。Docker 配置需在有 Docker 的环境验证。

## 前端接入方式

建议前端通过同源代理访问 `/api/v1/*` 和 `/healthz`，WebSocket 路径 `/api/v1/ws` 也需代理。开发代理保留原始 Host / Origin；生产反向代理保留公网 Host，设置 `X-Forwarded-Proto: https`。不要将不可信客户端传入的转发头直接交给后端。后端不开放跨域 CORS。

可选 `-web <前端构建目录>` 由后端提供静态文件。默认关闭；不会自动构建前端，也不提供 SPA history 回退，前端可采用 hash 路由。静态响应的 CSP 只允许同源脚本、样式和连接；不要依赖内联脚本、内联样式或 CDN。

浏览器配对流程：

1. 在 HTTPS 或 localhost 环境，用 WebCrypto 生成 ECDSA P-256 密钥对。
2. 导出公钥的 SPKI DER，编码为标准 Base64。生成至少 16 字符的随机 `device_id` 和 `nonce`（推荐 UUID）。
3. 签名原文为四项以 **LF** 连接，无末尾换行：`device_id + "\n" + public_key + "\n" + nonce + "\n" + pairing_code`。算法 ECDSA + SHA-256。
4. `signature` 必须为 **ASN.1 DER** 签名的标准 Base64。WebCrypto 返回 64 字节 `r || s`，需将 r、s 各自转为 DER INTEGER（去除前导零、最高位为 1 时补 00），再包进 DER SEQUENCE。Android Keystore 已返回 DER，可直接使用。
5. 调用注册接口取得 token，随后以 `Authorization: Bearer <token>` 调用 `POST /api/v1/session`。浏览器自动发送同源 Origin；服务设置 HttpOnly、SameSite=Strict Cookie，HTTPS 时标记 Secure。前端无需将 token 保存在 localStorage 或 URL 中。
6. 后续 fetch 默认同源 Cookie，WebSocket 使用同源 `wss://<host>/api/v1/ws`，无需 query token。刷新页面可用 `GET /api/v1/session` 恢复登录状态。

注册返回 201 后配对码已消费；若建立浏览器会话失败，可在当前页面用已返回的 token 重试 session 接口。Cookie 写请求必须有与 Host 一致的 Origin；浏览器自动处理，无需自行设置。Android 继续使用 Bearer，不要求 Origin。所有授权设备均具有单用户管理权限，包括规则修改、查看所有设备短信、生成配对码与撤销设备；不是多角色权限系统。

## 接口表

除健康检查与签名注册外，其余接口均需 Bearer 或浏览器会话。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/healthz` | `{status:"ok", classifier:"ok"或"unavailable"}`；上游异常不代表存储异常 |
| POST | `/api/v1/devices/register` | 一次性配对，返回 `{token, device_id}`，201 |
| POST | `/api/v1/pairing-codes` | 新增一次性码，返回 `{pairing_code, expires_at}`，201 |
| POST | `/api/v1/session` | 仅接受 Bearer + 同源 Origin，换取浏览器 Cookie |
| GET | `/api/v1/session` | 返回 `{device_id, name}` |
| DELETE | `/api/v1/session` | 清除 Cookie，返回 `{logged_out:true}`；撤销设备需另用 DELETE devices |
| POST | `/api/v1/messages/sync` | Android 上传，`{messages:[...]}`，1–50 条，逐消息 ACK |
| GET | `/api/v1/messages?cursor=0&limit=50` | 安卓增量同步，按 revision 升序 |
| GET | `/api/v1/messages/search` | 网页列表，按 received_at 降序、message_id 升序打破同时间并列 |
| GET | `/api/v1/messages/{id}` | 单条详情 |
| GET | `/api/v1/filter/quarantine` | 拦截箱，查询参数与 search 相同，固定 action=quarantine |
| POST | `/api/v1/messages/{id}/restore` | 恢复，返回完整 Message 并发出变更通知 |
| POST | `/api/v1/messages/{id}/feedback` | 纠错，返回 `{status:"pending_review"}`，不覆盖模型原始预测 |
| GET / PUT | `/api/v1/filter/rules` | 读取 / 保存完整规则 |
| GET | `/api/v1/devices` | Device 数组，不返回令牌哈希 |
| DELETE | `/api/v1/devices/{id}` | 撤销设备，关闭其 WebSocket，返回 `{revoked:true}` |
| GET | `/api/v1/status` | 消息 / 分类 / 隔离 / 设备连接 / 待复核统计 |
| GET | `/api/v1/ws` | 升级 WebSocket，仅推送 `{"event":"changed"}` |

所有 epoch 时间：Message 的 `received_at` 是**毫秒**，设备 `expires_at`、配对码 `expires_at` 和 `server_time` 是**秒**。令牌有效期 90 天；撤销或到期后返回 401，本地历史不清除。

### 注册与上传

```json
{"device_id":"随机UUID","name":"Android 手机","public_key":"Base64 SPKI","nonce":"随机UUID","pairing_code":"一次性码","signature":"Base64 DER"}
```

```json
{"messages":[{"message_id":"019a0000-0000-7000-8000-000000000001","sender":"TEST","body":"合成测试短信","received_at":1792540800000,"subscription_id":1,"slot":0}]}
```

服务以认证身份覆盖 device_id，不接受客户端伪造分类或策略。上传成功返回 `{messages:[Message...]}`，只在刷盘成功后 ACK；HTTP 200 后客户端按返回的 message_id 确认。相同设备、发送方、正文、接收时间和 subscription_id 的重试去重。相同 ID 却不同内容返回 409；失败时保持本机消息，不直接删除。单请求上限 512 KiB，正文最多 4096 个 Unicode 字符。单批分类总预算 8 秒、单次上游超时 3 秒，预算耗尽后原文正常保存并由后台补分类。

### Message

```json
{"message_id":"019a0000-0000-7000-8000-000000000001","device_id":"设备UUID","sender":"TEST","body":"合成测试短信","received_at":1792540800000,"subscription_id":1,"slot":0,"category":"uncertain","confidence":0,"risk":0,"needs_review":true,"model_version":"","action":"allow","reason":"分类不可用，正常保留","revision":1,"classified":false,"restored":false}
```

category：`personal / otp / service / transaction / marketing / suspicious / uncertain`。
action：`allow / quarantine`。confidence、risk 均为 0–1。不要将待分类等同于隔离。

### 同步与查询

增量同步返回 `{messages:[...], cursor:整数, has_more:布尔}`。游标只在客户端本地事务成功后提交，has_more 为 true 时继续拉取。WebSocket 重连后也从原游标补拉。**不要把网页 category / action 过滤用于该接口，否则会漏掉恢复和分类更新。**

网页 search / quarantine 参数：`q`（发送方或正文，字面、不区分大小写，最长 512 字节）、`category`、`action`、`device_id`、`limit`（1–50，默认 50）、`offset`（非负整数，默认 0）。返回 `{messages:[...], total:整数, offset:整数, has_more:布尔}`。offset 是实时列表分页，期间有新短信或恢复时应刷新列表；不是数据库快照。

### 恢复与反馈

```json
{"operation_id":"客户端生成的UUID"}
```

反馈再增加 `corrected_category`。反馈相同 operation_id 重试去重，内容冲突返回 409。恢复不会删除短信，后续补分类也保留用户恢复结果。当前规则只对后续上传及尚未完成分类的消息生效，不自动回溯重判全部历史。

### 规则

```json
{"mode":"classify","threshold":0.95,"whitelist":[],"blacklist":[]}
```

mode：`classify / filter / block`，threshold 为 0.8–1，白黑名单各最多 500 项、每项最多 128 字节。PUT 为完整替换。验证码、交易、安全内容优先保护；模型异常 fail-open；未经校准或需复核的模型不只因分数达到阈值而隔离。明确的黑名单规则仍服从重要消息保护。

### Device 与状态

Device 字段：`device_id, name, public_key, active, expires_at`。设备在线统计只表示存在有效授权的 WebSocket 连接，不保证 Android 后台进程一直在线。

status 字段：`messages, quarantined, pending_classification, categories, authorized_devices, connected_devices, pending_feedback, revision, classifier_configured, server_time`。不会包含短信正文、发件人或令牌；classifier_configured 不代表上游健康，健康用 `/healthz`。

### 错误与重试

错误通常为 `{error:"机器可读代码"}`，未知路由可能是 HTTP 404 文本；客户端不能假设全部错误均为 JSON。

| HTTP | 处理 |
|---|---|
| 400 / 422 | 参数或消息契约有误，保留原始数据，修正后重试 |
| 401 | 未授权、已撤销或令牌过期，停止自动上传并提示重新配对 |
| 403 | 签名 / 配对码 / Origin 校验失败 |
| 409 | message_id 或反馈 operation_id 冲突，不覆盖已存记录 |
| 429 | 当前配对会话单来源失败达 10 次，由已授权设备生成新码，或重启服务 |
| 503 | 刷盘失败，无 ACK，指数退避重试 |

## Android 联调

现有 `RelayRepository` 可直接使用本服务，无需更改现有字段。首次使用服务终端配对码；后续设备可用网页调用 pairing-codes 取得的新码。开发设备连接后：

```powershell
adb reverse tcp:8787 tcp:8787
cd android_client
flutter test integration_test/mvp_test.dart --flavor dev -d <序列号> --dart-define=PAIRING_CODE=<刚生成的码>
```

该集成测试需要可用的真实分类器、使用合成短信，并会撤销测试设备。测试运行器会覆盖 dev 调试应用，不应在用户正式应用上随意执行。生产安卓仍要求 HTTPS；不要通过放宽 Release 明文网络限制完成联调。

## 本次验证（2026-10-21）

- `go test ./... -count=1 -timeout=30s`：14 项通过。
- `go test -race ./... -count=1 -timeout=30s`：通过；`go vet ./...` 通过，Windows 服务程序构建成功。
- `flutter test test/backend_contract_test.dart test/data_test.dart`：8 项通过。`contracts/message.json` 同时被 Go 实际上传 ACK 测试与安卓解析测试使用，防止字段漂移。
- 后端测试覆盖签名配对、配对码轮换及单次消费、手机上传后管理端读取、独立分页、Cookie / Origin 校验、撤销与到期、安卓与浏览器 WebSocket、分类取消后整批落盘、存储失败回滚。
- 本机服务 `/healthz` 返回 200，未授权读取消息返回 401。当前运行实例未配置分类器，`classifier` 为 `unavailable`，短信会保存并等待后续分类。
- 本次 ADB 无连接设备，未执行真机集成测试；Docker 未安装，容器配置尚未实跑。上述测试不代表已经完成前端页面或 Android 实机端到端验收。
