#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# multimodal-proxy demo：截屏→分析 全流程展示
# 需先运行 bash scripts/install.sh 完成配置
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$PLUGIN_ROOT/.venv/bin/python"

echo "═══════════════════════════════════════════════════════════"
echo "  multimodal-proxy demo — 多图对比"
echo "═══════════════════════════════════════════════════════════"
echo ""

# 生成两张测试图（图A左红右蓝，图B左蓝右红）
echo "→ 生成测试图..."
IMG_A="/tmp/mmp_demo_a.png"
IMG_B="/tmp/mmp_demo_b.png"
"$PY" -c "
import struct, zlib
from pathlib import Path
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
Path('$IMG_A').write_bytes(make_png(b'\xc0\x00\x00', b'\x00\x00\xc0'))
Path('$IMG_B').write_bytes(make_png(b'\x00\x00\xc0', b'\xc0\x00\x00'))
"
echo "  图A: $IMG_A (左红右蓝)"
echo "  图B: $IMG_B (左蓝右红)"
echo ""

# 调用 process_multimodal（直接调用，绕过 MCP stdio）
echo "→ 调用 process_multimodal 分析..."
echo ""
"$PY" -c "
import sys
sys.path.insert(0, '$PLUGIN_ROOT/mcp')
from multimodal_proxy import process_multimodal
result = process_multimodal(
    media=['$IMG_A', '$IMG_B'],
    prompts=['这是图A', '这是图B', '对比这两张图的颜色布局差异']
)
print('分析结果:')
print(result)
"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✓ demo 完成"
echo "═══════════════════════════════════════════════════════════"
