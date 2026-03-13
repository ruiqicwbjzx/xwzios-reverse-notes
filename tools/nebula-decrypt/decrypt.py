#!/usr/bin/env python3
"""
nbiosapp 响应解密脚本
解密流程：msg(base64) → base64解码 → 按256字节分块RSA解密(PKCS1v15) → 拼接明文 → JSON
"""

import base64
import json
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDJtnj1AQKua3K8
Hnvqi0xE0zpFRMLCeDRFYVXL9DSpz19Im3VZnd+qbvlU8Ld0u5lEfdv9yLsQ31kL
lbE7Y/D85VJFdSBIAy47IAVrgdyQT/nHDUVZD+RIRMtlxLR5Rl+n5jwCqOgpaNbC
zdpiPd+gZY4VxIqwM+61MW3AuUGcW+3tGV8L9k+iUkesQacqpw138WcKqH1slFvx
AJHIiHW0LPceNCwudKR3SktfpGSWb9KyTKVsHQg6JdFHN4g7UVskXi036Tj5SB2l
za+CYqq/2HCa5MFHzTjScPpLqZVBBVU6eZPawTNp1c+x9MGe5gd7WI2aL5vaDUfi
tdbhdM7dAgMBAAECggEAXXcGnwgD1QwGkvJRGsHG6lExu+z7jZ6jIc7TMXkLee+T
yBH4kzja7Z8UOu57I0TV5O2opPSA8XV8TijjgZBylswvje2Ssqt+nXjd6g23RMs6
Aqi8jGMXtQDjellmApfANQ0ym0zmnmFsucEmwsTGvQyxhJaYaML3hc/MejOdGjSP
7aPQL5px89o2iX9kM6SAHpQF9MQqcwwwipQcnM3LlwfV7NloweFR1U1eVmjT+lnL
/l1AJLF9prn5vjM2tjAmJsQMfShBddV8xs60kCNsXchC2+rx8r8Hl8xFe/eNFog1
jjA160uxkrmLeNIKKt+PonNYpvU8l2EZ3qPvdX1dpQKBgQDn0MYzhUdriJPzJv8j
V7BBbmL3UYGWXPfgXlE00C93Z9x1M2XieZo3FSa2Wrl9TZUylfOWl3Gf8e4jPki3
PMoSZDuMSUjEiwqfofIyg2R45U9IHI4gjWBj6kbC47rOVhWJDTo4adTVQ3tQA+EY
bKSw2HMjBCy7sabVIeJr0z7+hwKBgQDewbpIBEVh4G79f3xZQns2VUZ4wPc6W6ed
MdED0kglgAFBaXVYGlGKQGZNQTeqZm//T8l0HJc4+E+M2iVGt/otM4sGsP7mz5WO
tFKhFCLR2UhmfwOzeJ5/48YfSyj+3B9RYQlEohVFsLWCc1BgFx7lkgCPjMOk+yQZ
tzEYAYhcewKBgQCMFgnwUHZccWiW49YC0Zbds4ty0XpyFzRkDhscw0Ir8kOzP6Au
QDYFW27Ne/3jzuJ+c0eElXhAo7645Yaj1MR4YMHrgM3MmAmPdhoalHQ+6rQCa98n
pMe/GXAxjdTxo+vXqnqoZKwNRH5cWDvKury7cdICMx+lPTIIUjW12y6SOQKBgFcP
hEzNToi4fOiawPDp6NoNbiOX14h5dgMcC0LhFs2BP/xeyTwL3T6ZeOJM0QLKUo+I
kYXN/tSHSCAWymbfVOoBsR6GYrm2/A7wLzNBeXJm58MXdUzZoaj+TtrAN1+UjLDz
qfmnF4VLUUWQ6CMGJk83RvzT2UtL1IowbQGi57atAoGAcgllp4LbriEk//3Iu4Yq
DyJrqn37mOfMXT8s7aeZB25NLgif+FTBlNwSBX0WvUd7WScGAfJKl+kVC78gb3g3
r0TkVVdDVgVeDboyH1+c+HovWHDtWvEWZDuLokRDNf5IvG7SICAB4LcJUuzagB1k
TUgqnta2UscU5yHLGTZXLOw=
-----END PRIVATE KEY-----"""

RSA_BLOCK_SIZE = 256

private_key = serialization.load_pem_private_key(PRIVATE_KEY_PEM.encode(), password=None)


def decrypt_msg(msg_b64: str) -> dict:
    """解密响应 msg 字段，返回解密后的 JSON 对象"""
    ciphertext = base64.b64decode(msg_b64)

    if len(ciphertext) % RSA_BLOCK_SIZE != 0:
        raise ValueError(f"密文长度 {len(ciphertext)} 不是 {RSA_BLOCK_SIZE} 的整数倍")

    plaintext_parts = []
    for i in range(0, len(ciphertext), RSA_BLOCK_SIZE):
        block = ciphertext[i : i + RSA_BLOCK_SIZE]
        decrypted = private_key.decrypt(block, padding.PKCS1v15())
        plaintext_parts.append(decrypted)

    plaintext = b"".join(plaintext_parts)
    return json.loads(plaintext.decode("utf-8"))


def decrypt_response(response_body: str | dict) -> dict:
    """
    解密完整的 HTTP 响应体
    传入原始 JSON 字符串或已解析的 dict
    """
    if isinstance(response_body, str):
        data = json.loads(response_body)
    else:
        data = response_body

    msg = data.get("msg")
    if not msg or not isinstance(msg, str):
        print("[!] msg 字段不是字符串，无需解密，直接返回")
        return data

    decrypted = decrypt_msg(msg)
    print(f"[+] 解密成功，明文 JSON keys: {list(decrypted.keys())}")
    return decrypted


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        filepath = sys.argv[1]
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    else:
        print("请粘贴响应 JSON（输入后按 Ctrl+D 结束）：")
        raw = sys.stdin.read()

    if not raw.strip():
        print("[!] 输入为空")
        sys.exit(1)

    result = decrypt_response(raw.strip())
    print("\n===== 解密结果 =====")
    print(json.dumps(result, indent=2, ensure_ascii=False))
