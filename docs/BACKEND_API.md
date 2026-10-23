# 后端 API 与客户端对接

[项目首页](../README.md) · [文档索引](README.md)

后端位于 `server/`，支持加密文件快照与 PostgreSQL 加密租户快照；每个进程绑定一个租户，同租户多实例由数据库 advisory lock 拒绝。设备级 admin/editor/viewer 权限限制接口。尚无逐实体关系表、同租户水平多实例或独立用户/组账户。Web 控制台位于 `web_client/`，可通过根目录 `tools/start.ps1` 与后端一起构建启动。

当前 Android／Web 使用 v2 E2EE 消息接口。下文 v1 消息分类、搜索、操作及审核仅适用于未开启 E2EE 的旧明文库；身份、会话、设备和配置仍使用 v1。任一 E2EE 设备注册后，服务器全局拒绝旧明文消息接口。代理应同时转发 `/api/v1/*`、`/api/v2/*` 和 `/healthz`。

## 端到端加密消息协议

- 注册请求带 `e2ee:true`，签名原文在旧四行后追加 `\ne2ee-v1`。成功后用同一设备认证读取 `GET /api/v2/crypto/params`，参数和信封格式见[端到端加密](END_TO_END_ENCRYPTION.md)。
- `GET /api/v2/encrypted-messages?cursor=0&limit=50` 返回 `{messages, cursor, has_more}`；普通记录外层字段为 `message_id`、`device_id`、`received_at`、`revision`、`ciphertext`。启用服务端保留期限后，过期记录以 `deleted:true` 墓碑返回，`ciphertext` 为空、`device_id` 为空；客户端应删除本地消息及待处理操作，但仍需推进 revision 游标。客户端必须使用外层修订号和身份，不能信任内层旧修订号。
- `POST /api/v2/encrypted-messages/sync` 接收 `{messages:[...]}`，每条包含 `message_id`、`received_at`、`ciphertext`，覆盖已有不同密文时必须带当前 `base_revision`。冲突返回 `409 revision_conflict`，整批回滚；相同密文重放幂等，新消息可以省略 `base_revision`。单批 1～50 条，请求上限 5 MiB。
- 客户端只有确认返回消息 ID、时间、密文及有效修订号后，才确认上传或移除操作队列；HTTP 200 本身不代表每条记录都得到确认。密文内保存 `corrected_category`，不覆盖模型原 `category`。
- 恢复／归档／取消归档／纠错写入时附带 `operation_id` 与 `operation_kind`（`restore`／`archive`／`unarchive`／`feedback`）。服务持久化独立密文操作收据；同 ID、同消息和动作重试只返回当前记录，标记 `operation_replayed:true`，不重放旧密文。同 ID 改用于其他消息或动作返回 `409 operation_conflict`。重放 ACK 的密文可能不同于旧请求，客户端必须解密并采用服务器当前记录，不能重新覆盖较新的操作。
- `POST /api/v2/legacy-migration` 的 `message_ids` 每次最多 50 项，只移除同一设备且已有同 ID／接收时间匹配密文的旧记录。`complete:true` 仅在所有剩余旧记录均有匹配密文时清理旧记录和关联反馈／操作／别名，否则 `409 migration_incomplete` 保留数据。浏览器配对不自动调用全库清理。

E2EE 新消息不经过服务端分类、全文搜索或纠错审核；当前客户端没有端侧模型。Web 在本机解密后搜索，Android 使用本地索引。迁移尚未完成时，服务器遗留快照仍可能包含管理员可读的旧正文。

可通过 `PRIVRELAY_RETENTION_DAYS` / `-retention-days` 为 E2EE 密文启用服务端保留期限（默认关闭）。过期记录变为持久化删除墓碑，沿用全局 revision 游标通知 Android 与 Web 删除各自本地记录；操作收据随内容一同清除，之后旧客户端上传会遇到修订冲突并先拉取删除状态。墓碑仅保留消息 ID、接收时间与修订号，不含正文密文。该机制不清理 E2EE 启用前遗留的旧明文记录、离线设备断连期间的本地副本、备份文件或分类器独立反馈卷。

## 启动与部署

