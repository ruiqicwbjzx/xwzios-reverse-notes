# Python IDE (app.pythonide) AI 功能破解分析报告

> **工具**：IDA Pro + IDA-MCP + Theos  
> **目标**：`Python IDE.app`（bundle ID: `app.pythonide`）  
> **分析日期**：2026-03-13  
> **作者**：xwzios  

---

## 一、目标描述

App 内置 AI 分析功能，免费使用 5 次后弹出以下提示：

> "AI 请求失败  
> 免费次数已用完，可购买调用包或配置自己的 API Key 获得更多使用。"

**分析目标**：判断次数限制是本地验证还是服务器验证，并实现破解。

---

## 二、IDA 静态分析

### 2.1 关键字符串定位

搜索字符串 `免费次数` 找到以下关键地址：

| 地址 | 字符串内容 |
|---|---|
| `0x10075d340` | `免费次数已用完，可购买调用包或配置自己的 API Key 获得更多使用。` |
| `0x10075e1b0` | `🎁 免费次数 · 剩余 %lld/5 次（共 5 次）` |
| `0x10075f331` | `keyFreeUsed` |
| `0x10075f340` | `keyPackageBalance` |

### 2.2 定位核心类 AIUsageManager

通过 `0x10075d340` 的交叉引用，找到核心类 `AIUsageManager`，包含以下关键方法：

| 函数 | 地址 | 作用 |
|---|---|---|
| `AIUsageManager.canMakeAICall()` | `0x10009c26c` | 判断是否允许 AI 调用 |
| `AIUsageManager.consumeOneCall()` | `0x10009c33c` | 消耗一次调用次数 |
| `AIUsageManager.freeCallsRemaining` getter | `0x10009c01c` | 读取剩余免费次数 |
| `AIUsageManager.packageCallsBalance` getter | `0x10009c030` | 读取调用包余额 |
| `AIUsageManager.freeCallsUsed` getter | `0x10009ce94` | 读取已用次数 |
| `AIUsageManager.readIntFromKeychain(key:)` | `0x10009d458` | 从 Keychain 读取整数 |
| `AIUsageManager.init()` | `0x10009c9b8` | 初始化，从 Keychain 加载数据 |
| `KeychainHelper.get(key:)` | `0x1001bc818` | Keychain 读取辅助 |
| `KeychainHelper.set(key:value:)` | `0x1001bc76c` | Keychain 写入辅助 |

---

## 三、验证逻辑分析

### 3.1 结论：100% 本地验证

反编译 `canMakeAICall()` 和 `consumeOneCall()` 后确认：**无任何网络请求，次数计数完全存储在本地 iOS Keychain 中。**

### 3.2 Keychain 存储键名

| Keychain Key | 含义 |
|---|---|
| `keyFreeUsed` | 已使用的免费次数（上限 5） |
| `keyPackageBalance` | 购买的调用包余额 |

### 3.3 canMakeAICall 逻辑

```
freeCallsRemaining > 0  →  return true
         ↓ 否
packageCallsBalance > 0  →  return true
         ↓ 否
return false  →  弹出"免费次数已用完"
```

### 3.4 consumeOneCall 逻辑

```
readIntFromKeychain("keyFreeUsed") → freeCallsUsed
freeCallsUsed += 1
KeychainHelper.set("keyFreeUsed", freeCallsUsed)
freeCallsRemaining = max(0, 5 - freeCallsUsed)
Published 属性更新 → UI 刷新
```

### 3.5 初始化逻辑（AIUsageManager.init）

```
readIntFromKeychain("keyFreeUsed") → v6（已用次数）
freeCallsRemaining = max(0, 5 - v6)
Published.init(freeCallsRemaining)  ← @Published 属性初始化
                                       UI 通过此属性更新
readIntFromKeychain("keyPackageBalance") → packageBalance
Published.init(packageBalance)
```

---

## 四、Hook 方案设计

### 4.1 v1 方案（失败原因分析）

最初使用 `dlsym(RTLD_DEFAULT, symbol)` 查找 Swift 符号，Hook 未生效。

**失败原因：**
1. Swift 内部函数未导出到动态符号表，`dlsym` 返回 NULL
2. UI 直接监听 `@Published` 属性（在 init 时由 Keychain 初始化），不走 getter 函数
3. Swift 调用约定：`self` 通过 `x20` 寄存器传递，普通 C 函数无法正确拦截

### 4.2 v2 方案（最终方案）

**三层 Hook 策略：**

| Hook 目标 | 地址偏移 | 替换逻辑 | 效果 |
|---|---|---|---|
| `readIntFromKeychain` | `0x10009d458` | 返回 `Optional<Int>.some(0)` | init 计算 `freeCallsRemaining = 5`，UI 显示 5/5 |
| `canMakeAICall` | `0x10009c26c` | 返回 `true`（x0=1） | AI 调用始终放行 |
| `consumeOneCall` | `0x10009c33c` | no-op（直接 ret） | 次数永不递减 |

**关键技术点：**

1. **偏移量定位**：使用 `_dyld_get_image_header` 获取运行时基址 + IDA 偏移，绕过符号导出限制
2. **naked asm**：使用 `__attribute__((naked))` + 内联汇编编写 hook 桩，规避 Swift x20 调用约定
3. **Optional\<Int\> 返回约定**：`w1=0` 表示 `.some(x0)`，`w1=1` 表示 `.none`

---

