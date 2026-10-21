# 非 Android 全面测试报告

[项目首页](../README.md) · [文档索引](README.md) · [分类器集成](CLASSIFIER_INTEGRATION.md)

日期：2026-10-21。范围为 Go 后端、Web、固定版本的 PrivateSMS-Classifier 原版 API 与公开 INT8 CPU 模型、消息持久化、鉴权、并发、重试及故障恢复。本轮没有运行 Flutter、Gradle、ADB、Android 应用或设备测试。Go 中保留的共享 JSON 契约与模拟设备身份属于后端 API 测试，不代表 Android 验收。

## 环境与隔离

- Windows，Go 1.27.3、Node.js 24.13.0、Python 3.14.3、ONNX Runtime 1.31.0 CPU。
- 上游提交：`87f5874057f12756c7c5a0cc2544b04320fbf591`，普通源码目录；71 个上游文件及公开模型校验通过，没有嵌套 Git 或子模块。
- 模型：`privatesms-rbt3-synthetic-six-class-v1-int8`；保持原有未校准与需人工复核标记。
- 所有数据均为合成消息。Go 进程使用 `artifacts/` 独立密文库，分类器反馈使用独立 SQLite，单元测试使用临时目录。没有向日常消息库写入测试数据。
- 没有 Docker，也没有可用 WSL。Linux 容器构建／运行及 POSIX 权限验证未执行。

## 测试结果

| 范围 | 结果 |
|---|---|
| Go 自动化 | 23 个顶层测试通过，含分类／评分契约与故障矩阵；`-race` 通过，语句覆盖率 81.0% |
| Go 静态与构建 | `go vet ./...`、实际服务 exe 构建通过 |
| 上游响应契约 | 两个接口的鉴权、字段完整性、类型、概率范围、实际阈值、模型版本／类别／风险／复核一致性；allow 不被本地高置信度改成隔离 |
| 分类器故障 | classify 401、score 404／503、302 跳转、超大／截断／非法 JSON、缺字段／null、超时、不一致模型版本、无效 block 均 fail-open，原文落盘并 ACK |
| Go 可靠性 | 并发上传及重试保持消息数；服务重启保留会话、撤销、规则和历史；磁盘提交失败回滚；密文篡改／截断、错误／缺失密钥拒绝打开且不覆盖原文件 |
| 1 万条内存数据查询 | 全库历史末页、4,000 条隔离末页、2,000 条恢复计数和隔离原因统计通过；不是 1 万条真实模型吞吐测试 |
| Web | 状态测试、TypeScript 检查、Vite 生产构建通过；筛选防抖、乱序响应、末页收缩、会话重置、请求失败重试、页面销毁保护通过 |
| Web + Go 实际进程 | WebCrypto 配对、Cookie、手机身份 API 模拟、105 条数据搜索分页、恢复、审核幂等、撤销、退出通过；测试强制关闭分类器，避免环境变量污染隔离条件 |
| 原版 INT8 实际进程 | 7 组直接 API 检查及 1 组带鉴权 Go 链路通过；含 4,096 个 Unicode 字符、非法参数不回显正文、caller 阈值／profile／模型名称不能绕过复核、官方反馈提交与审核 |
| 模型并发 | 8 个并发客户端、40 对 classify+score 共 80 次真实模型请求全部成功 |
| Go + 原版模型负载 | 500 条消息、5 个并发批次、每批 50 条及重复投递，503 条业务记录数守恒，分页无重无漏；新增故障样本后总数 504，恢复分类后仍为 504 |
| 原版服务重连 | 重启 Go 并把分类器切到不可用路由，原文正常 ACK，重复上传修订号稳定；再接回模型，待分类消息恢复且不重复入库，撤销身份仍被拒绝 |
| 浏览器实际交互 | 504 条真实模型结果展示、规则页采用上游决策且无误导性本地阈值滑块；合成名单保存后刷新仍存在；详情展示原版模型、决策、依据与实际 50% 阈值 |
| 启动工具 | 隔离环境准备、固定依赖安装、托管原版 API 健康检查、退出清理，以及统一启动器通过独立 `-Data` 提供 Web／API 均已实跑 |

一轮本机样本中，500 条真实模型消息含重试的负载检查约 5.8 秒；8 并发请求对的 P50 约 783 毫秒、P95 约 809 毫秒，包含创建 HTTP 客户端等开销。它们只是该轮合成负载的测量值，不是收信到展示的生产 P95、不是真实短信误拦截率，也不是服务容量承诺。