启动参数、分类器配置、Docker、HTTPS 与备份统一见[部署指南](DEPLOYMENT.md)。本文件描述当前实现的接口契约；历史测试结果见[后端自动化验证记录](BACKEND_VALIDATION.md)。

## 前端接入方式

建议前端通过同源代理访问 `/api/v1/*` 和 `/healthz`，WebSocket 路径 `/api/v1/ws` 也需代理。开发代理保留原始 Host / Origin；生产反向代理保留公网 Host，设置 `X-Forwarded-Proto: https`。不要将不可信客户端传入的转发头直接交给后端。后端不开放跨域 CORS。

可选 `-web <前端构建目录>` 由后端提供静态文件。默认关闭；不会自动构建前端，也不提供 SPA history 回退，前端可采用 hash 路由。静态响应的 CSP 只允许同源脚本与连接，并允许 Element Plus 所需的内联样式；不要依赖内联脚本或 CDN。

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
| GET | `/api/v1/pairing-codes` | 查询当前码是否仍有效，返回 `{active, expires_at}`，不返回配对码 |
| POST | `/api/v1/session` | 仅接受 Bearer + 同源 Origin，换取浏览器 Cookie |
| GET | `/api/v1/session` | 返回 `{device_id, name}` |
| DELETE | `/api/v1/session` | 清除 Cookie，返回 `{logged_out:true}`；撤销设备需另用 DELETE devices |
| POST | `/api/v1/messages/sync` | Android 上传，`{messages:[...]}`，1–50 条，逐消息 ACK |
| GET | `/api/v1/messages?cursor=0&limit=50` | 安卓增量同步，按 revision 升序 |
| GET | `/api/v1/messages/search` | 网页列表，按 received_at 降序、message_id 升序打破同时间并列 |
| GET | `/api/v1/messages/{id}` | 单条详情 |
| GET | `/api/v1/filter/quarantine` | 拦截箱，查询参数与 search 相同，固定 action=quarantine |
| POST | `/api/v1/messages/{id}/restore` | 恢复，返回完整 Message 并发出变更通知 |
| POST | `/api/v1/messages/{id}/feedback` | 新纠错返回 `{status:"pending_review"}`；重试返回已有审核状态，不覆盖模型原始预测 |
| GET | `/api/v1/feedback` | 反馈分页、状态计数与已通过类别分布，不含短信正文 |
| PUT | `/api/v1/feedback/{operation_id}` | 通过或驳回待审核反馈，记录审核设备与时间 |
| POST | `/api/v1/feedback/{operation_id}/withdraw` | 持久撤回此反馈的后续审核与导出资格 |
| GET / PUT | `/api/v1/filter/rules` | 读取 / 保存完整规则 |
| GET | `/api/v1/devices` | Device 数组，不返回令牌哈希 |
| DELETE | `/api/v1/devices/{id}` | 撤销设备，关闭其 WebSocket，返回 `{revoked:true}` |
| PUT | `/api/v1/devices/{id}/role` | 管理员设置设备角色 `admin / editor / viewer`；不能降级最后一个有效管理员 |
| GET | `/api/v1/status` | 消息 / 分类 / 隔离 / 设备连接 / 待复核统计 |
| GET | `/api/v1/ws` | Bearer 认证升级 WebSocket；双向心跳与 `changed` 通知。Android 可发送 `sms_relay`（消息 ID + 客户端 E2EE 密文），服务端只转给其他在线设备，不写入存储；离线补发仍走加密游标同步 |

设备角色以已配对设备为主体：`admin` 可管理配对、设备、规则、AI 配置和导出；`editor` 可同步消息、发起归档/恢复/纠错及撤回授权；`viewer` 仅可读取。旧快照缺少角色时按管理员兼容。管理员生成配对码时选择新设备角色，默认 `editor`。未认证配对接口仍要求一次性码和设备签名。

所有 epoch 时间：Message 的 `received_at` 是**毫秒**，设备 `expires_at`、配对码 `expires_at` 和 `server_time` 是**秒**。令牌有效期 90 天；撤销或到期后返回 401，本地历史不清除。

### Android 扫码绑定

Web 设备中心允许填写手机可访问的服务器根地址，然后生成二维码。二维码在浏览器本地生成，无第三方二维码服务；内容与 [共享样本](../contracts/pairing.json) 一致：

