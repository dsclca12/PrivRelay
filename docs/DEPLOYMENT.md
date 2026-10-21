# 自托管部署指南

[项目首页](../README.md) · [文档索引](README.md) · [后端 API](BACKEND_API.md)

本指南对应单用户、单进程 Go 服务。当前使用 AES-GCM 加密文件快照，不需要 PostgreSQL；不能让多个进程同时写入同一数据文件。Web 页面尚未交付，可选静态目录托管不会自动生成管理台。

## 本机启动

需要 Go 1.25 或兼容工具链。从仓库根目录执行：

```powershell
Set-Location server
go run . -listen 127.0.0.1:8787 -data data/privrelay.enc
```

保持终端运行，启动时会打印一次性配对码。相对路径按服务进程工作目录解释，上例数据位于 `server/data/`。

| 参数 | 默认值 | 用途 |
|---|---|---|
| `-listen` | `127.0.0.1:8787` | HTTP 监听地址；公网访问通过 HTTPS 反向代理 |
| `-data` | `data/privrelay.enc` | 密文快照路径；密钥为同路径追加 `.key` |
| `-classifier` | `CLASSIFIER_URL` 环境变量，未设置时为空 | 分类器基础地址，不包含 `/api/v1/classify` |
| `-web` | 空，关闭 | 可选的已有前端构建目录；无 SPA history 回退 |

`CLASSIFIER_API_KEY` 通过 `X-API-Key` 传给上游分类请求。不要将密钥写入源码或提交到版本库。

## 接入分类器

独立部署 [PrivateSMS-Classifier](https://github.com/dsclca12/PrivateSMS-Classifier)，准备其 `/healthz` 和 `/api/v1/classify`。本仓库不包含模型或模型训练环境。已有分类器监听本机 8000 时，在 `server/` 启动：

```powershell
go run . -listen 127.0.0.1:8787 -data data/privrelay.enc -classifier http://127.0.0.1:8000
```

省略分类器或上游不可用时，后端仍保存并 ACK 原始短信，每分钟重试未完成分类。保留上游未校准和需复核标志，不因分数达到阈值而绕过模型限制。

Windows 初测可使用 `tools/windows_classifier.py`：需事先安装上游 `privatesms` 包及脚本导入的依赖，将 `PRIVATESMS_MODEL_PATH` 指向有效模型。该入口仅监听 `127.0.0.1:18788`、不提供反馈接口，属于本地验证工具。常规托管使用上游 Linux 容器，具体依赖安装按上游说明。

## Docker Compose

从仓库根目录执行：

```powershell
docker compose up --build -d
docker compose logs server
```

`compose.yaml` 默认只映射宿主机 `127.0.0.1:8787`。命名卷 `relay-data` 保存 `/data/privrelay.enc` 和 `/data/privrelay.enc.key`。Compose 会注入 `CLASSIFIER_URL`、`CLASSIFIER_API_KEY`；可使用本机环境变量或被忽略的根目录 `.env` 配置。

容器中的 `127.0.0.1` 指向容器本身；分类器地址应使用容器可达的服务名或宿主机地址。本 Compose 只启动 Go 服务，不启动分类器、反向代理或前端。现有历史报告未覆盖 Docker 实跑，部署后需检查容器日志、卷权限和健康接口。

更新镜像可再次执行 `docker compose up --build -d`。不要使用 `docker compose down -v` 停机，该命令会删除保存运行数据的卷。

## HTTPS 与浏览器接入

向正式 Android 客户端提供 HTTPS 地址。后端保留在可信内网或回环监听，由反向代理终止 TLS。

- 代理 `/api/v1/*` 和 `/healthz`；`/api/v1/ws` 需要支持 WebSocket 升级。
- 保留公网 Host，HTTPS 代理设置 `X-Forwarded-Proto: https`；覆盖不可信客户端传入的转发头。
- 浏览器页面和 API 使用同源；后端不开放跨域 CORS，Cookie 写请求校验 Origin。
- `-web` 静态响应 CSP 仅允许同源脚本、样式与连接。前端不能依赖内联脚本、内联样式或 CDN；无 history 回退时可使用 hash 路由。

配对签名、浏览器 Cookie 和授权行为见 [API 文档](BACKEND_API.md#前端接入方式)。所有授权设备都具有单用户管理权限，不能将它部署为隔离多个用户的共享服务。

## 配对与检查

配对码有效 10 分钟，成功使用一次后失效。已授权客户端可调用 `POST /api/v1/pairing-codes` 生成新码；重启服务也可生成初始码，已有设备授权保留。新码替换旧码。令牌有效期 90 天。

在新终端执行（本机回环示例）：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/healthz
```

服务可用时返回 `status: ok`；`classifier: unavailable` 表示未配置或无法访问上游，不代表消息存储已失败。健康接口也不能代替真实上传与刷盘验证。未授权读取消息应返回 HTTP 401。

## 备份与恢复

1. 停止写入，停止对应后端进程或执行 `docker compose stop server`，避免复制时快照与操作状态变化。
2. 一起备份密文文件及其 `.key`，保护备份访问权限。Docker 部署备份命名卷内这两个文件。
3. 恢复时将文件对放回配置的路径，保证服务用户可读写目录和文件；不要让两个进程同时打开同一存储。
4. 启动后检查健康、配对设备身份及合成消息的上传和查询；既有会话仍受过期和撤销状态约束。

缺失原密钥时不能解密原快照，不应删除密文或用新密钥覆盖来修复。密钥与快照同存意味着拥有宿主机访问权的人仍可能读取正文，需同时保护宿主机及备份。

## 常见问题

| 现象 | 检查 |
|---|---|
| 手机连接回环地址失败 | 是否为 dev Debug、主动允许回环 HTTP，ADB 连接与 reverse 是否仍有效；prod 使用 HTTPS |
| 分类始终不可用 | 基础 URL、上游健康、密钥、容器网络是否可达；保存消息不要求上游可用 |
| 配对返回 403 / 429 | 码是否过期或消费、签名格式是否正确；单来源失败达 10 次后需要新码或重启服务 |
| 上传返回 503 | 数据目录或卷权限、磁盘空间；保留原始消息等待重试，不清空本地库 |
| 浏览器写入被拒绝 | Host / Origin 同源、代理转发头、会话过期与设备撤销状态 |
| 静态页面 404 | 是否显式设置 `-web`、构建目录是否存在；仓库没有默认前端或 history 回退 |
