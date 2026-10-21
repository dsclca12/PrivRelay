# Android MVP 初步测试报告

[文档索引](README.md)

> 历史测试快照（2026-10-21）：以下结果与环境只对应原记录轮次。本次文档整理未重新执行测试，不据此判断当前设备、进程或产物状态。不同报告的测试数量与设备状态可能因轮次不同而有差异。

日期：2026-10-21（Asia/Shanghai）。测试仅使用合成短信，没有导入手机系统历史，没有发送付费运营商短信，也没有向公共仓库发布短信数据、密钥或令牌。

## 环境

- 实机：OPPO CPH2747，Android 16 / API 36，arm64。
- 模拟器：Medium Phone API 36.1，Android 16，x86_64；使用系统 `emu sms send` 生成真实 Android 短信广播。
- 主机：Windows，Flutter 3.47.7 stable，Dart 3.13.5，JDK 17，Gradle 8.14.1，AGP 8.13.1，Kotlin 2.2.20。
- 配套 Go 服务通过 ADB reverse 回环访问；真实 PrivateSMS-Classifier INT8 ONNX 模型通过仅监听回环的 Windows 推理入口接入，模型版本 `privatesms-rbt3-synthetic-six-class-v1-int8`，保留未校准和必须复核标志。
- 本次上游分类器源码版本：`87f5874057f12756c7c5a0cc2544b04320fbf591`。

## 自动化结果

| 检查 | 结果 | 覆盖 |
|---|---|---|
| Flutter 数据 / Repository / Widget | 12 项通过 | API 解析校验、事务失败不 ACK、spool 重放去重、分页与字面搜索、上传中断恢复、退避、HTTPS 地址约束、待恢复操作与旧数据冲突、并发同步调用等待、收件箱/恢复/纠错、拒绝权限后的本地使用 |
| Kotlin / Robolectric | 3 项通过 | UUIDv7、SIM/正文参与去重、SQLite 落盘与消费后墓碑去重 |
| Go 后端 | 7 项通过 | 重要消息保护、未授权访问、幂等 ACK 与加密持久化、ID 冲突、规则/恢复/反馈/游标/撤销、P-256 一次性配对、磁盘提交失败回滚、分类器异常降级与恢复、缺失复核字段拒绝信任 |
| OPPO 真机 integration_test | 1 条完整流程通过 | 见下文 |

最终 `flutter analyze` 输出 `No issues found!`。构建脚本会输出工具链未来升级提示，当前版本仍可构建。

原始日志保存在工作区被 Git 忽略的 `artifacts/`，例如 `device-integration.log`、`kotlin-tests.log`、`server-tests.log`、`android-release.log`；Kotlin XML 位于 `android_client/build/app/test-results/testDevDebugUnitTest/`。日志中可能包含本地临时配对码或调试服务信息，不应公开发布。

## 真机完整流程

`integration_test/mvp_test.dart` 最终输出 `All tests passed!`，测试用例耗时约 27 秒（不含构建、安装）。

1. Android Keystore 生成 P-256 身份，服务验证签名并消费一次性配对码。
2. 向实际 Kotlin spool 注入两条合成短信，验证同一条重复注入返回同一 ID。
3. 将测试连接指向不存在的回环端口，验证短信转入加密业务库、原生暂存被确认消费，而上传仍保留为待重试。
4. 恢复服务连接，验证队列清空并获得真实 ONNX 分类与模型版本。
5. 验证用户黑名单中的营销短信进入隔离箱，验证码内容仍正常保留，两个模拟 SIM 槽位正确展示。
6. 在实际 Flutter UI 中进入拦截箱、打开详情、恢复消息、提交服务通知纠错；原始模型预测保持 marketing。
7. 读取业务数据库文件头，确认不是明文 SQLite 头；本地字面搜索能够查到已保存的消息。
8. 撤销本机授权，验证进入重新配对状态，本地历史保留；结束时解除测试配对，恢复后台补发开关。

该流程的“来信”来自受 dev Debug 限制的合成注入接口，验证了真机原生持久化、业务与网络闭环，不代表测试过真实运营商短信接收或实际双卡网络。

## 系统广播与后台进程恢复