```json
{"type":"privrelay-pairing","version":1,"server":"https://relay.example.com","pairing_code":"一次性配对码","expires_at":2000000000}
```

Android 设置中的「扫码绑定服务器」读取二维码，检查版本、字段、有效期及服务器地址，在用户确认同步目的地后调用原有签名注册接口。二维码不是长期令牌；配对码仍由后端执行 10 分钟有效、单次使用、重新生成使旧码失效的限制。Web 定期查询配对状态，消费或过期后移除二维码并刷新设备列表。二维码包含临时授权凭据，请勿分享或记录到日志。

正式 Android 仅接受 HTTPS；地址不能包含账号、路径、查询参数或 fragment。dev Debug 的 HTTP 测试需主动勾选允许 HTTP，且网络配置仅允许 `127.0.0.1`、`localhost` 和模拟器 `10.0.2.2`；使用 ADB 回环时先执行 `adb reverse tcp:8787 tcp:8787`。网页默认地址来自浏览器当前源，开发时需确认端口是后端端口（默认 8787），而非 Vite 的 5173。手机通过局域网连接电脑时填写可访问的 HTTPS 地址。

### 注册与上传

```json
{"device_id":"随机UUID","name":"Android 手机","public_key":"Base64 SPKI","nonce":"随机UUID","pairing_code":"一次性码","signature":"Base64 DER"}
```

```json
{"messages":[{"message_id":"019a0000-0000-7000-8000-000000000001","sender":"TEST","body":"合成测试短信","received_at":1792540800000,"subscription_id":1,"slot":0}]}
```

服务以认证身份覆盖 device_id，不接受客户端伪造分类或策略。上传成功返回 `{messages:[Message...]}`，只在刷盘成功后 ACK；HTTP 200 后客户端按返回的 message_id 确认。相同设备、发送方、正文、接收时间和 subscription_id 的重试去重。相同 ID 却不同内容返回 409；失败时保持本机消息，不直接删除。同步请求上限 3 MiB（涵盖 50 条、每条最多 4096 个 Unicode 字符的 JSON 转义开销，包括补充平面字符的 UTF-16 代理对转义）；其他 JSON 请求仍为 512 KiB，超限返回 413。单批分类总预算 8 秒、单次上游超时 3 秒，预算耗尽后原文正常保存并由后台补分类。

如果重传使用了不同 message_id，ACK 的 message_id 仍回显此次上传 ID，并额外提供 `canonical_message_id` 指向服务端已有记录。客户端应在确认上传时，以事务将本地记录和待处理操作合并到 canonical_message_id；后续查询、恢复、归档与纠错使用该 ID。常规 ACK 与查询结果省略此字段，不会为同一短信创建第二条服务端记录。

服务同时持久化上传别名，详情、恢复、归档与反馈接口也接受旧上传 ID；查询结果使用规范 ID。同一 ID（包括别名）之后更换正文、所属设备等身份信息仍返回 409。

### Message

```json
{"message_id":"019a0000-0000-7000-8000-000000000001","device_id":"设备UUID","sender":"TEST","body":"合成测试短信","received_at":1792540800000,"subscription_id":1,"slot":0,"category":"uncertain","confidence":0,"risk":0,"needs_review":true,"model_version":"","action":"allow","reason":"分类不可用，正常保留","revision":1,"classified":false,"restored":false}
```

category：`personal / otp / service / transaction / marketing / suspicious / uncertain`。
action：`allow / quarantine`。confidence、risk 均为 0–1。不要将待分类等同于隔离。

成功取得两份一致的上游响应时，消息额外返回 `classifier_action`（allow/block）、`classifier_reason` 和 `classifier_threshold`（实际 thresholdUsed），方便区分上游建议与用户规则的最终结果。无法取得可靠评分时不返回这些字段。

### 同步与查询

增量同步返回 `{messages:[...], cursor:整数, has_more:布尔}`。游标只在客户端本地事务成功后提交，has_more 为 true 时继续拉取。WebSocket 重连后也从原游标补拉。**不要把网页 category / action 过滤用于该接口，否则会漏掉恢复和分类更新。**