### 已发现并修复的问题

1. 分类器断线时，已存在消息的上传重试会制造新修订号，并可能覆盖人工恢复说明；现在未取得新分类结果时保留原记录。
2. 重复恢复操作反复增加修订号；现在对已恢复消息幂等返回。
3. Web 冒烟继承 `CLASSIFIER_URL`，可能意外连接模型导致“未分类”的断言失效；现在显式关闭测试分类器，保持隔离。
4. 原先 Go 根据本地置信度／数字正则决定模型隔离，与上游 `/sms/score` 不一致；现改为原版分类及评分双接口，并保存来源与实际阈值。
5. 名单长度的 Web 字符计数与后端 UTF-8 字节限制不一致；现在前端按 128 字节检查并提示。
6. Python 依赖审计发现 pytest、setuptools、Starlette 的已知漏洞，已更新固定运行环境并重跑真实接口、模型、Go／Web 和上游测试。

## 上游测试的未通过与未运行项

原版源码保持不改，Windows 平台执行结果：**106 passed、6 failed、1 skipped**。另有 `tests/test_benchmark.py` 依赖 POSIX `resource`，完整收集时失败；Windows 重跑明确排除此模块，保留在报告的未验证项中。

6 个失败均是断言 POSIX `0600 / 0700` 文件权限，Windows 的 `stat().st_mode` 不具备相同语义：

- `test_feedback_requires_auth_and_explicit_human_review`
- `test_train_save_reload_predict`
- `test_sanitize_public_dataset_is_path_gated_private_and_provenance_tracked`
- `test_fgrc_import_is_capped_seeded_and_training_only`
- `test_registry_requires_test_gate_and_rolls_back_atomically`
- `test_private_report_refuses_to_replace_existing_evidence`

1 个跳过是 `test_rbt_style_export_preserves_token_type_ids_and_dynamic_shapes`，因为环境没有 PyTorch；现有 INT8 CPU 推理已经实测，重新导出与训练工具链不在该环境中。

没有伪造 chmod、改掉上游断言或把失败改成通过。固定环境的 `pip check` 通过；上述权限失败在安全依赖升级前后保持相同。正式运行含敏感正文的上游反馈库前，需要 Linux POSIX 验证或 Windows ACL 验证。本轮合成反馈测试不能证明真实部署权限安全。

统一脚本保留这些失败，因此完整测试入口退出码为 1，不能描述为“所有测试全通过”。Docker 未安装的项明确为未运行。

## 依赖安全扫描

- `npm audit --prefix web_client --json`：0 条已知漏洞。
- `govulncheck v1.9.0`：未发现可达已知漏洞。
- `pip-audit 2.10.1`：初始运行环境中 3 个包存在漏洞记录；更新到 pytest 9.0.3、setuptools 83.0.0、Starlette 1.3.1 后，固定依赖扫描为 0 条已知漏洞，`pip check` 无依赖冲突。

扫描只反映该轮工具和漏洞库的结果，不代替代码审计或未来持续更新。上游 optional-extra 的旧版本上界不再直接用于 PrivRelay 部署，版本差异及验证方式见[集成说明](CLASSIFIER_INTEGRATION.md)。

## 复跑

从根目录，先准备 Python 隔离运行环境，再运行统一测试（不含 Android）：

```powershell
./tools/start-classifier.ps1
# 看到健康启动后可 Ctrl+C 停止；测试会自行启动独立的随机端口进程。
./tools/test-all.ps1 -AuditDependencies
```

安全扫描需要联网，并需要可用 `uvx`；普通 `./tools/test-all.ps1` 不包含联网漏洞扫描。报告写入 `artifacts/non-android-tests-*/report.json`，模块日志、Go 覆盖率和上游 JUnit XML 同目录保存。真实分类器报告写入 `artifacts/classifier-test-*/report.json`，其鉴权 Go 子链路日志在同目录 `authenticated-relay.log`；后端负载报告在 `artifacts/backend-smoke-*/report.json`。

代码及模型校验可单独执行 `python tools/verify_upstream.py`。上游 Windows 权限失败会导致完整入口非零；`-SkipUpstreamUnit` 仅供明确选择跳过上游单元测试的局部复测，不表示这些测试已经通过。

## 仍需外部环境的验证

Linux／Docker 实跑、持久卷及备份恢复、POSIX／ACL 权限、真实 HTTPS 代理、长时间运行、真实数据模型效果和生产时延仍未验收。本报告不会把这些未运行项目表述为已完成。
