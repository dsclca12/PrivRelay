# Android MVP 依赖与权限

实际版本以 `android_client/pubspec.lock`、Gradle 配置和 `server/go.sum` 为准。

| 直接依赖 | 用途 | 许可证 |
|---|---|---|
| Flutter / flutter_localizations | Material 3 与平台本地化 | BSD-3-Clause |
| flutter_riverpod | 依赖注入与状态更新 | MIT |
| go_router | 页面路由 | BSD-3-Clause |
| drift / drift_dev | 本地事务、分页与 schema 生成 | MIT |
| sqlite3（SQLCipher hook） | 加密数据库 | MIT（Dart 绑定），SQLCipher BSD-style，OpenSSL Apache-2.0 |
| flutter_secure_storage | Keystore 保护的数据库密钥和令牌 | BSD-3-Clause |
| dio | 有界超时 HTTP | MIT |
| web_socket_channel | 授权的变更通知与重连 | BSD-3-Clause |
| connectivity_plus | 网络恢复后触发补发 | BSD-3-Clause |
| path_provider | 应用私有目录 | BSD-3-Clause |
| uuid | 操作幂等 ID / 配对 nonce | MIT |
| crypto | Dart 密码工具（当前未用于令牌持久化） | BSD-3-Clause |
| AndroidX WorkManager | 无 GMS 的后台补偿任务 | Apache-2.0 |
| gorilla/websocket | Go WebSocket 服务 | BSD-2-Clause |
| junit / Robolectric / flutter_test / integration_test | 测试，非运行时 SDK | EPL-1.0 / MIT / BSD-3-Clause |

选择了当前能解析安装的版本并检查了上游维护状态：不使用已废弃的 sqlcipher_flutter_libs，也不使用 Android 短信采集第三方插件。Flutter pub 在当前 SDK 限制下保留了若干兼容版本；没有为了追新强制覆盖锁文件。分发前可使用应用内 Flutter 许可证页及上游 NOTICE 进行完整的传递依赖许可复核。

Android 权限：

- RECEIVE_SMS：用户点击授权后采集新短信。
- POST_NOTIFICATIONS：用户选择后发布通用通知，不含正文。
- INTERNET / ACCESS_NETWORK_STATE：连接用户确认的服务器并补发。
- RECEIVE_BOOT_COMPLETED：设备启动后调度未完成任务。
- WorkManager 的合并清单还包含其调度所需权限（例如 WAKE_LOCK）。不申请读取短信历史、通讯录、电话状态、定位或外部存储。

依赖没有引入第三方短信分析、广告、统计或崩溃上报 SDK。原生 P-256 / AES-GCM 使用系统 Android Keystore 和 JCA。上游模型及测试用 Python 依赖不打包进 Android APK。
