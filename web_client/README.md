# PrivRelay Web 控制台

Vue 3 + TypeScript 实现的浏览器控制台，对接 `server/` 的单用户 Go 参考服务，提供 README §3.5 要求的五个中心：

| 页面 | 路由 | 能力 |
| --- | --- | --- |
| 消息中心 | `/messages` | 全量消息浏览、分类 / 动作 / 关键字过滤、分页、详情抽屉、恢复与分类纠错 |
| 拦截中心 | `/quarantine` | 拦截统计、拦截原因分布、恢复与纠错、行内 popconfirm 恢复 |
| 设备中心 | `/devices` | 设备列表、公钥指纹、授权状态与到期时间、浏览器配对、撤销授权 |
| 规则中心 | `/rules` | 模式 A/B/C、隔离阈值（0.80–1.00）、白名单 / 黑名单、脏数据提示与保存 |
| 运行监控 | `/monitor` | 服务与分类服务健康探测、同步方式、消息 / 拦截 / 设备统计、本地运行日志 |

其他：登录 / 配对页（WebCrypto ECDSA P-256 配对，或粘贴访问令牌）、深浅色主题、响应式折叠侧栏、401 自动登出。

## 技术栈

- Vue 3.5 + TypeScript（`vue-tsc --noEmit` 严格模式通过）
- Vite 6、vue-router 4、Pinia 2
- Element Plus 2 + `@element-plus/icons-vue`（全量引入，默认中文语言包）
- 无额外样式框架，深色模式使用 Element Plus 官方 dark css vars

## 目录结构

```
web_client/
├─ src/
│  ├─ api/            # client.ts（fetch 封装 / 令牌 / 错误码）、endpoints.ts、types.ts、mock.ts
│  ├─ components/     # MessageTable、MessageDetailDrawer
│  ├─ composables/    # useSync.ts（WebSocket + 轮询降级、401 处理）
│  ├─ layout/         # MainLayout.vue（侧栏 / 顶栏 / 主题 / 同步状态）
│  ├─ router/
│  ├─ stores/         # auth、messages、logs
│  ├─ utils/          # format、pairing（WebCrypto 配对）、uuid
│  ├─ views/          # Login / Messages / Quarantine / Rules / Devices / Monitor
│  ├─ styles/main.css
│  ├─ App.vue
│  └─ main.ts
├─ index.html
├─ vite.config.ts
├─ tsconfig.json
└─ package.json
```

## 快速开始

要求 Node.js ≥ 20（开发时使用 Node 24 LTS 验证）。先在 `server/` 启动 Go 服务（默认监听 `127.0.0.1:8787`，启动日志会打印一次性配对码）：

```bash
cd web_client
npm install
npm run dev          # http://localhost:5173
```

开发服务器把 `/api`、`/healthz` 代理到 `PRIVRELAY_API`（默认 `http://127.0.0.1:8787`，`/api` 同时开启 `ws: true`）。需要指向其他地址时：

```bash
PRIVRELAY_API=http://192.168.1.10:8787 npm run dev
```

登录页输入服务端日志中的配对码即可完成配对。配对流程在浏览器内用 WebCrypto 生成 ECDSA P-256 密钥，签名内容与 `server/main.go` 校验逻辑严格一致：

```
SHA256(device_id + "\n" + base64(spki) + "\n" + nonce + "\n" + pairing_code)
```

私钥不落盘（仅本次配对使用），访问令牌保存在 `localStorage`。

## 演示模式（无需后端）

```bash
VITE_MOCK=1 npm run dev          # PowerShell: $env:VITE_MOCK='1'; npm run dev
```

`src/api/mock.ts` 提供内存演示数据（14 条消息、2 台设备、规则、健康检查），可完整走通配对、浏览、恢复、纠错、规则保存、撤销等交互。配对码随意输入非空值即可。

## 构建与部署

```bash
npm run build        # vue-tsc --noEmit && vite build，产物在 dist/
npm run preview      # 本地预览产物
```

服务端没有 CORS 头，**生产环境必须与 API 同源**，即用反向代理同时提供 `dist/` 与 `/api`、`/healthz`。Caddy 示例：

```caddyfile
relay.example.com {
    handle /api/* {
        reverse_proxy 127.0.0.1:8787
    }
    handle /healthz {
        reverse_proxy 127.0.0.1:8787
    }
    handle {
        root * /srv/privrelay/web_client/dist
        try_files {path} /index.html
        file_server
    }
}
```

Nginx 等价配置需为 `location / { try_files $uri $uri/ /index.html; }`，并将 `/api/`、`/healthz` 反代到 Go 服务。

若必须跨源部署，可在构建时设置 `VITE_API_BASE=https://api.example.com`，但需要自行给 Go 服务补 CORS 中间件，否则浏览器会拦截请求。

## 与 Go 服务的接口对照

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/healthz` | 服务与分类器健康状态 |
| POST | `/api/v1/devices/register` | 配对注册，返回访问令牌 |
| GET | `/api/v1/messages?cursor=&limit=` | 按 `revision` 游标增量拉取 |
| POST | `/api/v1/messages/{id}/restore` | 恢复到收件箱（幂等键 `operation_id`） |
| POST | `/api/v1/messages/{id}/feedback` | 分类纠错（进入待审核队列） |
| GET / PUT | `/api/v1/filter/rules` | 读取 / 更新规则（模式、阈值、名单） |
| GET | `/api/v1/devices` | 设备列表 |
| DELETE | `/api/v1/devices/{id}` | 撤销设备授权 |

消息字段（`message_id`、`sender`、`body`、`received_at`、`category`、`confidence`、`risk`、`needs_review`、`model_version`、`action`、`reason`、`device_id`、`revision`、`classified`、`restored` 等）与 `server/store.go` 的 JSON 契约一一对应。

## 同步策略

1. 进入控制台后先按游标拉全量历史（50 条/页，最多 400 页；超出时页面提供“加载更多历史”）。
2. 之后每 5 秒增量拉取一页，标签页重新可见时立即补拉。
3. 尝试连接 `/api/v1/ws`，收到 `changed` 事件立即刷新；连接失败自动降级为轮询并在顶栏显示“轮询同步”。
4. 任何接口返回 401/403 时清除本地会话并跳回登录页。

## 已知限制

- **WebSocket 实时推送暂不可用**：服务端 `/api/v1/ws` 只从 `Authorization` 头读取令牌，且 `CheckOrigin` 仅接受空 `Origin`；浏览器 WebSocket 无法携带自定义请求头、且必然发送 `Origin`。前端已实现自动降级轮询，功能不受影响。若要让实时推送生效，需要服务端支持从查询参数或子协议读取令牌，并放宽同源 Origin 校验。
- **必须同源部署**：Go 服务未提供 CORS 响应头，跨源直连会被浏览器拦截；开发环境依赖 Vite 代理，生产环境依赖反向代理（见上）。
- **冷启动全量扫描**：服务端游标只能升序翻页，刷新页面后会从头扫描历史。个人短信量级（万条内）开销很小，数据量更大时建议服务端支持倒序分页。
- **Element Plus 全量引入**：主包约 1.2 MB（gzip 390 KB）。控制台场景可接受；如需优化可改为按需引入。
- 撤销当前浏览器自身设备后会立即回到登录页，需要重新配对；服务端不会删除消息与历史记录。
