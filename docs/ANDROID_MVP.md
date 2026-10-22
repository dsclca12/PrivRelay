# Android MVP 使用与构建

[项目首页](../README.md) · [文档索引](README.md) · [部署指南](DEPLOYMENT.md)

本版包含 Flutter/Kotlin Android 客户端、单用户 Go 自托管参考服务和初版 Web 控制台。[项目设计](PROJECT_DESIGN.md)中的 PostgreSQL、默认短信应用角色和完整机型验收矩阵属于后续交付，不应将本版作为全部设计目标已验收的生产版本。

当前客户端配对使用[端到端加密](END_TO_END_ENCRYPTION.md)。下文服务端模型分类／隔离闭环描述旧明文协议与已迁移历史；当前 E2EE 新短信不会上传正文供服务器分类，也没有端侧自动分类实现。恢复、归档与 `corrected_category` 纠错字段在客户端写入密文同步，不进入服务端审核队列。

## 已实现的闭环

- 用户明确授权后接收新短信，不申请 READ_SMS，不导入系统历史。
- 原生 Receiver 在返回前写入 AES-GCM 加密 SQLite spool，密钥位于 Android Keystore；分段 PDU 合并，记录时间、subscriptionId 与槽位。
- UUIDv7 消息 ID；持久化去重墓碑在 spool 消费后仍保留。Dart 的 Drift 事务提交之后才 ACK 原生记录。
- Drift + SQLCipher 业务数据库；密钥通过 flutter_secure_storage 保存。关闭系统备份。
- 本地收件箱、分类筛选、字面搜索、每页 50 条、拦截箱、恢复、详情和人工纠错。
- HTTPS 服务器确认、一次性配对码、Keystore P-256 签名注册、逐设备令牌、撤销与重新配对。解除配对和鉴权失败均保留本机记录。
- 设置中扫码绑定 Web 设备中心生成的二维码，自动填入地址和一次性码，确认目的地后注册；相机拒绝时可手动输入。[扫码契约和测试地址说明](BACKEND_API.md#android-扫码绑定)。
- 持久化上传队列，逐消息 ACK，指数退避与抖动，断网补发；网络变化、启动、升级、重启和 WorkManager 任务触发补偿。WebSocket 只发送变更提示，重连后通过游标补拉数据。
- 原始预测与最终策略分开保存。白名单优先，验证码/交易/安全内容保护，分类失败正常保留，隔离可恢复。未校准或要求复核的模型不会仅凭分数自动隔离；用户可明确设置发件人黑名单。
- 详情显示分类来源、LLM 待复核状态和轻量原始结果；这些字段随本地加密记录保存。上传 ACK 在本地事务内一起落盘，通知异常不会将已确认的记录重新标记为上传失败。
- 纠错单独进入持久化操作队列，不改写模型原始分类，不自动用于训练。
- 通知始终使用通用文案，不展示发件人、验证码或正文。隔离消息不发本应用普通通知。
- 设置、设备管理、健康检查与不含短信正文的同步诊断。
- OpenAI 兼容 LLM 配置、直接分类或轻量模型复核、独立授权的自动隔离及合成测试；默认连接配置为空，详见 [AI 分类](AI_CLASSIFICATION.md)。
- 列表正文隐藏；全应用默认 `FLAG_SECURE` 防截屏／录屏并保护最近任务画面，设置中可关闭。
- 新消息提醒支持全部、重要与风险（个人／验证码／交易／可疑／不确定）、关闭；所有通知仍不含正文。
- 自动本地保留期限可选永久／30／90／365 天；启用后立即与同步时清理过期已上传正常记录，保留隔离、未上传和待处理操作关联的消息。服务器不删除；重配对或远程更新可能重新拉取。

## 构建

根目录 `.fvmrc` 固定 Flutter **3.47.7 stable / Dart 3.13.5**。Android minSdk 24，compileSdk / targetSdk 由该 Flutter SDK 决定（本次为 36）。使用 JDK 17、Gradle 8.14.1、AGP 8.13.1、Kotlin 2.2.20；Gradle/AGP 的后续升级提示不影响当前构建，但升级 Flutter 时需同步迁移。

Flutter 可能优先选择 Android Studio 自带的 Java，而非 `JAVA_HOME`。若构建提示选中了不兼容的 Java 25，先用 `flutter config --jdk-dir="<本机 JDK 17 目录>"` 指定 JDK，再重新构建；该配置会影响本机其他 Flutter 项目。

以下命令从仓库根目录开始，依次执行：

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

`pubspec.lock` 和 `server/go.sum` 纳入版本控制。dev 与 prod 使用不同的应用 ID；服务器可手动输入，也可用 `--dart-define=SERVER_URL=https://relay.example.com` 提供初值。配置不内置任何实际服务器或令牌。

按顺序运行上述命令，不要并发执行 Flutter 测试和 Release 构建；两种模式共享生成的插件注册文件，并发运行会造成测试插件混入发布编译。

SQLCipher 使用 sqlite3 3.x 原生构建 hook 的 `source: sqlcipher`，不使用已停止维护的 sqlcipher_flutter_libs。数据库打开时检查 `cipher_version`，加密支持缺失时拒绝打开，不降级为明文。

dev 的网络配置只为 localhost / 127.0.0.1 / 10.0.2.2 开放 HTTP，并且需要在 Debug 界面主动勾选；prod 不允许明文传输。生产签名密钥不得入库。未配置私有签名时，dev APK 使用开发签名，仅供侧载初测。

2026-10-21 初测产物采用 Release 编译和开发签名，详见[历史测试报告](ANDROID_TEST_REPORT.md#安装产物)。Flutter 的 split-per-abi 会把 ABI 偏移加入 versionCode（该轮 arm64 为 2001）；将来进行源码调试覆盖安装时，构建号需高于设备上已安装的 versionCode，避免为降级而卸载、清除数据。

正式产物需要在被忽略的 `android_client/android/key.properties` 中填写 `storeFile`（相对 android 目录或绝对路径）、`storePassword`、`keyAlias`、`keyPassword`，然后执行 `flutter build apk --release --flavor prod --obfuscate --split-debug-info=../artifacts/symbols` 或对应的 `flutter build appbundle`。没有私有签名配置时 prod Release 会明确拒绝构建，避免误用 debug 签名发布。

## 自托管参考服务

服务启动、分类器配置、配对码、Docker、HTTPS 与数据备份见[部署指南](DEPLOYMENT.md)；消息字段、浏览器会话和管理台对接见[后端 API](BACKEND_API.md)。当前参考服务为单用户、单进程加密快照实现，尚无 PostgreSQL、多租户、多实例及容量保障。

## Android 初测

启动独立空库测试后端、连接单台 ADB 设备后，从仓库根目录执行。将占位符替换为实际序列号和刚生成的配对码；共享口令只用于此隔离测试，不使用日常口令：

```powershell
adb reverse tcp:8787 tcp:8787
cd android_client
flutter test integration_test/mvp_test.dart --flavor dev -d <设备序列号> --dart-define=PAIRING_CODE=<刚生成的配对码> --dart-define=VAULT_PASSPHRASE=synthetic-test-passphrase
```

当前脚本使用合成数据，覆盖签名配对 → 原生暂存 → 本地加密 → E2EE 离线失败与重试 → 合成隔离记录的 UI 恢复 → 独立纠错字段 → 撤销与历史保留。隔离记录由测试夹具构造，不验证真实模型或黑名单自动分类。测试结束会解除配对；此修订尚未在真机执行。测试运行器使用的 APK 不是交付主程序，完成后需重新构建安装 `lib/main.dart` 的 APK。

`devDebug` 额外提供受系统 DUMP 权限保护的 shell 合成短信 Receiver，用于测试普通后台进程回收后的 WorkManager 消费；所有 Release 和 prod 构建均不包含它。MethodChannel 的合成注入也仅对 dev Debug 开启。

壳层调试接口（仅 dev Debug，包名 `dev.privrelay.privrelay.dev`）：

```powershell
# 注入一条可指定发件人、正文、时间戳、订阅与槽位的合成短信
adb shell am broadcast -n dev.privrelay.privrelay.dev/dev.privrelay.privrelay.sms.TestSmsReceiver --receiver-ordered `
  --es sender "+8613800000000" --es body "【测试】验证码 123456" --el timestamp 0 --ei subscription_id 1 --ei slot 0

# 用默认后台恢复样本注入（省略任意参数即使用默认值）
adb shell am broadcast -n dev.privrelay.privrelay.dev/dev.privrelay.privrelay.sms.TestSmsReceiver --receiver-ordered

# 查询原生暂存队列长度，输出形如 data="spool_count=1"
adb shell am broadcast -n dev.privrelay.privrelay.dev/dev.privrelay.privrelay.sms.TestSmsReceiver --receiver-ordered --ez status true
```

`--el timestamp 0` 表示由设备当前时间补齐；相同发件人、正文、时间戳和订阅的消息会按指纹去重，重复广播返回同一 `message_id`。注入后立即触发一次同步任务；Receiver 仅在 `BuildConfig.DEBUG` 且 flavor 为 `dev` 时生效。

## 使用边界

- 本版不是默认短信应用，不能抑制系统短信应用的通知，不能向运营商拦截短信，也不提供短信发送。
- E2EE 新短信正文在客户端加密后同步，服务端只保存信封与元数据。未迁移的历史仍受服务端存储加密保护，拥有存储密钥的管理员可读；TLS、本地加密和 E2EE 是不同保护层。
- 不提供前台常驻服务，系统省电/OEM 自启动限制可能延迟后台补发；WorkManager 不承诺秒级送达。强行停止应用会暂停广播和任务，用户需再次打开。
- 智能过滤和自动隔离在本 MVP 共用隔离箱，均抑制本应用隔离通知；没有验证为可自动隔离的模型时只依靠明确用户规则，不宣称真实误拦截率。
- 尚未完成 Android 7/10/12/14/15 多版本、真实双卡来信、30 分钟断网、Doze、低电量及设备重启的完整验收。合成 SIM 槽位验证不等于实际双卡网络验收。
- 首版为中文界面，支持系统深色模式和字体缩放；应用锁已实现，英文完整翻译、历史导入和前台实时模式待扩展。

依赖许可证与权限说明见[依赖与权限](DEPENDENCIES.md)；历史测试证据见[Android 初步测试报告](ANDROID_TEST_REPORT.md)。

## 归档与应用锁（2026-10-22）

收件箱可切换查看已归档记录；详情支持归档、取消归档，操作先保存在本地队列，随后同步到服务器。隔离消息归档后仍在隔离箱可见，恢复时取消归档。旧数据库通过 JSON 缺省值兼容，不需要重建数据表。

设置可启用应用锁，启用和关闭均需验证设备锁屏密码。首次进入和从后台返回时显示锁定页；取消验证不显示短信。设备必须先配置安全锁屏。启用应用锁同时开启防截屏，关闭应用锁后才能关闭防截屏；后台接收、持久化和同步不依赖界面解锁。此锁保护前台查看，不能替代设备加密，也不会把 SQLCipher 密钥绑定到每次身份验证。原生密码确认和不同 OEM 生命周期仍需实际设备验收。