网页 search / quarantine 参数：`q`（发送方或正文，字面、不区分大小写，最长 512 字节）、`category`、`action`、`device_id`、`limit`（1–50，默认 50）、`offset`（非负整数，默认 0）。返回 `{messages:[...], total:整数, offset:整数, has_more:布尔}`。offset 是实时列表分页，期间有新短信或恢复时应刷新列表；不是数据库快照。

### 恢复与反馈

```json
{"operation_id":"客户端生成的UUID"}
```

反馈再增加 `corrected_category`。每个操作使用独立的 operation_id；将同一个 ID 用于不同短信、不同动作或不同纠错内容返回 409。归档、取消归档和恢复的操作收据与状态一起持久化，即使操作未改变当前状态也会记录。重试已确认的操作返回消息当前状态，不重放旧动作，因此服务重启后也不会撤销较新的操作；升级前未记录收据的历史操作不在此保证内。反馈重试返回已有审核状态。恢复不会删除短信，后续补分类也保留用户恢复结果。当前规则只对后续上传及尚未完成分类的消息生效，不自动回溯重判全部历史。

### 纠错审核

- `GET /api/v1/feedback?status=pending_review&offset=0&limit=20`：返回 `{feedback:[...], total, offset, has_more, counts, corrections}`。status 可为空或 `pending_review / approved / rejected / withdrawn`，limit 为 1–50。counts 为全部反馈的状态计数，corrections 为仍有授权的已通过记录 `原预测→纠正类别` 分布；均按纠错记录数统计，不代表独立短信误判率。
- `PUT /api/v1/feedback/{operation_id}`：请求 `{"review_status":"approved"}` 或 `rejected`，返回完整反馈。仅待审核可变更；同结论重试幂等，反向更改返回 409。记录审核设备 `reviewed_by` 与 epoch 秒 `reviewed_at`，刷盘失败返回 503 并回滚。
- 反馈额外保留提交时的 `predicted_category / model_version`；旧快照缺少这些字段时，列表从当前消息补充显示，不能作为原始预测的历史证据。列表不复制短信正文；查看短信使用已有详情接口。
- 已审核反馈再次提交同一个 operation_id，返回已有审核状态，不重新打开队列。审核不改变短信、隔离动作或模型参数，也不会自动向分类器发送数据。模型评估和训练仍需单独明确授权。
- `POST /api/v1/feedback/{operation_id}/withdraw` 可幂等撤回单条反馈。服务器写入撤回时间和设备 tombstone，拒绝后续审核、在列表显示 `withdrawn`，并从所有后续导出中排除；原纠错记录保留作重放防护。已下载到客户端的文件、备份或已送入外部系统的副本无法由服务器远程擦除，操作者必须另行删除。

### 规则

```json
{"mode":"classify","threshold":0.95,"whitelist":[],"blacklist":[]}
```

mode：`classify / filter / block`，threshold 为 0.8–1（兼容旧客户端字段，仅传给上游，不再参与 Go 本地置信度判断），白黑名单各最多 500 项、每项最多 128 字节。PUT 为完整替换。模型隔离决策来自 `/sms/score`；上游实际阈值由其环境变量或模型配置决定，返回的 `thresholdUsed` 才是有效阈值。验证码与交易类别、白名单、人工恢复优先保护；分类或评分任一步异常均 fail-open。移除原先本地正文数字正则及置信度阈值隔离逻辑。明确黑名单仍服从类别保护，失败／不确定结果正常保留。

### Device 与状态

Device 字段：`device_id, name, public_key, active, expires_at`。设备在线统计只表示存在有效授权的 WebSocket 连接，不保证 Android 后台进程一直在线。

status 字段：`messages, quarantined, restored, quarantine_reasons, pending_classification, categories, authorized_devices, connected_devices, pending_feedback, revision, classifier_configured, server_time`。restored 为全库已人工恢复条数，quarantine_reasons 为当前隔离原因分布，pending_feedback 只统计待审核反馈。不会包含短信正文、发件人或令牌；classifier_configured 不代表上游健康，健康用 `/healthz`。

### 错误与重试

错误通常为 `{error:"机器可读代码"}`，未知路由可能是 HTTP 404 文本；客户端不能假设全部错误均为 JSON。

