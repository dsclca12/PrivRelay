# 后端自动化验证记录

[文档索引](README.md) · [后端 API](BACKEND_API.md)

> 历史记录：2026-10-21。本记录从 API 文档独立整理，保留当时的测试结果；本次文档整理未重新执行这些测试。设备连接、服务实例和通过数量仅对应原验证轮次。

- `go test ./... -count=1 -timeout=30s`：14 项通过。
- `go test -race ./... -count=1 -timeout=30s`：通过；`go vet ./...` 通过，Windows 服务程序构建成功。
- `flutter test test/backend_contract_test.dart test/data_test.dart`：8 项通过。`contracts/message.json` 同时被 Go 实际上传 ACK 测试与安卓解析测试使用，防止字段漂移。
- 后端测试覆盖签名配对、配对码轮换及单次消费、手机上传后管理端读取、独立分页、Cookie / Origin 校验、撤销与到期、安卓与浏览器 WebSocket、分类取消后整批落盘、存储失败回滚。
- 本机服务 `/healthz` 返回 200，未授权读取消息返回 401。该轮运行实例未配置分类器，`classifier` 为 `unavailable`，短信会保存并等待后续分类。
- 本次 ADB 无连接设备，未执行真机集成测试；Docker 未安装，容器配置尚未实跑。上述测试不代表已经完成前端页面或 Android 实机端到端验收。
