# PrivRelay

隐私优先、自托管的跨设备短信管理系统。Android 客户端接收新短信并加密保存在本机，通过 Go 服务同步，接入 [PrivateSMS-Classifier](https://github.com/dsclca12/PrivateSMS-Classifier) 进行分类，支持规则隔离、恢复和人工纠错。

当前处于 **Android MVP 与后端联调阶段**，尚未完成生产稳定性和完整系统验收。

## 当前能力

| 模块 | 已实现 | 边界 |
|---|---|---|
| Android | Flutter / Kotlin、新短信接收、加密存储、离线队列、收件箱、隔离与恢复 | 非默认短信应用；不导入系统历史、不发送短信，不能抑制系统短信应用通知 |
| Go 服务 | 签名配对、消息同步与查询、规则、纠错、设备撤销、浏览器会话、WebSocket | 单用户、单进程、加密文件快照；尚无 PostgreSQL、多租户、多实例支持 |
| 分类器 | 对接独立分类服务；异常时保存原文并等待补分类 | 本仓库不分发模型；未经校准或需复核的预测不能仅凭分数自动隔离 |
| Web | 已提供管理台 API 和可选静态目录托管 | 仓库尚无可运行的前端页面与构建配置 |

服务器及分类服务能够读取待分类正文，当前架构不提供端到端加密。Android 后台补发受系统省电和 OEM 限制，WorkManager 不保证秒级送达。更多限制见 [Android 使用说明](docs/ANDROID_MVP.md#使用边界)。

## 快速开始

以下 PowerShell 命令从仓库根目录开始。后端需要 Go 1.25 或兼容工具链；Android 需要根目录 [.fvmrc](.fvmrc) 指定的 Flutter 3.47.7、JDK 17 和 Android SDK。

### 1. 启动后端

```powershell
Set-Location server
go run . -listen 127.0.0.1:8787 -data data/privrelay.enc
```

保持终端打开，启动时会显示有效 10 分钟、成功使用一次即失效的配对码。省略分类器时短信仍可保存和同步，但会等待分类。接入真实模型、Docker、HTTPS 和备份说明见[部署指南](docs/DEPLOYMENT.md)。

在另一个终端检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/healthz
```

未配置分类器时，预期 `status` 为 `ok`、`classifier` 为 `unavailable`。

### 2. 构建并启动 Android 开发版

从仓库根目录，在新终端依次执行：

```powershell
Set-Location android_client
flutter --version
flutter pub get
dart run build_runner build
flutter devices
flutter run --flavor dev -d <设备序列号>
```

确认 Flutter 版本与 `.fvmrc` 一致；使用 FVM 时可将 `flutter` / `dart` 命令换为 `fvm flutter` / `fvm dart`。连接单台 ADB 设备后，可执行 `adb reverse tcp:8787 tcp:8787`，在 dev Debug 界面主动允许回环 HTTP，填写 `http://127.0.0.1:8787` 并输入配对码。多设备时使用 `adb -s <设备序列号> reverse tcp:8787 tcp:8787`。正式客户端应连接 HTTPS 地址。

完成权限授权后接收新短信；也可先使用未配对的本地模式。详细构建、签名和设备测试流程见 [Android MVP](docs/ANDROID_MVP.md) 与[开发指南](CONTRIBUTING.md)。

## 文档导航

| 需求 | 文档 |
|---|---|
| 浏览全部文档、区分操作说明与历史证据 | [文档索引](docs/README.md) |
| 使用、构建和理解 Android 边界 | [Android MVP](docs/ANDROID_MVP.md) |
| 部署、配置分类器和备份 | [部署指南](docs/DEPLOYMENT.md) |
| 对接客户端与管理台 | [后端 API](docs/BACKEND_API.md) |
| 本地开发、测试和提交变更 | [开发与贡献指南](CONTRIBUTING.md) |
| 查询依赖、许可证和权限 | [依赖与权限](docs/DEPENDENCIES.md) |
| 查看完整立项、架构与未来验收目标 | [项目设计](docs/PROJECT_DESIGN.md) |

## 仓库结构

```text
android_client/   Flutter 客户端、Kotlin 平台代码及测试
server/           Go API、策略、加密持久化及测试
contracts/        Go / Android 共用的消息契约样本
tools/            隔离后端冒烟测试、Windows 分类器初测入口
docs/             使用、部署、接口、设计及历史测试报告
compose.yaml      单实例后端容器配置
```

本地 `.tools/`、`artifacts/`、`data/` 为被忽略的工具、测试产物或运行数据目录，不属于源码交付；本地 `web/` 目录尚不构成可交付前端。

## 数据与许可

请勿提交真实短信、验证码、反馈数据、配对码、令牌、加密数据文件、密钥或签名材料。加密快照和其 `.key` 需要一起备份，并按敏感数据保护。

仓库目前未提供项目级 `LICENSE` 文件；第三方依赖许可证见[依赖与权限](docs/DEPENDENCIES.md)，不代表本项目源码已经授予相同许可。
