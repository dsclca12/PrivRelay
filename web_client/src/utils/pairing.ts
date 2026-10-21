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

  const payload = new TextEncoder().encode(`${deviceId}\n${publicKey}\n${nonce}\n${code}`)
  // WebCrypto hashes the payload itself and returns IEEE P1363 r || s.
  // Go VerifyASN1 expects the two unsigned integers in an ASN.1 sequence.
  const raw = new Uint8Array(await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' }, keyPair.privateKey, payload,
  ))
  function integer(bytes: Uint8Array): number[] {
    let start = 0
    while (start < bytes.length - 1 && bytes[start] === 0) start++
    const value = Array.from(bytes.slice(start))
    if (value[0]! & 0x80) value.unshift(0)
    return [0x02, value.length, ...value]
  }
  const values = [...integer(raw.slice(0, 32)), ...integer(raw.slice(32))]
  const signature = toBase64(new Uint8Array([0x30, values.length, ...values]).buffer)

  return {
    device_id: deviceId,
    name: input.deviceName.trim() || 'Web 控制台',
    public_key: publicKey,
    nonce,
    pairing_code: code,
    signature,
  }
}