在模拟器授予 RECEIVE_SMS 后，用 `emu sms send` 从 Android 系统短信入口发送 ASCII 合成测试文本。收件箱实际展示测试发件人、正文和 SIM 1。原生 SQLite 中 `seen` 为 2，`spool` 为 0，确认系统广播已经落盘并由 Dart 消费。

随后将应用放到后台，以应用自身 UID 对进程执行 SIGKILL（没有使用 force-stop），确认旧进程消失，再注入新的系统短信。系统重新创建了应用进程，WorkManager 启动 headless FlutterEngine；最终 `seen` 增为 4、`spool` 为 0。该证据覆盖进程死亡后的持久化消费，不等于已完成 Doze、整机重启或 OEM 长时间后台稳定性测试。

初次模拟器启动出现过系统 `System UI isn't responding` 弹窗；切换图形配置、恢复系统 UI 后完成上述功能测试，因此本轮不据模拟器启动表现宣称无 ANR 或满足性能指标。

最终还覆盖了 x64 Release（AOT、混淆、R8）的后台恢复：用 `am kill` 结束后台应用，确认旧进程消失，再从系统短信入口发送 `PR-RELEASE restarted background fixture`。应用进程重新创建，日志显示 `SyncWorker` 的 `Worker result SUCCESS`，随后打开完整主程序，收件箱显示该消息及前一条 Release 合成短信。该检查确认发布编译下的 headless Dart 入口没有被混淆或裁剪破坏。

## 本轮修复的实际问题

- 故障注入发现 Go 使用 JSON 回填旧快照不能清除新增 map 项，磁盘失败后内存残留；改为整体恢复快照，测试确认失败时不 ACK、不残留。
- 真机测试暴露同步忙碌时新调用提前返回；改为复用同一 Future，调用方等待提交完成，关闭数据库前也等待现有同步结束，并增加回归测试。
- 后台消费与前台处理串行，持久化任务按退避时间调度，已被前台消费的空 spool 不再额外启动 headless 引擎。
- 分类器服务失败时已经 ACK 的消息会由服务后台重新分类并推进游标，避免永远停留在未分类状态。
- 上游 Windows 反馈初始化使用 `os.fchmod`，本地初测改用独立只读推理入口，没有修改模型或放松其复核元数据。
- USB / ADB 曾多次离线，重连后回环转发丢失；恢复连接与转发后完整流程通过。连接中断不计为业务链路通过。

## 尚未验收

Android 7/10/12/14/15、真实双卡运营商来信、30 分钟断网、Doze、低电量、设备重启、真实分类误拦截率、10,000 条列表性能和 P95 时延未完成。默认短信应用模式、Web 控制台、多租户、PostgreSQL 与正式发布签名仍是后续工作。当前结果是 Android MVP 初测，不是生产稳定性或完整立项验收。

## 安装产物

最终主程序已生成并在 OPPO 上覆盖安装、打开引导页并进入本地收件箱：

- `artifacts/PrivRelay-0.1.0-android-arm64.apk`：23,571,487 字节，约 22.5 MiB，minSdk 24，targetSdk 36，dev 应用 ID，开发签名。
- `artifacts/PrivRelay-0.1.0-android-x64.apk`：25,884,275 字节，供模拟器复测。
- `artifacts/symbols/` 与 `android_client/build/app/outputs/mapping/devRelease/`：Dart 符号、R8 映射。
- `artifacts/PrivRelay-0.1.0-debug-symbols.zip`：上述符号与映射的归档。
- `artifacts/SHA256SUMS.txt`：两个 APK 的校验值。

安装包为 Release 编译，启用了 Dart 混淆、R8 与资源压缩。产物 Manifest 检查确认没有 READ_SMS 和合成测试 Receiver，且关闭备份与默认明文传输。开发 flavor 仅为三个回环测试域保留受限网络配置，正式 prod 没有此覆盖。该轮测试结束时实机保留为未配对的本地模式，需要用户自行授予短信接收权限并连接其服务器。

arm64 包 SHA-256：`acef9401fe8997ddd959d4ab237c6981f65dfef25f76c77f7a1a0817bac190b9`。
