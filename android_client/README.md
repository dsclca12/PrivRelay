# PrivRelay Android

Flutter / Kotlin 短信客户端。使用、权限、构建和自托管服务说明见 [Android MVP](../docs/ANDROID_MVP.md)，历史验证见 [测试报告](../docs/ANDROID_TEST_REPORT.md)。

[项目首页](../README.md) · [文档索引](../docs/README.md) · [开发指南](../CONTRIBUTING.md)

## 构建

以下命令在 `android_client/` 中依次执行；先确认 Flutter 版本与根目录 `.fvmrc` 一致。

```powershell
flutter pub get
dart run build_runner build
flutter analyze
flutter test
flutter build apk --debug --flavor dev
```

Flutter 版本固定在根目录 `.fvmrc`。开发版应用 ID 为 `dev.privrelay.privrelay.dev`，生产版为 `dev.privrelay.privrelay`。正式发布请配置自己的签名密钥，切勿发布开发签名包。

请按顺序执行 Flutter 测试与不同模式构建；它们共享自动生成的原生插件注册文件，不能并发执行 Debug 测试和 Release 构建。
