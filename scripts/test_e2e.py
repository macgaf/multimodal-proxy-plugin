#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端测试：配置 keychain + 调用 understand_image 验证 doubao 图片分析成功。

key 从环境变量 ARK_API_KEY 读取，不打印 key 本身。
"""
import os, sys, subprocess, json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
KEY = os.environ.get("ARK_API_KEY", "")
BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
MODEL = os.environ.get("ARK_VISION_MODEL", "doubao-seed-2.0-pro")
IMG = "/tmp/multimodal_proxy_test.png"


def ensure_test_image():
    """若测试图片不存在则生成一张红蓝双色测试图（纯 Python，无第三方依赖）。"""
    if Path(IMG).exists():
        return
    import struct, zlib
    w, h = 240, 80
    rows = []
    for _ in range(h):
        row = bytearray()
        for x in range(w):
            if x < 110:
                row += b"\xc0\x00\x00"      # 红色
            elif x < 130:
                row += b"\xff\xff\xff"    # 白色分隔
            else:
                row += b"\x00\x00\xc0"      # 蓝色
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        c += struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        return c

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw)
    Path(IMG).write_bytes(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    print(f"  测试图片已生成: {IMG}")

ensure_test_image()

if not KEY:
    print("✗ 请设置环境变量 ARK_API_KEY"); sys.exit(1)

# 1. 配置（keychain 存 key）
print(f"→ 配置 provider=volcengine base_url={BASE_URL} model={MODEL}")
r = subprocess.run([PY, str(ROOT/"scripts/configure.py"),
    "--provider","volcengine","--base-url",BASE_URL,
    "--api-key",KEY,"--vision-model",MODEL,
    "--keychain","--keychain-account","volcengine","--set-default"],
    capture_output=True, text=True)
print(r.stdout.strip()[-200:])
if r.returncode != 0:
    print("配置失败:", r.stderr[-300:]); sys.exit(1)

# 验证配置文件无明文 key
cfg = json.load(open(Path.home()/".config"/"multimodal-proxy"/"config.json"))
prov = cfg["providers"]["volcengine"]
print(f"  api_key_store={prov.get('api_key_store')}  明文key存在={'api_key' in prov}")

# 2. 通过 MCP stdio 调用 understand_image（模拟 Codex 主模型调用工具）
print(f"\n→ 通过 MCP stdio 调用 understand_image（图片={IMG}）")
p = subprocess.Popen([PY, str(ROOT/"mcp"/"multimodal_proxy.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
for req in [
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"e2e","version":"1"}}},
    {"jsonrpc":"2.0","method":"notifications/initialized"},
    {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"understand_image","arguments":{"image":IMG,"prompt":"请详细描述这张图片的内容和颜色"}}},
]:
    p.stdin.write(json.dumps(req)+"\n"); p.stdin.flush(); time.sleep(0.5)
time.sleep(8); p.terminate()
out = p.stdout.read()
for line in out.splitlines():
    try:
        d = json.loads(line)
        if d.get("id") == 2:
            res = d.get("result", {})
            if res.get("isError"):
                print("✗ 工具返回错误:")
                print(res.get("content",[{}])[0].get("text","")[:500])
                sys.exit(2)
            else:
                txt = res.get("content",[{}])[0].get("text","")
                print("✓ doubao 图片分析成功！返回:")
                print(txt[:600])
                sys.exit(0)
    except: pass
print("✗ 未收到工具响应"); sys.exit(3)
