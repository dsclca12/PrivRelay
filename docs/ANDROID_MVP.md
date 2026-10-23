# Android MVP 使用与构建

[项目首页](../README.md) · [文档索引](README.md) · [部署指南](DEPLOYMENT.md)

本版包含 Flutter/Kotlin Android 客户端、Go 自托管服务和初版 Web 控制台。服务端已支持 PostgreSQL 加密租户快照与设备级角色；数据库仍不是逐实体关系表，也没有独立用户/组账户。Android 现在可由用户主动申请默认 SMS 角色，接入 SMS_DELIVER、系统 SMS 收件箱、MMS 下载和附件导入、SENDTO composer 与快捷回复。MMS 附件随消息对象端到端加密同步，单条消息最多收录 2 MiB 附件；超过上限的附件继续保存在系统 Provider 并在应用详情提示。完整机型验收矩阵仍未完成。

当前客户端配对使用[端到端加密](END_TO_END_ENCRYPTION.md)。下文服务端模型分类／隔离闭环描述旧明文协议与已迁移历史；当前 E2EE 新短信不会上传正文供服务器分类，也没有端侧自动分类实现。恢复、归档与 `corrected_category` 纠错字段在客户端写入密文同步，不进入服务端审核队列。

## 已实现的闭环

- 用户明确授权后接收新短信；历史导入仅在用户主动点击时申请 `READ_SMS`，每次读取最近最多 5,000 条系统收件箱 SMS 记录。实时接收与历史导入使用发件人、正文、时间和订阅 ID 派生的确定性 UUIDv7，写入本地加密库并进入现有同步队列，避免同条短信重复导入。
- 短信发送由用户从设置页填写号码和正文，确认发送内容及潜在运营商费用后，才单独申请 `SEND_SMS` 并交给 Android `SmsManager`；不报告虚假的送达确认。
- 原生 Receiver 在返回前写入 AES-GCM 加密 SQLite spool，密钥位于 Android Keystore；分段 PDU 合并，记录时间、subscriptionId 与槽位。
- UUIDv7 消息 ID；持久化去重墓碑在 spool 消费后仍保留。Dart 的 Drift 事务提交之后才 ACK 原生记录。
- Drift + SQLCipher 业务数据库；密钥通过 flutter_secure_storage 保存。关闭系统备份。
- 本地收件箱、分类筛选、字面搜索、每页 50 条、拦截箱、恢复、详情和人工纠错。
- HTTPS 服务器确认、一次性配对码、Keystore P-256 签名注册、逐设备令牌、撤销与重新配对。解除配对和鉴权失败均保留本机记录。
- 设置中扫码绑定 Web 设备中心生成的二维码，自动填入地址和一次性码，确认目的地后注册；相机拒绝时可手动输入。[扫码契约和测试地址说明](BACKEND_API.md#android-扫码绑定)。
- 持久化上传队列，逐消息 ACK，指数退避与抖动，断网补发；网络变化、启动、升级、重启和 WorkManager 任务触发补偿。WebSocket 使用双向 ping/pong 与退避重连。在线 Android 设备间可额外即时转发 E2EE 密文；实时副本仅在内存显示，收件箱仍由已有加密同步路径持久化。服务端不持久化转发帧，离线补发仍使用加密同步队列。
- 原始预测与最终策略分开保存。白名单优先，验证码/交易/安全内容保护，分类失败正常保留，隔离可恢复。未校准或要求复核的模型不会仅凭分数自动隔离；用户可明确设置发件人黑名单。
- 详情显示分类来源、LLM 待复核状态和轻量原始结果；这些字段随本地加密记录保存。上传 ACK 在本地事务内一起落盘，通知异常不会将已确认的记录重新标记为上传失败。
- 纠错单独进入持久化操作队列，不改写模型原始分类，不自动用于训练。
- 通知始终使用通用文案，不展示发件人、验证码或正文。隔离消息不发本应用普通通知。
- 设置、设备管理、健康检查与不含短信正文的同步诊断。
- OpenAI 兼容 LLM 配置、直接分类或轻量模型复核、独立授权的自动隔离及合成测试；默认连接配置为空，详见 [AI 分类](AI_CLASSIFICATION.md)。
- 列表正文隐藏；全应用默认 `FLAG_SECURE` 防截屏／录屏并保护最近任务画面，设置中可关闭。
- 新消息提醒支持全部、重要与风险（个人／验证码／交易／可疑／不确定）、关闭；所有通知仍不含正文。
- 自动本地保留期限可选永久／30／90／365 天；启用后立即与同步时清理过期已上传正常记录，保留隔离、未上传和待处理操作关联的消息。服务器期限默认关闭；管理员可为 E2EE 密文单独配置期限并通过同步墓碑删除各设备副本，旧明文迁移数据、备份与离线设备副本不受该设置即时清除。
- 前台实时同步可由用户选择开启；它需要通知权限、显示持续通知，并启动后台 Flutter 引擎维持双向 WebSocket，同时继续使用 WorkManager 补偿本地加密暂存队列。关闭后台补发时会同时关闭前台服务；重启设备后需重新手动开启。Android 15 的 `dataSync` 服务有运行时限，强行停止、省电策略和 OEM 行为仍可能中断，不承诺永久运行或秒级送达。

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

服务启动、分类器配置、配对码、Docker、HTTPS 与数据备份见[部署指南](DEPLOYMENT.md)；消息字段、浏览器会话和管理台对接见[后端 API](BACKEND_API.md)。服务支持加密文件快照或 PostgreSQL tenant snapshot；每个进程绑定一个租户，同租户多实例由 advisory lock 拒绝。它仍是整租户快照，不是关系表，也没有独立用户／组账户或容量保障。

## Android 初测

启动独立空库测试后端、连接单台 ADB 设备后，从仓库根目录执行。将占位符替换为实际序列号和刚生成的配对码；共享口令只用于此隔离测试，不使用日常口令：

```powershell
adb reverse tcp:8787 tcp:8787
cd android_client
flutter test integration_test/mvp_test.dart --flavor dev -d <设备序列号> --dart-define=PAIRING_CODE=<刚生成的配对码> --dart-define=VAULT_PASSPHRASE=synthetic-test-passphrase
```

当前脚本使用合成数据，覆盖签名配对 → 原生暂存 → 本地加密 → E2EE 离线失败与重试 → 合成隔离记录的 UI 恢复 → 独立纠错字段 → 最后管理员保护和本机解除配对。隔离记录由测试夹具构造，不验证真实模型或黑名单自动分类。测试运行器使用的 APK 不是交付主程序，完成后需重新构建安装 `lib/main.dart` 的 APK。

专用测试设备可给测试命令增加 `--dart-define=DEVICE_SMS_HISTORY_SMOKE=true`。当 Flutter 测试 APK 安装后，在 20 秒等待期内从另一终端执行 `adb shell pm grant dev.privrelay.privrelay.dev android.permission.READ_SMS`，以验证系统收件箱查询字段与 5,000 条上限。测试只断言数量和字段类型，不输出或上传历史短信正文；完成后可用 `adb shell pm revoke dev.privrelay.privrelay.dev android.permission.READ_SMS` 撤回测试授权。

2026-10-23 在 USB 连接的 `2304FPN6DC`（Android 15 / API 35）上运行上述完整合成集成测试，通过；另在测试包临时获得 `READ_SMS` 后验证系统收件箱读取字段和 5,000 条上限。历史正文未输出或上传，测试 APK 卸载后临时授权随包清理。测试使用隔离临时后端、合成短信和合成口令，没有发送真实短信。该验收覆盖一台 Android 15 设备，不代表其他系统版本、运营商收信、双卡、Doze、低电量或长时间断网已经验收。

`devDebug` 额外提供受系统 DUMP 权限保护的 shell 合成短信 Receiver，用于测试普通后台进程回收后的 WorkManager 消费；所有 Release 和 prod 构建均不包含它。MethodChannel 的合成注入也仅对 dev Debug 开启。

壳层调试接口（仅 dev Debug，包名 `dev.privrelay.privrelay.dev`）：

```powershell
# 注入一条可指定发件人、正文、时间戳、订阅与槽位的合成短信
adb shell am broadcast -a dev.privrelay.TEST -n dev.privrelay.privrelay.dev/dev.privrelay.privrelay.sms.TestSmsReceiver `
  --es sender "+8613800000000" --es body "【测试】验证码 123456" --el timestamp 0 --ei subscription_id 1 --ei slot 0

# 用默认后台恢复样本注入（省略任意参数即使用默认值）
adb shell am broadcast -a dev.privrelay.TEST -n dev.privrelay.privrelay.dev/dev.privrelay.privrelay.sms.TestSmsReceiver

# 查询原生暂存队列长度，输出形如 data="spool_count=1"
adb shell am broadcast -a dev.privrelay.TEST -n dev.privrelay.privrelay.dev/dev.privrelay.privrelay.sms.TestSmsReceiver --ez status true
```

上述命令必须包含 `-a dev.privrelay.TEST`；在 Android 15 上省略 action 时，shell 会把额外参数解释成默认 Intent 字段。重复测试要使用相同的发件人、正文、时间戳和订阅 ID 才能验证幂等去重。

`--el timestamp 0` 表示由设备当前时间补齐；相同发件人、正文、时间戳和订阅的消息会按指纹去重，重复广播返回同一 `message_id`。注入后立即触发一次同步任务；Receiver 仅在 `BuildConfig.DEBUG` 且 flavor 为 `dev` 时生效。

dev Debug 的同一 Receiver 还接受 `start_foreground_sync` / `stop_foreground_sync` action，用于启动或停止持续服务；启动 action 需在应用 Activity 位于前台时发送，以满足 Android 15 的前台服务启动限制。此路径不配对服务器，也不触发短信。

USB WebSocket 断线重连冒烟：在主机启动隔离的 Go 服务（`127.0.0.1:8787`），执行 `adb reverse tcp:8787 tcp:8787`，然后运行 `flutter test integration_test/ws_stability_test.dart -d <设备序列号> --flavor dev --dart-define=PAIRING_CODE=<一次性码> --dart-define=VAULT_PASSPHRASE=<仅测试用口令>`。看到 `USB_WS_STRESS: online` 后，从另一终端执行 `adb reverse --remove tcp:8787`；看到 `USB_WS_STRESS: offline observed` 后恢复 `adb reverse tcp:8787 tcp:8787`。测试会确认服务端连接数恢复到 1。ADB reverse 经 USB 转发，关闭手机 Wi-Fi 本身不会断开这条测试连接；本流程只中断测试端口映射，不触碰运营商短信。结束后运行 `adb reverse --remove tcp:8787`。

## 使用边界

- 默认 SMS 角色为用户可选项；未切换时仍不能抑制系统短信应用通知。启用后，新 SMS 写入系统 Provider 并进入本地加密队列；MMS 下载完成后读取发件地址、文本和附件并进入同一加密队列。附件最多 2 MiB，超过上限的附件留在系统 Provider，应用详情会提示未同步。系统历史导入目前只读 SMS 收件箱，每次最多 5,000 条。应用内发送需显式确认并可能收费；Android 呼叫快捷回复由系统明确触发。`SENDTO` 已路由到应用 composer，但运营商真实投递状态不可用。
- E2EE 新短信正文在客户端加密后同步，服务端只保存信封与元数据。未迁移的历史仍受服务端存储加密保护，拥有存储密钥的管理员可读；TLS、本地加密和 E2EE 是不同保护层。
- 前台实时同步默认关闭；用户开启后显示持续通知并增加耗电。系统省电/OEM 自启动限制及 Android 15 的 `dataSync` 前台服务时限仍可能延迟后台补发；WorkManager 不承诺秒级送达。强行停止应用会暂停广播和任务，用户需再次打开。在线设备的临时 WS 转发不会写服务端或接收端数据库；设备离线时由原加密队列和游标同步补发。
- 智能过滤和自动隔离在本 MVP 共用隔离箱，均抑制本应用隔离通知；没有验证为可自动隔离的模型时只依靠明确用户规则，不宣称真实误拦截率。
- 尚未完成 Android 7/10/12/14/15 多版本、真实双卡来信、MMS 运营商下载、30 分钟断网、Doze、低电量及设备重启的完整验收。合成 SIM 槽位验证不等于实际双卡网络验收。
- 界面支持跟随系统、简体中文和英文切换，语言偏好保存在本机；主要页面文案已本地化，模型返回的动态原因可能保留原语言。应用锁已实现。历史导入与单条短信发送已实现；前台实时同步可选启用，但扩展设备与长稳验收仍待完成。

依赖许可证与权限说明见[依赖与权限](DEPENDENCIES.md)；历史测试证据见[Android 初步测试报告](ANDROID_TEST_REPORT.md)。

## 归档与应用锁（2026-10-22）

收件箱可切换查看已归档记录；详情支持归档、取消归档，操作先保存在本地队列，随后同步到服务器。隔离消息归档后仍在隔离箱可见，恢复时取消归档。旧数据库通过 JSON 缺省值兼容，不需要重建数据表。

设置可启用应用锁，启用和关闭均需验证设备锁屏密码。首次进入和从后台返回时显示锁定页；取消验证不显示短信。设备必须先配置安全锁屏。启用应用锁同时开启防截屏，关闭应用锁后才能关闭防截屏；后台接收、持久化和同步不依赖界面解锁。此锁保护前台查看，不能替代设备加密，也不会把 SQLCipher 密钥绑定到每次身份验证。原生密码确认和不同 OEM 生命周期仍需实际设备验收。
