#!/usr/bin/env python3
"""
xwzios 逆向分析报告 → Telegram 群组自动上传工具

用法:
    python3 upload.py /path/to/report.md
    python3 upload.py /path/to/report.md --silent    # 不发摘要，只发文件
    python3 upload.py --setup                         # 交互式配置
    python3 upload.py --get-chat-id                   # 获取群组 Chat ID
"""

import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

# ─────────────────────────────────────────────
# 代理支持：自动检测或手动配置
# ─────────────────────────────────────────────
def install_proxy():
    """安装代理到 urllib，支持从 config 或环境变量读取"""
    proxy_url = None

    # 1. 从 config.json 读取
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        proxy_url = cfg.get("proxy", "")

    # 2. 从环境变量读取
    if not proxy_url:
        proxy_url = (os.environ.get("HTTPS_PROXY") or
                     os.environ.get("https_proxy") or
                     os.environ.get("ALL_PROXY") or
                     os.environ.get("all_proxy") or "")

    if proxy_url:
        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url
        })
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)
        return proxy_url
    return None


# ─────────────────────────────────────────────
# 配置管理
# ─────────────────────────────────────────────
def load_config():
    if not CONFIG_PATH.exists():
        print("❌ 配置文件不存在，请先运行: python3 upload.py --setup")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    token = cfg.get("bot_token", "")
    chat_id = cfg.get("chat_id", "")
    if not token or "填写" in token:
        print("❌ 未配置 bot_token，请先运行: python3 upload.py --setup")
        sys.exit(1)
    if not chat_id or "填写" in chat_id:
        print("❌ 未配置 chat_id，请先运行: python3 upload.py --setup")
        sys.exit(1)
    return token, str(chat_id)


def setup():
    print("=" * 50)
    print("  xwzios TG 上传工具 - 配置向导")
    print("=" * 50)

    # 代理配置
    print()
    print("[代理配置] Telegram API 在国内需代理")
    print("  格式: http://127.0.0.1:7890 或 socks5h://127.0.0.1:7891")
    print("  留空则从环境变量 HTTPS_PROXY 读取")
    proxy = input("代理地址 (留空跳过): ").strip()

    # Bot Token
    print()
    print("[步骤 1] 打开 Telegram → @BotFather → /newbot")
    token = input("请粘贴 Bot Token: ").strip()

    # 保存（先存 token 和 proxy，后面获取 chat_id）
    cfg = {"bot_token": token, "chat_id": "", "proxy": proxy}
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

    if proxy:
        install_proxy()

    # 验证 token
    print("\n📡 验证 Token...")
    try:
        resp = api_get(token, "getMe")
        bot_name = resp["result"]["username"]
        print(f"✅ Bot 验证成功: @{bot_name}")
    except Exception as e:
        print(f"❌ Token 验证失败: {e}")
        print("   请检查 Token 是否正确，代理是否可用")
        return

    # 获取 Chat ID
    print()
    print(f"[步骤 2] 把 @{bot_name} 拉进你的群组，然后在群里发一条消息")
    input("完成后按回车继续...")

    chat_id = fetch_chat_id(token)
    if chat_id:
        cfg["chat_id"] = str(chat_id)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        print(f"✅ Chat ID: {chat_id}")

        print("\n📤 发送测试消息...")
        try:
            send_message(token, str(chat_id), "✅ xwzios 逆向报告上传机器人已连接！")
            print("✅ 配置完成！测试消息已发送到群组。")
        except Exception as e:
            print(f"⚠️  测试消息失败: {e}")
    else:
        print("❌ 未能获取 Chat ID，请手动填写到 config.json 的 chat_id 字段")


def fetch_chat_id(token):
    """从 getUpdates 中自动提取群组 chat_id"""
    try:
        resp = api_get(token, "getUpdates")
        results = resp.get("result", [])
        groups = {}
        for item in results:
            msg = item.get("message") or item.get("my_chat_member", {}).get("chat")
            if not msg:
                continue
            chat = msg.get("chat") or msg
            chat_type = chat.get("type", "")
            if chat_type in ("group", "supergroup", "channel"):
                cid = chat["id"]
                title = chat.get("title", f"ID:{cid}")
                groups[cid] = title

        if not groups:
            print("⚠️  未找到群组消息，请确保：")
            print("    1. Bot 已加入群组")
            print("    2. 在群里发了一条消息")
            print("    可以手动获取: python3 upload.py --get-chat-id")
            return None

        if len(groups) == 1:
            cid = list(groups.keys())[0]
            print(f"  找到群组: {groups[cid]} ({cid})")
            return cid

        print("  找到多个群组:")
        items = list(groups.items())
        for i, (cid, title) in enumerate(items):
            print(f"    [{i+1}] {title} ({cid})")
        choice = input("请选择序号: ").strip()
        idx = int(choice) - 1
        return items[idx][0]

    except Exception as e:
        print(f"⚠️  获取更新失败: {e}")
        return None


