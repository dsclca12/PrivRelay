# Android MVP

本版是 Flutter/Kotlin Android 客户端与单用户 Go 自托管参考服务。原始立项文档中的 Web 控制台、PostgreSQL、默认短信应用角色和完整机型验收矩阵属于后续交付，不应将本版作为全部设计目标已验收的生产版本。

## 已实现的闭环

- 用户明确授权后接收新短信，不申请 READ_SMS，不导入系统历史。
- 原生 Receiver 在返回前写入 AES-GCM 加密 SQLite spool，密钥位于 Android Keystore；分段 PDU 合并，记录时间、subscriptionId 与槽位。
- UUIDv7 消息 ID；持久化去重墓碑在 spool 消费后仍保留。Dart 的 Drift 事务提交之后才 ACK 原生记录。
- Drift + SQLCipher 业务数据库；密钥通过 flutter_secure_storage 保存。关闭系统备份。
- 本地收件箱、分类筛选、字面搜索、每页 50 条、拦截箱、恢复、详情和人工纠错。
- HTTPS 服务器确认、一次性配对码、Keystore P-256 签名注册、逐设备令牌、撤销与重新配对。解除配对和鉴权失败均保留本机记录。
- 持久化上传队列，逐消息 ACK，指数退避与抖动，断网补发；网络变化、启动、升级、重启和 WorkManager 任务触发补偿。WebSocket 只发送变更提示，重连后通过游标补拉数据。
- 原始预测与最终策略分开保存。白名单优先，验证码/交易/安全内容保护，分类失败正常保留，隔离可恢复。未校准或要求复核的模型不会仅凭分数自动隔离；用户可明确设置发件人黑名单。
- 纠错单独进入持久化操作队列，不改写模型原始分类，不自动用于训练。
- 通知始终使用通用文案，不展示发件人、验证码或正文。隔离消息不发本应用普通通知。
- 设置、设备管理、健康检查与不含短信正文的同步诊断。

## 构建

根目录 `.fvmrc` 固定 Flutter **3.47.7 stable / Dart 3.13.5**。Android minSdk 24，compileSdk / targetSdk 由该 Flutter SDK 决定（本次为 36）。使用 JDK 17、Gradle 8.14.1、AGP 8.13.1、Kotlin 2.2.20；Gradle/AGP 的后续升级提示不影响当前构建，但升级 Flutter 时需同步迁移。

```powershell
cd android_client
flutter pub get
dart run build_runner build
flutter analyze
flutter test
flutter build apk --debug --flavor dev
cd android
.\gradlew.bat :app:testDevDebugUnitTest
```

`pubspec.lock` 和 `server/go.sum` 已提交到工作区供版本控制。dev 与 prod 使用不同的应用 ID；服务器可手动输入，也可用 `--dart-define=SERVER_URL=https://relay.example.com` 提供初值。配置不内置任何实际服务器或令牌。

按顺序运行上述命令，不要并发执行 Flutter 测试和 Release 构建；两种模式共享生成的插件注册文件，并发运行会造成测试插件混入发布编译。

SQLCipher 使用 sqlite3 3.x 原生构建 hook 的 `source: sqlcipher`，不使用已停止维护的 sqlcipher_flutter_libs。数据库打开时检查 `cipher_version`，加密支持缺失时拒绝打开，不降级为明文。

dev 的网络配置只为 localhost / 127.0.0.1 / 10.0.2.2 开放 HTTP，并且需要在 Debug 界面主动勾选；prod 不允许明文传输。生产签名密钥不得入库。当前开发 APK 为 debug 签名，仅供侧载初测。

本次交付 APK 采用 Release 编译和开发签名。Flutter 的 split-per-abi 会把 ABI 偏移加入 versionCode（本次 arm64 为 2001）；将来进行源码调试覆盖安装时，构建号需高于设备上已安装的 versionCode，避免为降级而卸载、清除数据。

正式产物需要在被忽略的 `android_client/android/key.properties` 中填写 `storeFile`（相对 android 目录或绝对路径）、`storePassword`、`keyAlias`、`keyPassword`，然后执行 `flutter build apk --release --flavor prod --obfuscate --split-debug-info=../artifacts/symbols` 或对应的 `flutter build appbundle`。没有私有签名配置时 prod Release 会明确拒绝构建，避免误用 debug 签名发布。

