#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端测试：通过 MCP stdio 调用 process_multimodal 验证 doubao 图片分析。

key 从环境变量 ARK_API_KEY 读取（不打印 key）。
测试场景：多图对比（图A左红右蓝，图B左蓝右红）。
"""
import os, sys, subprocess, json, time, struct, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
KEY = os.environ.get("ARK_API_KEY", "")
BASE_URL = os.environ.get("ARK_BASE_URL", "https://api.openai.com/v1")
MODEL = os.environ.get("ARK_VISION_MODEL", "gpt-4o")

if not KEY:
    print("✗ 请设置环境变量 ARK_API_KEY"); sys.exit(1)

# 1. 配置（keychain 存 key）
print(f"→ 配置: provider=volcengine base_url={BASE_URL} model={MODEL}")
r = subprocess.run([PY, str(ROOT/"scripts/configure.py"),
    "--provider","volcengine","--base-url",BASE_URL,
    "--api-key-stdin","--vision-model",MODEL,
    "--keychain-account","volcengine"],
    input=KEY, capture_output=True, text=True)
print(r.stdout.strip()[-150:])
if r.returncode != 0:
    print("配置失败:", r.stderr[-200:]); sys.exit(1)

# 2. 生成两张测试图（图A左红右蓝，图B左蓝右红）
def make_png(left, right, w=120, h=60):
    rows=[]
    for _ in range(h):
        row=bytearray()
        for x in range(w): row += left if x<w//2 else right
        rows.append(bytes(row))
    raw=b''.join(b'\x00'+r for r in rows)
    def chunk(t,d):
        c=struct.pack('>I',len(d))+t+d
        return c+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')

img_a = '/tmp/mmp_test_a.png'
img_b = '/tmp/mmp_test_b.png'
Path(img_a).write_bytes(make_png(b'\xc0\x00\x00', b'\x00\x00\xc0'))
Path(img_b).write_bytes(make_png(b'\x00\x00\xc0', b'\xc0\x00\x00'))
print(f"  测试图: {img_a}(左红右蓝), {img_b}(左蓝右红)")

# 3. 通过 MCP stdio 调用 process_multimodal（多图对比）
print(f"\n→ 通过 MCP 调用 process_multimodal（多图对比）")
p = subprocess.Popen([PY, str(ROOT/"mcp"/"multimodal_proxy.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
for req in [
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"e2e","version":"1"}}},
    {"jsonrpc":"2.0","method":"notifications/initialized"},
    {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"process_multimodal","arguments":{
        "media":[img_a, img_b],
        "prompts":["这是图A","这是图B","对比这两张图的颜色布局差异"]
    }}},
]:
    p.stdin.write(json.dumps(req)+"\n"); p.stdin.flush(); time.sleep(0.5)

deadline = time.time() + 25
while time.time() < deadline:
    line = p.stdout.readline()
    if not line: time.sleep(0.5); continue
    try:
        d = json.loads(line.strip())
        if d.get("id")==2:
            res = d.get("result",{})
            if res.get("isError"):
                print("✗ 错误:", res.get("content",[{}])[0].get("text","")[:400])
                sys.exit(2)
            else:
                print("✓ 多图对比成功！返回:")
                print(res.get("content",[{}])[0].get("text","")[:500])
                sys.exit(0)
    except: pass
print("✗ 超时未收到响应"); sys.exit(3)
