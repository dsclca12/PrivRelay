const AAD = new TextEncoder().encode('PrivRelay-E2EE-v1')
let cachedKey: Promise<CryptoKey> | null = null
let generation = 0
export function vaultGeneration(): number { return generation }

export interface VaultParams { version: number; kdf: string; iterations: number; salt: string }

export function setVaultCredentials(passphrase: string, params: VaultParams): void {
  const normalized = passphrase.trim()
  if (normalized.length < 12 || [...normalized].some((c) => c.charCodeAt(0) < 33 || c.charCodeAt(0) > 126)) {
    throw new Error('端到端加密口令至少 12 个字符，且只能包含可见 ASCII 字符')
  }
  if (params.version !== 1 || params.kdf !== 'PBKDF2-SHA256' || params.iterations !== 600000 || fromBase64Url(params.salt).length !== 16) {
    throw new Error('服务器加密参数不受支持')
  }
  generation++
  const material = crypto.subtle.importKey('raw', new TextEncoder().encode(normalized), 'PBKDF2', false, ['deriveKey'])
  cachedKey = material.then(key => crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt: fromBase64Url(params.salt), iterations: params.iterations },
    key,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  ))
}

export function clearVaultCredentials(): void {
  generation++
  cachedKey = null
}

export function hasVaultCredentials(): boolean { return cachedKey !== null }

function fromBase64Url(value: string): Uint8Array {
  const base64 = value.replaceAll('-', '+').replaceAll('_', '/')
  const binary = atob(base64 + '='.repeat((4 - base64.length % 4) % 4))
  return Uint8Array.from(binary, (c) => c.charCodeAt(0))
}

function toBase64Url(value: Uint8Array): string {
  let binary = ''
  for (const byte of value) binary += String.fromCharCode(byte)
  return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

function key(): Promise<CryptoKey> {
  if (cachedKey) return cachedKey
  throw new Error('请重新输入端到端加密口令')
}

export async function encryptVault(plain: string): Promise<string> {
  const nonce = crypto.getRandomValues(new Uint8Array(12))
  const sealed = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce, additionalData: AAD, tagLength: 128 }, await key(), new TextEncoder().encode(plain)))
  const envelope = new Uint8Array(1 + nonce.length + sealed.length)
  envelope[0] = 1
  envelope.set(nonce, 1)
  envelope.set(sealed, 13)
  return toBase64Url(envelope)
}

export async function decryptVault(ciphertext: string): Promise<string> {
  const envelope = fromBase64Url(ciphertext)
  if (envelope.length < 29 || envelope[0] !== 1) throw new Error('加密记录格式无效')
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: envelope.slice(1, 13), additionalData: AAD, tagLength: 128 },
    await key(),
    envelope.slice(13),
  )
  return new TextDecoder().decode(plain)
}
