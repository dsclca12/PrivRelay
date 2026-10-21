/**
 * 浏览器端设备配对：ECDSA P-256 + SHA-256，签名内容与 server/main.go 校验逻辑严格一致。
 * 摘要 = SHA256(device_id + "\n" + base64(spki) + "\n" + nonce + "\n" + pairing_code)
 */
import type { RegisterRequest } from '../api/types'
import { uuid } from './uuid'

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary)
}

export interface PairingInput {
  pairingCode: string
  deviceName: string
}

export async function buildPairingRequest(input: PairingInput): Promise<RegisterRequest> {
  const code = input.pairingCode.trim()
  const deviceId = uuid()
  const nonce = toBase64(crypto.getRandomValues(new Uint8Array(32)))

  const keyPair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, [
    'sign',
    'verify',
  ])
  const publicKey = toBase64(await crypto.subtle.exportKey('spki', keyPair.publicKey))

  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(`${deviceId}\n${publicKey}\n${nonce}\n${code}`),
  )
  // WebCrypto 的 ECDSA 签名即 ASN.1 DER，与 Go ecdsa.VerifyASN1 兼容
  const signature = toBase64(
    await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, keyPair.privateKey, digest),
  )

  return {
    device_id: deviceId,
    name: input.deviceName.trim() || 'Web 控制台',
    public_key: publicKey,
    nonce,
    pairing_code: code,
    signature,
  }
}
