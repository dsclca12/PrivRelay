/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 构建期 API 基址，留空表示同源（开发环境经 Vite 代理） */
  readonly VITE_API_BASE?: string
  /** 设为 "1" 启用内置演示数据，无需后端 */
  readonly VITE_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
