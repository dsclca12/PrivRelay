# 开发与贡献指南

[项目首页](README.md) · [文档索引](docs/README.md)

## 开发环境

| 范围 | 要求与版本来源 |
|---|---|
| Android | Flutter 3.47.7（[.fvmrc](.fvmrc)）、Dart 3.13.5、JDK 17、Android SDK；minSdk 24 |
| Android 构建工具 | 见 Gradle wrapper、settings 与 app 配置，详见 [Android MVP](docs/ANDROID_MVP.md#构建) |
| Go 后端 | Go 1.25 或兼容工具链，见 [go.mod](server/go.mod) |
| 真实进程冒烟测试 | 支持内置 fetch 的 Node.js（建议 22 或以上）、Windows 后端 exe、已启动的真实分类器 |
| 容器部署 | 可选 Docker Engine 与 Compose 插件，见[部署指南](docs/DEPLOYMENT.md) |

工具链不在 PATH 时先配置本机环境；不要将个人绝对路径或临时工具目录写入项目配置。依赖版本以 `pubspec.lock`、Gradle 配置和 `go.sum` 为准。

## 代码边界

- `android_client/lib/`：界面、本地业务库、同步与持久化队列。
- `android_client/android/`：短信广播、Keystore、原生 spool、WorkManager、权限及通知。
- `server/`：认证、消息同步、查询、策略与加密快照。
- `contracts/message.json`：Go 上传 ACK 与 Android 解析共用的契约样本。修改字段时同时检查两端与 API 文档。
- `tools/`：开发与验证工具；分类器模型和上游源码独立维护，不复制进本仓库。

## 本地验证

按改动范围运行对应检查。以下每个代码块均从仓库根目录开始；Android 检查和不同模式的构建应顺序执行，避免共享生成文件发生冲突。

### Go 后端

```powershell
Set-Location server
go test ./... -count=1 -timeout=30s
go vet ./...
```

涉及并发、会话或 WebSocket 时，再运行 `go test -race ./... -count=1 -timeout=30s`。竞态检测需要支持的平台和 C 编译工具链；缺少环境应记录为未运行。

### Flutter 与 Kotlin

```powershell
Set-Location android_client
flutter pub get
dart run build_runner build
flutter analyze
flutter test
flutter build apk --debug --flavor dev
Set-Location android
.\gradlew.bat :app:testDevDebugUnitTest
```

仅验证消息契约时可在 `android_client/` 执行 `flutter test test/backend_contract_test.dart test/data_test.dart`。数据或生成模型变化后检查生成文件是否同步。

### Web 控制台

仓库根目录运行 `npm test --prefix web_client` 与 `npm run build --prefix web_client`。状态测试无需浏览器或分类器，覆盖搜索分页、乱序请求和会话清理；真实 Go 进程冒烟、浏览器与构建说明见 [Web 验证](web_client/README.md#验证)。

### 设备与真实分类链路

[Android 初测](docs/ANDROID_MVP.md#android-初测)包含设备集成测试命令和副作用。测试使用 dev 应用、会覆盖调试包并撤销测试设备；使用独立测试服务和合成数据，测试后重新安装主程序。不要以测试运行器代替交付 APK。

[后端冒烟测试](docs/BACKEND_SMOKE_TEST.md#复跑)说明 Windows exe 的构建、分类器前置条件及报告位置。冒烟脚本创建独立密文库，不使用正式消息库。

单元测试、构建成功、合成注入、系统广播、真实运营商来信是不同级别的证据；报告中明确实际验证到哪一层。

### 非 Android 全面测试

先按[集成说明](docs/CLASSIFIER_INTEGRATION.md)准备 Python 环境，然后从根目录运行 `./tools/test-all.ps1`。统一入口包含 Go 竞态和覆盖率、Web、原版模型真实进程、500 条消息负载与恢复、源码校验和上游单元测试，不运行 Flutter、Gradle、ADB 或 Android 设备测试。上游 Windows 平台失败不会被隐藏，统一入口因此可能返回非零；结果及跳过项写入 `artifacts/non-android-tests-*/report.json`。依赖安全扫描与浏览器交互证据见[非 Android 报告](docs/NON_ANDROID_TEST_REPORT.md)。

## 提交变更

- 说明具体问题、变更后的行为和实际验证结果。缺失的设备、Docker 或分类器验证应明确标记为未运行。
- 涉及配对、ACK、重试和落盘时，确认失败不会清除原始消息、伪造成功 ACK 或覆盖用户恢复结果。
- 不提交真实短信、验证码、反馈数据、令牌、密钥、签名配置、运行库或原始敏感日志。合成样本应明确标注。
- 正式签名与发布流程见 [Android 构建说明](docs/ANDROID_MVP.md#构建)；不要把开发签名包当作正式发布包。
- 提交前检查 `git diff --check` 和变更范围，避免混入生成产物或个人配置。

## 文档规范

1. 使用 UTF-8 Markdown，中文正文、一个一级标题，按二级和三级标题组织。命令、路径、字段和枚举使用代码格式。
2. 根 README 只承担项目介绍、当前状态、快速开始与导航；详细操作放入 `docs/`，模块 README 链接到权威说明。
3. 操作指南写当前行为；设计文档标明目标；测试报告写明日期、环境、范围、结果及未验收项。避免无时间边界的临时运行状态表述。
4. 同一事实集中维护：接口字段在 `BACKEND_API.md`，部署配置在 `DEPLOYMENT.md`，Android 使用和签名在 `ANDROID_MVP.md`，完整设计在 `PROJECT_DESIGN.md`。其他文档引用相应说明。
5. 命令块标注语言和起始工作目录；说明必需环境、占位符、服务依赖、预期结果及会改变测试设备状态的操作。PowerShell 命令不混用 Bash 语法。
6. 仓库内部使用相对 Markdown 链接；移动文档时修复入链和相对出链。新增文档加入 `docs/README.md`。
7. 接口或配置变化同步更新文档、契约样本及相关测试；不将计划能力、一次样本延迟或历史测试计数表述为生产保证。
8. 历史报告保留原日期与证据，必要时加注背景；新增复测记录与旧轮次明确区分。被忽略的本地产物路径只作为取证线索，不作为公共下载链接。

## 跨平台验证入口（2026-10-22）

Node 版本见 `.nvmrc`（22），Flutter 固定 3.47.7 / Dart 3.13.5。可在根目录执行 `python3 tools/verify.py --android --containers`，一次运行所选模块并保存结果；不带开关时仅检查 Go、上游完整性和 Web。详情见[验证与发布](docs/RELEASE.md#linux--macos--windows-统一入口)。脚本不接入日常短信库，容器使用独立项目和资料卷。
