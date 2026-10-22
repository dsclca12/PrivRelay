# PrivRelay

隐私优先、自托管的跨设备短信管理系统。Android 客户端接收新短信并加密保存在本机，通过端到端加密与 Go 服务同步；Web 和 Android 设备使用共享口令解密。服务端存储加密快照，并支持 HTTPS/TLS。E2EE 模式不向服务器分类器或 LLM 暴露短信正文，因此服务器端分类、全文搜索和纠错审核不可用；普通明文模式保留原有分类能力。详见[端到端加密说明](docs/END_TO_END_ENCRYPTION.md)。

当前处于 **Android MVP 与后端联调阶段**，Web 控制台初版已交付，尚未完成生产稳定性和完整系统验收。

## 当前能力

| 模块 | 已实现 | 边界 |
|---|---|---|
| Android | Flutter / Kotlin、新短信接收、加密存储、离线队列、收件箱、隔离与恢复、归档、设备密码应用锁 | 非默认短信应用；不导入系统历史、不发送短信，不能抑制系统短信应用通知 |
| Go 服务 | 签名配对、消息同步与查询、规则、纠错、设备撤销、浏览器会话、WebSocket | 单用户、单进程、加密文件快照；尚无 PostgreSQL、多租户、多实例支持 |
| AI 分类 | 原版 PrivateSMS-Classifier／INT8 模型；可配置 OpenAI 兼容 LLM 直接分类或复核；独立授权的自动隔离 | LLM 地址、模型、密钥默认空且关闭；分数未经校准；重要消息保护，失败正常保留，隔离可恢复 |
| Web | Vue 3 + TypeScript 控制台：消息、拦截、设备、规则、纠错审核、运行监控；管理台 API 与静态目录托管 | 归档与授权纠错样本导出；浏览器会话鉴权与实时推送，断线时 5 秒轮询补偿；尚无多用户与权限体系 |

