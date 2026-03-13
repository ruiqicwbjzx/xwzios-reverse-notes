# 星云加速器 (nbiosapp) 逆向分析报告

> **工具**：IDA Pro + IDA-MCP + Python  
> **目标**：星云加速器 / nbiosapp（bundle ID: `com.locklayertech.nbiosapp`）  
> **分析日期**：2026-03-13  
> **作者**：xwzios  

---

## 一、目标描述

星云加速器是一款 iOS VPN 加速工具，包含试用限制和节点列表加密。

**分析目标**：
1. 绕过试用状态限制
2. 解密 API 响应获取节点列表

---

## 二、试用状态验证分析

### 2.1 结论：本地验证（内存 Patch）

通过 IDA 分析找到 `userStateCode` getter 函数（偏移 `0xAD8FC`），该函数返回用户当前状态码。

| 状态码 | 含义 |
|---|---|
| 其他值 | 试用/未激活 |
| `6` | 已激活/VIP |

### 2.2 破解方案

直接内存 Patch `userStateCode` getter，让它永远返回 `6`：

```asm
MOV X0, #6    ; 0xD28000C0
RET           ; 0xD65F03C0
```

**实现方式**：独立 dylib，不依赖 CydiaSubstrate，使用 `vm_protect` + `memcpy` 直接写内存。

### 2.3 关键偏移

| 函数 | 偏移 | 说明 |
|---|---|---|
| `userStateCode` getter | `0xAD8FC` | 用户状态码，patch 返回 6 |

---

## 三、API 响应解密分析

### 3.1 加密方式

API 响应体结构：
```json
{
  "code": 200,
  "msg": "<base64 编码的 RSA 加密密文>"
}
```

### 3.2 解密流程

```
msg (base64 字符串)
  → base64 解码 → 二进制密文
  → 按 256 字节分块
  → 每块 RSA 解密 (PKCS1v15，2048-bit 私钥)
  → 拼接所有明文块
  → UTF-8 解码 → JSON
```

### 3.3 密钥来源

从 App 二进制中提取到 RSA 私钥（硬编码在客户端中），2048-bit PKCS#8 格式。

**关键发现**：私钥直接内嵌在客户端，属于客户端解密模式（服务器用公钥加密，客户端用私钥解密），安全性较低。

### 3.4 解密结果

解密后获得完整节点列表，包含：

| 字段 | 示例 |
|---|---|
| `label` | 香港 通用 自动 |
| `region` | hk |
| `protocol` | hy2 (Hysteria2) |
| `server_name` | hk-vmiss-ex2.nebulacloud.win |
| `ip` | 38.207.180.130 |
| `portFrom/portTo` | 25001-30000 |

节点覆盖地区：香港、日本、新加坡、美国、台湾等。

---

## 四、破解代码

### 4.1 试用绕过 (bypass_trial.m)

独立 dylib，通过 `__attribute__((constructor))` 自动加载：

```objc
static const uint64_t kOff_userStateCode_getter = 0xAD8FC;

// ARM64 patch: MOV X0, #6; RET
uint32_t patch[2] = { 0xD28000C0, 0xD65F03C0 };
patch_memory(base + kOff_userStateCode_getter, patch, sizeof(patch));
```

技术特点：
- 不依赖 CydiaSubstrate / MSHookFunction
- 使用 `vm_protect` 修改内存权限后直接写入
- `sys_icache_invalidate` 刷新指令缓存

### 4.2 解密脚本 (星云加速器解密算法.py)

```python
def decrypt_msg(msg_b64: str) -> dict:
    ciphertext = base64.b64decode(msg_b64)
    plaintext_parts = []
    for i in range(0, len(ciphertext), 256):
        block = ciphertext[i : i + 256]
        decrypted = private_key.decrypt(block, padding.PKCS1v15())
        plaintext_parts.append(decrypted)
    return json.loads(b"".join(plaintext_parts).decode("utf-8"))
```

依赖：`cryptography` 库

---

## 五、安全评估

| 项目 | 评估 |
|---|---|
| 试用验证 | 纯本地状态码判断，无服务器校验 |
| API 加密 | RSA-2048 PKCS1v15，但私钥硬编码在客户端 |
| 节点保护 | 加密传输但客户端可解密，等同明文 |
| 协议 | Hysteria2 (hy2)，基于 QUIC |

---

*by xwzios*