| HTTP | 处理 |
|---|---|
| 400 / 422 | 参数或消息契约有误，保留原始数据，修正后重试 |
| 401 | 未授权、已撤销或令牌过期，停止自动上传并提示重新配对 |
| 403 | 签名 / 配对码 / Origin 校验失败 |
| 409 | message_id 或 operation_id 冲突，不覆盖已存记录 |
| 413 | JSON 请求体超过接口大小上限 |
| 429 | 当前配对会话单来源失败达 10 次，由已授权设备生成新码，或重启服务 |
| 503 | 刷盘失败，无 ACK，指数退避重试 |

## Android 联调

当前 `RelayRepository` 使用 E2EE 接口，需要共享口令。首次使用服务终端配对码；后续设备可用网页调用 pairing-codes 取得的新码。独立空库测试后端运行、单台开发设备连接后，从仓库根目录执行：

```powershell
adb reverse tcp:8787 tcp:8787
cd android_client
flutter test integration_test/mvp_test.dart --flavor dev -d <序列号> --dart-define=PAIRING_CODE=<刚生成的码> --dart-define=VAULT_PASSPHRASE=synthetic-test-passphrase
```

若要在专用设备额外检查系统短信 Provider 历史读取，可临时授予 dev 包 `READ_SMS` 并追加 `--dart-define=DEVICE_SMS_HISTORY_SMOKE=true`；这只校验字段和数量，不打印或同步历史正文。完成后撤回该权限。

该集成测试使用合成短信和合成隔离记录，不验证真实模型；当前流程确认最后一个管理员无法自撤销，随后解除本机配对。2026-10-23 已在 Android 15 真机运行通过。测试运行器会覆盖 dev 调试应用，不应在用户正式应用上随意执行。生产安卓仍要求 HTTPS；不要通过放宽 Release 明文网络限制完成联调。

## AI / LLM 配置

已授权客户端通过 `GET /api/v1/ai/settings` 查询配置，通过 `PUT /api/v1/ai/settings` 保存，通过 `POST /api/v1/ai/test` 发送固定合成样本。字段、空白默认值、密钥保留与清除、HTTP 显式授权、分类输出及失败补偿见 [AI 分类说明](AI_CLASSIFICATION.md#接口与密钥)。

消息新增可选字段 `classification_source`（`privatesms`／`llm`）、`llm_pending`、`primary_classification`（LLM 复核前的轻量模型分类结果）。旧客户端可忽略。`GET /api/v1/status` 增加 `llm_mode`、`pending_llm_review`。LLM 使用独立阈值，不改变原版分类器决策语义。

## 2026-10-22：归档与授权导出

- 消息新增 `archived` 布尔值，旧快照默认为 `false`，归档变化沿用现有 revision 同步流。
- `POST /api/v1/messages/{id}/archive`、`.../unarchive` 接收与恢复相同的 `operation_id`；重复设置同一状态不会产生新修订。恢复到收件箱也会取消归档。
- `GET /api/v1/messages/search` 新增 `archived=false|true|all`，默认未归档。专属隔离查询始终包含归档消息；Web 隔离页显式请求 `all`，避免隐藏可恢复记录。
- `POST /api/v1/feedback/export` 必须带 `consent:true`、`purpose:evaluation|training`、`include_text`、`offset` 和 `limit`（1–100）。仅导出已通过审核且未撤回的记录，默认不含正文；`include_text:true` 才附带 `text`、`sender`。响应附带随机 `export_id` 与 `consent:true` 收据。每次分页导出在加密快照中记录同一 ID、设备、时间、用途、是否包含正文和数量，保留最近 1000 次记录；不会调用外部服务或启动训练。分类器的手动导入器要求服务器收据、训练用途、正文授权及操作者授权记录，将其转换为仅本机保存的 `human_verified` / `training_only` JSONL；它不自动训练或上传模型。

模型调用使用请求开始时的配置快照，在全局锁外执行。设备撤销后不提交在途上传；配置变化后舍弃旧分类结果并正常保存待分类消息。后台补分类按消息轮转，提交前检查修订号，避免覆盖并发恢复或归档。WebSocket 每连接独立写入并合并变更提示，慢客户端不会占用数据锁。
