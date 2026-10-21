# PrivateSMS-Classifier 集成

[项目首页](../README.md) · [部署](DEPLOYMENT.md) · [测试报告](NON_ANDROID_TEST_REPORT.md)

## 来源与目录

原仓库：[dsclca12/PrivateSMS-Classifier](https://github.com/dsclca12/PrivateSMS-Classifier)，固定提交 `87f5874057f12756c7c5a0cc2544b04320fbf591`。

`integrations/PrivateSMS-Classifier/` 是普通源码目录，没有 `.git`、gitlink 或 `.gitmodules`，不是子模块。源码、公开 INT8 模型、测试、LICENSE 和 NOTICE 一起保留。`integrations/UPSTREAM.json` 记录来源，`UPSTREAM_FILES.json` 对原仓库 71 个文件记录 SHA-256（文本统一换行为 LF 后计算，模型按原始字节）。运行 `python tools/verify_upstream.py` 验证未改动上游代码或模型。

公开模型 `model.int8.onnx` 的 SHA-256 为 `a83a6de05a2a17e310a6e28f8d9e1148ad7d8ed2f964633c15f02310ce3eacc6`。保留模型卡中的合成数据来源、Apache-2.0 与 hfl/rbt3 条款。本轮没有修改模型、重新训练模型或绕过复核标记。

部署层使用独立的 `requirements/classifier-runtime.txt` 固定运行依赖。安全审计后升级 Starlette 1.3.1、setuptools 83.0.0、pytest 9.0.3；Starlette、pytest 超出上游 optional-extra 原始上界，因此安装原版源码时使用 `--no-deps`，并针对固定环境执行完整接口与真实模型验证。上游自己的 pyproject、constraints 和业务源码保持原样。

## 决策链路

1. Go 调用原版 `POST /api/v1/classify`，保留类别、置信度、风险、校准状态、复核标记和模型版本。
2. Go 调用原版 `POST /sms/score` 获取 `action / score / reason / modelVersion / thresholdUsed / category / needsReview`。这是一次额外推理，不能假设只发生一次模型调用。
3. 两份响应必须在类别、版本、复核状态和风险评分上保持一致。请求失败、超时、跳转、缺字段、非法值或模型切换造成的不一致，均正常保存原文并等待补分类。只有符合上游文档契约的 `block` 可以成为模型隔离建议。
4. PrivRelay 保留产品控制：仅分类模式、人工恢复、OTP／交易类别保护、白名单优先、用户明确黑名单。不再用自己的正文数字正则或本地置信度阈值推导模型隔离。

最终 `action` 仍是 PrivRelay 的 `allow / quarantine`。额外保存 `classifier_action / classifier_reason / classifier_threshold`，分别展示上游建议、依据与实际阈值，便于区分模型判断和人工规则。

当前公开模型设置 `confidence_calibrated=false`、`always_requires_review=true`，因此 `/sms/score` 返回 allow，不能声称它已经启用自动模型拦截。校准且无需复核模型的 block 分支由上游测试及 Go 契约测试验证，不用伪造公开模型元数据来制造拦截演示。

### 阈值

上游 `/sms/score` 的请求虽然包含 `threshold / localScore / profile / modelVersion`，该版本的实际阈值由 `PRIVATESMS_DECISION_THRESHOLD` 或模型元数据决定；返回的 `thresholdUsed` 才是实际生效值。Go 规则字段 `threshold` 为兼容旧客户端保留，不再作为本地模型隔离阈值。Web 移除了容易误解的滑块，详情显示实际阈值。本轮未修改或测试 Android 客户端。

### 反馈

上游完整 ASGI 应用包含鉴权、分类、评分、反馈提交与人工审核接口，不再使用原先只实现 classify 的 Windows 简化替身。PrivRelay 自己的加密纠错队列仍独立保存，不自动把已有短信或纠错样本复制到上游反馈库，不自动训练。实际模型服务反馈接口只有配置 key 后才开放；本轮仅用明确标记的合成数据验证其提交与审核。

## Windows 启动

根目录运行：

```powershell
./tools/start-classifier.ps1
```

需要 Python 3.13+ 的 `os.fchmod` 支持，已测试 Python 3.14.3。脚本创建 `.tools/classifier-runtime/` 隔离环境，安装固定依赖和普通源码目录，监听 `127.0.0.1:18788`。首次安装需要联网；模型和 tokenizer 已包含，推理配置为离线。

`./tools/start.ps1` 默认一起启动分类器、构建前后端并托管 Web；已存在实现 `/sms/score` 的服务时复用。也可以传 `-Classifier <已有服务地址>`；`-WithoutClassifier` 主动只运行保存／同步流程。脚本仅停止自己创建的分类器进程。测试可用 `-Data <隔离密文文件>` 避免操作日常数据。

`CLASSIFIER_API_KEY` 由 Go 通过 `X-API-Key` 发往上游，托管脚本把同一个值映射到上游的 `PRIVATESMS_API_KEY`。不要将真实 key 提交到源码或命令日志。

上游反馈数据库可能包含明文样本。Windows 不能用 POSIX chmod 数字推断 ACL 安全性；反馈功能正式使用前需验证目录的 Windows ACL。原版 API 的反馈路由默认关闭，不应为了测试伪造权限断言通过。

## Docker

`docker compose up --build -d` 会构建内部 classifier 服务和 Go／Web 服务。分类器仅在内部网络开放，由原版 `privatesms.api.app:app` 提供完整接口；独立命名卷保存反馈数据库。Dockerfile 创建 UID 10001 可写的反馈目录，根文件系统只读，临时目录使用 tmpfs。

本轮环境未安装 Docker，也没有可用 WSL，因此未执行 Linux 镜像构建、容器或 POSIX 权限测试；不能以 Windows 的模型运行结果替代这些验证。