# ─────────────────────────────────────────────
# Telegram API（纯标准库 + 代理支持）
# ─────────────────────────────────────────────
API = "https://api.telegram.org/bot{}/{}"


def api_get(token, method):
    url = API.format(token, method)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def send_message(token, chat_id, text, parse_mode="Markdown"):
    url = API.format(token, "sendMessage")
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    if not resp.get("ok"):
        raise RuntimeError(resp.get("description", "Unknown error"))
    return resp


def send_document(token, chat_id, filepath, caption=""):
    url = API.format(token, "sendDocument")
    boundary = "----xwziosBoundary9527"
    filename = os.path.basename(filepath)

    with open(filepath, "rb") as f:
        file_data = f.read()

    body = bytearray()
    for name, value in [("chat_id", chat_id), ("parse_mode", "Markdown")]:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()

    if caption:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="caption"\r\n\r\n'.encode()
        body += f"{caption}\r\n".encode()

    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode()
    body += f"Content-Type: application/octet-stream\r\n\r\n".encode()
    body += file_data
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(url, data=bytes(body), headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read())
    if not resp.get("ok"):
        raise RuntimeError(resp.get("description", "Unknown error"))
    return resp


# ─────────────────────────────────────────────
# 从 MD 提取摘要
# ─────────────────────────────────────────────
def extract_summary(md_text):
    lines = md_text.strip().split("\n")

    title = ""
    for l in lines:
        if l.startswith("# "):
            title = l.lstrip("# ").strip()
            break

    conclusion = ""
    for l in lines:
        if "结论" in l or "本地验证" in l or "服务器验证" in l:
            conclusion = l.strip().lstrip("#").strip()
            break

    hooks = []
    in_table = False
    for l in lines:
        if "Hook 目标" in l or "Hook 策略" in l:
            in_table = True
            continue
        if in_table and l.startswith("|") and "---" not in l:
            cols = [c.strip() for c in l.split("|") if c.strip()]
            if len(cols) >= 2:
                hooks.append(f"• `{cols[0]}` → {cols[-1]}")
        elif in_table and not l.startswith("|"):
            in_table = False

    summary = f"📱 *{title}*\n"
    if conclusion:
        summary += f"\n🔍 {conclusion}\n"
    if hooks:
        summary += "\n🪝 *Hook 策略:*\n" + "\n".join(hooks[:5]) + "\n"
    summary += "\n_by xwzios_"
    return summary


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    install_proxy()

    if sys.argv[1] == "--setup":
        setup()
        return

    if sys.argv[1] == "--get-chat-id":
        token, _ = load_config()
        cid = fetch_chat_id(token)
        if cid:
            print(f"\n群组 Chat ID: {cid}")
            print("已自动更新到 config.json")
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            cfg["chat_id"] = str(cid)
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        return

    md_path = sys.argv[1]
    silent = "--silent" in sys.argv

    if not os.path.isfile(md_path):
        print(f"❌ 文件不存在: {md_path}")
        sys.exit(1)

    token, chat_id = load_config()

    with open(md_path, encoding="utf-8") as f:
        md_text = f.read()

    filename = os.path.basename(md_path)
    print(f"📤 上传 {filename} → Telegram 群组...")

    if not silent:
        try:
            summary = extract_summary(md_text)
            send_message(token, chat_id, summary)
            print("✅ 摘要消息已发送")
        except Exception as e:
            print(f"⚠️  摘要 Markdown 失败，改用纯文本: {e}")
            try:
                send_message(token, chat_id, extract_summary(md_text), parse_mode="")
                print("✅ 摘要消息已发送（纯文本）")
            except Exception as e2:
                print(f"⚠️  摘要发送失败: {e2}")

    try:
        send_document(token, chat_id, md_path,
                      caption=f"📋 逆向分析报告 - {filename}")
        print(f"✅ 文件 {filename} 已上传到群组")
    except Exception as e:
        print(f"❌ 文件上传失败: {e}")
        sys.exit(1)

    print("🎉 完成!")


if __name__ == "__main__":
    main()