首次配对 E2EE 设备会全局启用服务器 E2EE 模式并停用旧明文 API；Android 本地可访问的记录先加密迁移，未迁移的旧记录保留在服务器受存储加密保护的快照中，不会因浏览器配对或另一台手机完成迁移而删除。这些遗留记录尚未获得端到端保护，需要原设备迁移；当前客户端不具备端侧分类引擎，因此新 E2EE 消息不会自动分类／隔离。TLS 仍用于保护传输链路与令牌。Android 后台补发受系统省电和 OEM 限制，WorkManager 不保证秒级送达。上游源码是普通目录，没有嵌套 Git 仓库，提交及校验记录见 [集成说明](docs/CLASSIFIER_INTEGRATION.md)。更多限制见 [Android 使用说明](docs/ANDROID_MVP.md#使用边界)。

## 快速开始

以下 PowerShell 命令从仓库根目录开始。后端需要 Go 1.25 或兼容工具链；Android 需要根目录 [.fvmrc](.fvmrc) 指定的 Flutter 3.47.7、JDK 17 和 Android SDK；Web 控制台需要 Node.js 22 或更高版本。

### 一起启动 Web 与后端（Windows）

```powershell
./tools/start.ps1
```

脚本使用 Python 3.13+（Windows，已测试 3.14）准备固定依赖并启动原版分类器，安装缺失的 Web 依赖、构建前后端，然后由 Go 在同一个地址提供网页和 API。打开 `http://127.0.0.1:8787`，用终端显示的一次性码和至少 12 个可见 ASCII 字符的共享加密口令登录。在设备中心填写手机可访问的 HTTPS 地址并生成二维码，安卓设置填写相同共享口令后点「扫码绑定服务器」，确认后同步；也支持手动输入配对码，无需重启服务。默认沿用 `server/data/privrelay.enc`；按 Ctrl+C 停止。

已有分类器时使用 `./tools/start.ps1 -Classifier http://127.0.0.1:18788`；`-WithoutClassifier` 可主动只保存、同步消息。Docker 执行 `docker compose up --build -d` 会一起构建网页、后端和分类器。

以下为分别启动各模块的开发方式。

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

### 3. 启动 Web 控制台

```powershell
Set-Location web_client
npm install
npm run dev
```

浏览器打开终端提示的地址（默认 `http://localhost:5173`），用后端启动时显示的配对码配对，或粘贴访问令牌。开发服务器会把 `/api` 与 `/healthz` 代理到 `http://127.0.0.1:8787`，可用 `PRIVRELAY_API` 指向其他后端；设置 `VITE_MOCK=1` 可在没有后端时浏览演示数据。构建、同源部署和已知限制见 [Web 控制台说明](web_client/README.md)。

## AI / LLM 自动分类与拦截

以下为旧明文消息协议能力；当前 E2EE 客户端不向服务端发送正文，也未实现端侧模型，因此不对新密文短信自动分类或隔离。

在 Web 规则页或 Android「设置 → AI / LLM 自动分类」填写自己的兼容 API 地址、模型与密钥，选择直接分类或由轻量模型先处理、LLM 复核。所有连接配置默认留空，LLM 默认关闭。自动隔离需单独授权，并开启过滤／拦截模式；验证码、交易、安全内容、白名单与人工恢复优先保护。配置、测试及失败补偿见 [AI 分类说明](docs/AI_CLASSIFICATION.md)。

Android 同时提供列表正文隐藏、默认防截屏、分类提醒和可选的本地自动保留期限。自动清理默认关闭，不清理未上传、隔离或有待处理操作的记录。

## 文档导航

| 需求 | 文档 |
|---|---|
| 浏览全部文档、区分操作说明与历史证据 | [文档索引](docs/README.md) |
| 配置 AI / LLM 自动分类与隔离 | [AI 分类说明](docs/AI_CLASSIFICATION.md) |
| 持续集成和生成 APK / AAB | [验证与发布](docs/RELEASE.md) |
| 使用、构建和理解 Android 边界 | [Android MVP](docs/ANDROID_MVP.md) |
| 启动、构建和部署 Web 控制台 | [Web 控制台说明](web_client/README.md) |
| 部署、配置分类器和备份 | [部署指南](docs/DEPLOYMENT.md) |
| 对接客户端与管理台 | [后端 API](docs/BACKEND_API.md) |
| 本地开发、测试和提交变更 | [开发与贡献指南](CONTRIBUTING.md) |
| 查询依赖、许可证和权限 | [依赖与权限](docs/DEPENDENCIES.md) |
| 原版分类器集成与非 Android 全面测试 | [集成说明](docs/CLASSIFIER_INTEGRATION.md)、[测试报告](docs/NON_ANDROID_TEST_REPORT.md) |
| 查看本轮补齐内容和剩余工作 | [完成情况与后续工作](docs/COMPLETION_STATUS.md) |
| 查看完整立项、架构与未来验收目标 | [项目设计](docs/PROJECT_DESIGN.md) |

## 仓库结构

```text
android_client/   Flutter 客户端、Kotlin 平台代码及测试
web_client/       Vue 3 + TypeScript 管理控制台
server/           Go API、策略、加密持久化及测试
contracts/        Go / Android 共用的消息契约样本
integrations/     上游普通源码快照、公开 INT8 模型、来源与校验清单
requirements/     分类服务的固定 Python 运行依赖
tools/            隔离后端冒烟测试、Windows 分类器初测入口
docs/             使用、部署、接口、设计及历史测试报告
compose.yaml      单实例后端容器配置
```

本地 `.tools/`、`artifacts/`、`data/` 为被忽略的工具、测试产物或运行数据目录，不属于源码交付；可交付前端为 `web_client/`，本地根目录 `web/`（若存在）仅是临时草稿。

## 数据与许可

请勿提交真实短信、验证码、反馈数据、配对码、令牌、加密数据文件、密钥或签名材料。加密快照和其 `.key` 需要一起备份，并按敏感数据保护。

仓库目前未提供项目级 `LICENSE` 文件；第三方依赖许可证见[依赖与权限](docs/DEPENDENCIES.md)，不代表本项目源码已经授予相同许可。
