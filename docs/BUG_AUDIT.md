# Bug 审计与修复记录（2026-10-22）

本轮检查 Go 后端、Vue 控制台和 Android 同步链路，重点验证重试、并发操作、消息身份与会话切换。所有修改基于现有工作区完成，保留审计开始前的未提交内容。

## 发现与修复

| 问题 | 可复现的影响 | 修复 |
|---|---|---|
| 上传体积与消息契约不一致 | 50 条各 4096 字符的合法短信超过原 512 KiB 限制；转义后的 emoji 批次可超过 2 MiB | 同步接口上限改为 3 MiB，其他 JSON 接口保留 512 KiB；超限明确返回 413；覆盖 UTF-8、控制字符及 UTF-16 代理对转义 |
| 归档、取消归档、恢复缺少持久化操作收据 | 先归档再取消归档，重试第一次请求会重新归档；服务重启后同样发生 | 将 operation_id 收据与消息一起保存，包括未改变状态的操作；重试只返回当前状态；动作或消息冲突返回 409；失败提交同步回滚收据 |
| 重复短信的传输 ID 与服务端 ID 不一致 | 同一短信以新 ID 重传后收到成功 ACK，但该 ID 的详情和操作均 404，Android 可能出现重复行 | ACK 额外返回 canonical_message_id；Android 在事务中合并本地记录并迁移待处理操作，后续使用服务端 ID |
| 单条坏消息导致整批永久拒绝 | 一条消息触发 409、413 或 422，邻近合法短信也被标记 rejected，不再上传 | 逐步拆分错误批次，隔离被拒绝的单条记录；合法邻居继续上传；临时故障继续退避重试 |
| Android 后续操作越过正在退避的旧操作 | 旧恢复请求延迟时，较新的归档先发送，旧恢复随后又撤销归档 | 同条消息按入队顺序发送和调度；发送前检查操作仍存在；远端响应按队列顺序叠加本地意图 |
| Android 多引擎使用过期连接配置 | 前台重新配对或解绑后，已加载的后台实例仍持有旧地址或令牌 | 同步取得消费锁后重新读取持久化连接与后台设置；配对及解绑写入使用同一把锁 |
| 慢列表响应被定时刷新反复作废 | 搜索或反馈请求慢于轮询间隔，响应持续被丢弃，列表无法显示 | 自动刷新合并为一次后续请求；当前响应可以显示；筛选和分页仍立即作废旧响应 |
| 会话切换后旧响应重新显示私密数据 | 旧搜索、反馈、详情或导出响应在会话重置后返回 | 引入会话版本，同步清空已有数据并拒绝旧会话响应和导出下载 |
| Web 同步锁跨会话串扰 | stop/start 后旧请求阻塞新同步，旧请求完成又可能释放新请求的锁 | 按请求实例管理刷新锁；停止时释放；忽略旧请求的鉴权错误和旧 socket 事件 |

## 回归证据

- 后端：[audit_regression_test.go](../server/audit_regression_test.go)、[sync_identity_test.go](../server/sync_identity_test.go)，覆盖最大合法批次、超限、旧操作重放、重启、冲突、失败回滚与去重身份。
- Android：[sync_queue_regression_test.dart](../android_client/test/sync_queue_regression_test.dart)，覆盖操作次序、并发替换、批次拒绝隔离、临时错误、凭据刷新和 canonical ID 迁移。
- Web：[test_web.mjs](../tools/test_web.mjs)，使用实际 Vue/Pinia 状态与编译后的反馈视图脚本，控制响应顺序验证慢请求及会话隔离。
- 真实进程：[smoke_web.mjs](../tools/smoke_web.mjs)，运行隔离 Go 服务和合成数据，验证签名配对、Cookie、重复 ID ACK、旧归档重试、分页、LLM 合成接口、撤销与退出。

验证命令：

```sh
cd server
go test -race ./... -count=1 -timeout=120s
go vet ./...
go build -trimpath -o ../artifacts/privrelay-server .
cd ..
npm test --prefix web_client
npm run build --prefix web_client
node tools/smoke_web.mjs
python3 tools/verify_upstream.py
cd android_client
flutter analyze
flutter test
```

Web 验证使用仓库本地 Node 22 工具链。Go 竞态测试、静态检查、6 组 Web 状态测试、生产构建、真实进程联调与 71 项上游文件及模型校验均通过；Android 静态分析通过，36 项测试全部通过（新增 11 项）。

## 适用边界

- 新增操作收据对修复后确认的请求生效，无法追溯识别升级前未记录的 operation_id。
- canonical ID 迁移由支持该字段的新客户端执行；已有旧版本客户端需要更新。此修复不自动重写历史上已经产生的孤立本地记录。
- 联调使用合成短信和本地模拟 LLM，未连接外部付费模型；未执行 Android 真机短信接收、后台保活或 Docker 部署验收。本轮结果不等同于完整生产安全审计。