## 五、Swift Optional 返回约定（ARM64）

从 init 反编译代码分析得出：

```c
v2 = readIntFromKeychain(...)  // x0 = 值
// v3 = w1（隐式第二返回值）
if ((v3 & 1) != 0) {
    // w1=1 → .none，Keychain 无此 key，回退 NSUserDefaults
    v6 = NSUserDefaults.integerForKey(...)
} else {
    // w1=0 → .some(v2)，使用 Keychain 值
    v6 = v2;
}
```

结论：`w1=0 + x0=value → .some(value)`，`w1=1 → .none`

---

## 六、Theos 插件代码

### 6.1 项目结构

```
PythonIDEAIBypass/
├── Tweak.x                    ← 核心 Hook（混淆版）
├── Makefile
├── control
└── PythonIDEAIBypass.plist    ← 注入过滤（仅 app.pythonide）
```

### 6.2 Makefile

```makefile
ARCHS = arm64 arm64e
TARGET = iphone:clang:latest:14.0
TWEAK_NAME = PythonIDEAIBypass
$(TWEAK_NAME)_FILES = Tweak.x
$(TWEAK_NAME)_CFLAGS = -fobjc-arc
$(TWEAK_NAME)_FRAMEWORKS = Foundation
```

### 6.3 核心 Hook 代码（精简版）

```objc
// IDA base 0x100000000
#define _C1 0x10009c26cULL   // canMakeAICall
#define _C2 0x10009c33cULL   // consumeOneCall
#define _C3 0x10009d458ULL   // readIntFromKeychain

// 获取主二进制 ASLR 基址
static uintptr_t _base(void) {
    for (uint32_t i = 0; i < _dyld_image_count(); i++) {
        const struct mach_header *h = _dyld_get_image_header(i);
        if (h && h->filetype == MH_EXECUTE) return (uintptr_t)h;
    }
    return 0;
}

// canMakeAICall → 始终 true
__attribute__((naked)) static void _stub_can(void) {
    __asm__ volatile("mov x0, #1\nret\n");
}

// consumeOneCall → no-op
__attribute__((naked)) static void _stub_consume(void) {
    __asm__ volatile("ret\n");
}

// readIntFromKeychain → Optional<Int>.some(0)
__attribute__((naked)) static void _stub_keychain(void) {
    __asm__ volatile("mov x0, #0\nmov w1, #0\nret\n");
}
```

### 6.4 混淆措施

| 混淆技术 | 实现方式 |
|---|---|
| 字符串 XOR 加密 | bundle ID、首次启动 key 使用 XOR(0x5A) 加密，二进制无明文 |
| 函数名混淆 | 所有内部函数使用短名 `_stub_*`、`_patch`、`_base` |
| 符号隐藏 | `__attribute__((visibility("hidden")))` |
| naked asm | Hook 桩纯汇编，无 C 函数符号 |
| 栈分配解码 | XOR 解码使用 `alloca`，不产生堆对象 |

### 6.5 首次注入弹窗

- 使用 NSUserDefaults 记录首次标记（key 经 XOR 加密）
- 启动 1.8 秒后弹出 UIAlertController
- 标题：`xwzios破解`
- 内容：`Python IDE · AI 无限制 \n by xwzios`
- **仅首次弹出**

---

## 七、编译与安装

```bash
cd ~/Desktop/Payload/PythonIDEAIBypass

# 编译
make package

# 直连设备安装（SSH）
make install

# 或手动传到设备用 Filza / Sileo 安装最新 deb
# packages/com.bypass.pythonide.ai_1.0.3-1+debug_iphoneos-arm64.deb
```

---

## 八、效果验证

安装后重新启动 Python IDE：

- ✅ AI 助手设置页显示 **剩余 5/5 次**（readIntFromKeychain 返回 0）
- ✅ 使用 AI 功能不再弹出"免费次数已用完"
- ✅ 次数始终保持不变（consumeOneCall no-op）
- ✅ 首次启动弹出 xwzios 水印弹窗

---

## 九、关键符号表

| Swift 符号（Mangled） | 地址 | 说明 |
|---|---|---|
| `_$s10Python_IDE14AIUsageManagerC13canMakeAICallSbyF` | `0x10009c26c` | AI 调用门控 |
| `_$s10Python_IDE14AIUsageManagerC14consumeOneCallyyF` | `0x10009c33c` | 次数消耗 |
| `_$s10Python_IDE14AIUsageManagerC18freeCallsRemainingSivg` | `0x10009c01c` | 剩余次数 getter |
| `_$s10Python_IDE14AIUsageManagerC19packageCallsBalanceSivg` | `0x10009c030` | 调用包余额 getter |
| `_$s10Python_IDE14AIUsageManagerC13freeCallsUsedSivg` | `0x10009ce94` | 已用次数 getter |
| `_$s10Python_IDE14AIUsageManagerC19readIntFromKeychain...FZTf4nd_n` | `0x10009d458` | Keychain 读取（specialized） |
| `_$s10Python_IDE14AIUsageManagerCACyc...Llfc` | `0x10009c9b8` | 初始化方法 |
| `_$s10Python_IDE14KeychainHelperO3get3keySSSgSS_tFZTf4nd_n` | `0x1001bc818` | Keychain get |
| `_$s10Python_IDE14KeychainHelperO3set3key5valueySS_SStFZ` | `0x1001bc76c` | Keychain set |

---

*by xwzios*