## 自托管参考服务

```powershell
cd server
go test ./...
go run . -listen 127.0.0.1:8787 -classifier http://127.0.0.1:8000
```

服务启动时在本地终端显示有效 10 分钟的一次性配对码。每个码成功使用后立即作废；添加下一台设备时可由已授权客户端调用 `POST /api/v1/pairing-codes` 生成新码，也可重启服务，已配对设备不会因此被解除。单来源连续 10 次失败会停止该次会话的配对尝试。令牌有效期 90 天。部署时置于 HTTPS 反向代理之后，仅将 HTTPS 暴露给手机；分类器地址只能由服务器操作者配置。管理台接口及浏览器会话见 [后端接口文档](BACKEND_API.md)。

参考服务使用单进程、单用户、AES-GCM 加密文件快照和原子替换，确认前刷盘，磁盘提交失败回滚内存并不返回 ACK。数据文件及同目录 `.key` 必须一起备份并设置文件权限。该加密不能抵御拥有宿主机和密钥访问权的攻击者。该实现用于 Android MVP 的闭环验证；尚未实现 PostgreSQL、多租户、多实例、Web 控制台或大规模历史容量保障。不能同时运行两个进程写入同一存储文件。

接入现有 [PrivateSMS-Classifier](https://github.com/dsclca12/PrivateSMS-Classifier) 的 `/api/v1/classify` 与 `/healthz`，保留原模型的 `confidence_calibrated` / `needs_review`。分类器不可用时保存原始消息，服务每分钟补做未完成分类并通过游标通知客户端。可通过 `CLASSIFIER_API_KEY` 配置上游 API 密钥。

Windows 上游服务初始化反馈库会调用不可用的 `os.fchmod`。本仓库 `tools/windows_classifier.py` 是仅监听回环的初测入口，直接复用上游 ONNX 加载与推理，不改模型、不启用反馈接口；常规部署应使用上游 Linux 容器。上游代码与模型放在被忽略的 `.tools/`，不随本仓库重复发布。

## Android 初测

连接 ADB 后执行：

```powershell
adb reverse tcp:8787 tcp:8787
cd android_client
flutter test integration_test/mvp_test.dart --flavor dev -d <设备序列号> --dart-define=PAIRING_CODE=<刚生成的配对码>
```

使用合成数据，覆盖签名配对 → 原生暂存 → 本地加密 → 离线失败与重试 → 真实模型分类 → 黑名单隔离 → UI 恢复 → 纠错 → 撤销与历史保留。测试结束会解除配对。测试运行器使用的 APK 不是交付主程序，完成后需重新构建安装 `lib/main.dart` 的 APK。

`devDebug` 额外提供受系统 DUMP 权限保护的 shell 合成短信 Receiver，用于测试普通后台进程回收后的 WorkManager 消费；所有 Release 和 prod 构建均不包含它。MethodChannel 的合成注入也仅对 dev Debug 开启。

## 使用边界

- 本版不是默认短信应用，不能抑制系统短信应用的通知，不能向运营商拦截短信，也不提供短信发送。
- 服务端能够读取待分类正文；TLS 和本地加密不等于端到端加密。
- 不提供前台常驻服务，系统省电/OEM 自启动限制可能延迟后台补发；WorkManager 不承诺秒级送达。强行停止应用会暂停广播和任务，用户需再次打开。
- 智能过滤和自动隔离在本 MVP 共用隔离箱，均抑制本应用隔离通知；没有验证为可自动隔离的模型时只依靠明确用户规则，不宣称真实误拦截率。
- 尚未完成 Android 7/10/12/14/15 多版本、真实双卡来信、30 分钟断网、Doze、低电量及设备重启的完整验收。合成 SIM 槽位验证不等于实际双卡网络验收。
- 首版为中文界面，支持系统深色模式和字体缩放；英文完整翻译、应用锁、历史导入、清理策略自动化和前台实时模式待扩展。

依赖许可证与权限说明见 `docs/DEPENDENCIES.md`；本次证据见 `docs/ANDROID_TEST_REPORT.md`。
