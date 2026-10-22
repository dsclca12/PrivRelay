# 验证与发布

[项目首页](../README.md) · [文档索引](README.md)

## 持续集成

`.github/workflows/ci.yml` 在 push、pull request 和手动触发时运行 Go 竞态测试与 vet、Web 单测／生产构建、Flutter 分析／测试／开发 APK、Gradle 原生测试，以及 Docker Compose 分类器启动／签名配对／加密持久化／进程重启／幂等上传检查。

容器验收使用专属 `privrelay-test-ci` 项目名与合成短信，退出后移除该项目命名卷；普通人工验证执行 `tools/smoke_compose.mjs` 前应另外指定 `COMPOSE_PROJECT_NAME=privrelay-test-<随机标记>` 和 `PRIVRELAY_COMPOSE_TEST=1`。脚本拒绝复用普通项目名，不能连接真实资料卷。2026-10-22 已在 Linux Docker 实跑容器、备份恢复和换钥验收；GitHub Actions 执行结果仍需推送后确认。

## Android 发布构建

从仓库根目录运行 PowerShell。Flutter 必须与根目录 `.fvmrc` 一致。默认 `dev` 产物只用于内部测试，使用开发签名；正式产物需要私有签名材料。

```powershell
./tools/build-release.ps1
```

需要正式签名时，将私钥与被忽略的 `android_client/android/key.properties` 配好后运行：

```powershell
./tools/build-release.ps1 -Flavor prod
```

每次生成新的 `artifacts/releases/<flavor>-<timestamp>/`，包含 APK、AAB、对应混淆符号、锁文件及带 SHA-256 的 `manifest.json`。清单记录源码提交、工作区是否有未提交改动、Flutter 版本、产物类型及是否跳过检查。默认为发布前运行分析和 Flutter 测试；只有同一源码刚完成对应检查时才可使用 `-SkipChecks`。不要分发 `dev` 产物作为正式版，也不要上传符号文件到公开仓库。

生产密钥始终留在本机；工具不会复制、归档或打印 `key.properties`、证书或私钥。

## 本轮验证记录

更新 README 中功能时，运行相关模块的静态检查、测试和构建，并报告没有执行的设备或环境验收。`tools/smoke_web.mjs` 的 LLM 扩展使用本机合成兼容 API，验证默认无 LLM 配置、保存的 API Key 在读取时脱敏、合成探针不插入真实消息、分类隔离和人工恢复；不请求外部提供商，也不产生收费请求。

## Linux / macOS / Windows 统一入口

仓库 `.nvmrc` 与 CI 使用 Node 22；Flutter 使用 `.fvmrc` 指定的 3.47.7，`pubspec.yaml` 也声明相同最低版本。先在自己的 shell 中激活对应工具链。

```bash
python3 tools/verify.py                        # Go、上游校验、Web 和真实 Go 进程冒烟
python3 tools/verify.py --android --containers # 加入 Flutter、APK、Kotlin 和隔离容器
python3 tools/build_release.py                # 开发签名的内部 APK / AAB
python3 tools/build_release.py --flavor prod   # 必须预先配置自己的签名材料
```

Windows 可使用 `python`。验证报告写入 `artifacts/verify-*/report.json`，所选模块失败时退出码非零；容器验证结束后仅删除该次随机命名的测试卷。发布脚本强制核对 SDK 并运行分析、测试，生成 APK、AAB、各自 Dart 符号、R8 映射、锁文件和 SHA-256 清单。开发版不可作为正式版发布。

CI 额外保存 7 天的开发 Debug APK，便于真机验收；不自动发布正式版本或上传私钥与 Release 符号。容器 CI 同时运行上游 POSIX 测试。
