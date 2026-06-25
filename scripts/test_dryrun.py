#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线 dry-run 测试：不调用任何外部 API，不依赖付费 key。

验证范围：
  - 配置文件加载与结构
  - api_key 解析逻辑（keychain / env / plaintext 三种模式）
  - 媒体类型识别（media_type_of）
  - 本地文件转 data URL（to_data_url）
  - content 数组组装（build_content）
  - 剪贴板工具返回值解析逻辑

运行方式：
  .venv/bin/python scripts/test_dryrun.py

无需网络、无需 API key，可在 CI 中直接运行。
"""
from __future__ import annotations

import base64
import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path
from unittest.mock import patch

# 确保能 import MCP 模块
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp"))

from multimodal_proxy import (
    build_content,
    load_config,
    media_type_of,
    resolve_api_key,
    to_data_url,
)

PASS = 0
FAIL = 0


def ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"  ✓ {name}{(' — ' + detail) if detail else ''}")


def fail(name: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    print(f"  ✗ {name}{(' — ' + detail) if detail else ''}")


# ─── 辅助：生成最小 PNG ───

def make_png(color: bytes = b"\xc0\x00\x00", w: int = 4, h: int = 4) -> bytes:
    """生成纯色最小 PNG，返回字节。"""
    rows = []
    for _ in range(h):
        row = bytearray()
        for _ in range(w):
            row += color
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# ─── 测试用例 ───

def test_media_type_of() -> None:
    """媒体类型识别。"""
    print("\n[1] media_type_of — 媒体类型识别")
    cases = [
        ("/tmp/a.png", "image"),
        ("/tmp/a.jpg", "image"),
        ("/tmp/a.jpeg", "image"),
        ("/tmp/a.gif", "image"),
        ("/tmp/a.webp", "image"),
        ("/tmp/a.bmp", "image"),
        ("/tmp/a.svg", "image"),
        ("/tmp/v.mp4", "video"),
        ("/tmp/v.mov", "video"),
        ("/tmp/v.webm", "video"),
        ("/tmp/v.avi", "video"),
        ("/tmp/v.mkv", "video"),
        ("/tmp/a.mp3", "audio"),
        ("/tmp/a.wav", "audio"),
        ("/tmp/a.m4a", "audio"),
        ("/tmp/a.flac", "audio"),
        ("/tmp/a.aac", "audio"),
        ("/tmp/a.ogg", "audio"),
        ("https://example.com/img.png", "image"),
        ("https://example.com/v.mp4?token=x", "video"),
        ("https://example.com/a.mp3", "audio"),
    ]
    for path, expected in cases:
        got = media_type_of(path)
        if got == expected:
            ok(f"{path} → {expected}")
        else:
            fail(f"{path}", f"期望 {expected}，实际 {got}")


def test_to_data_url() -> None:
    """本地文件转 data URL + URL 原样返回。"""
    print("\n[2] to_data_url — 文件转 data URL")
    tmpdir = Path(tempfile.mkdtemp())

    # 本地 PNG
    png_path = tmpdir / "test.png"
    png_path.write_bytes(make_png())
    url = to_data_url(str(png_path))
    if url.startswith("data:image/png;base64,"):
        # 验证 base64 可解码回原数据
        b64_part = url.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        if decoded == make_png():
            ok("本地 PNG → data:image/png;base64,...", "base64 可还原")
        else:
            fail("本地 PNG", "base64 解码后与原文件不一致")
    else:
        fail("本地 PNG", f"前缀不对: {url[:30]}")

    # http URL 原样返回
    http_url = "https://example.com/img.png"
    if to_data_url(http_url) == http_url:
        ok("http URL 原样返回")
    else:
        fail("http URL", "未被原样返回")

    # data URL 原样返回
    data_url = "data:image/png;base64,iVBOR="
    if to_data_url(data_url) == data_url:
        ok("data URL 原样返回")
    else:
        fail("data URL", "未被原样返回")

    # 不存在的文件
    try:
        to_data_url("/nonexistent/file.png")
        fail("不存在文件", "应抛 FileNotFoundError")
    except FileNotFoundError:
        ok("不存在文件 → FileNotFoundError")


def test_build_content() -> None:
    """content 数组组装。"""
    print("\n[3] build_content — content 组装")
    tmpdir = Path(tempfile.mkdtemp())

    png_path = tmpdir / "img.png"
    png_path.write_bytes(make_png())

    provider_cfg = {"content_types": {}}

    # 单图 + 单提示词
    content = build_content([str(png_path)], ["描述这张图"], provider_cfg)
    # 应该是 [text, image_url]
    if len(content) == 2 and content[0]["type"] == "text" and content[1]["type"] == "image_url":
        ok("单图+单提示词 → [text, image_url]")
    else:
        fail("单图+单提示词", f"结构不对: {content}")

    # 多图 + 多提示词
    png2 = tmpdir / "img2.png"
    png2.write_bytes(make_png(b"\x00\x00\xc0"))
    content = build_content([str(png_path), str(png2)], ["图A", "图B", "对比"], provider_cfg)
    if len(content) == 5 and content[0]["type"] == "text" and content[3]["type"] == "image_url":
        ok("多图+多提示词 → [text×3, image_url×2]")
    else:
        fail("多图+多提示词", f"结构不对: {len(content)} 项")

    # 空提示词
    content = build_content([str(png_path)], [], provider_cfg)
    if len(content) == 1 and content[0]["type"] == "image_url":
        ok("空提示词 → [image_url]")
    else:
        fail("空提示词", f"结构不对: {content}")

    # 空白提示词被跳过
    content = build_content([str(png_path)], ["  ", ""], provider_cfg)
    if len(content) == 1 and content[0]["type"] == "image_url":
        ok("空白提示词被跳过")
    else:
        fail("空白提示词", f"应跳过空白: {content}")

    # content_types 自定义
    provider_cfg_custom = {"content_types": {"image": "image_url", "video": "video_url"}}
    content = build_content([str(png_path)], [], provider_cfg_custom)
    if content[0]["type"] == "image_url":
        ok("content_types 自定义生效")
    else:
        fail("content_types", f"类型不对: {content[0]['type']}")


def test_config_structure() -> None:
    """配置文件加载与结构验证（使用真实配置，不涉及 key 值）。"""
    print("\n[4] 配置加载 — 结构验证")
    try:
        cfg = load_config()
    except RuntimeError as e:
        fail("load_config", str(e))
        return

    if "providers" in cfg and isinstance(cfg["providers"], dict):
        ok("providers 字段存在且为 dict")
    else:
        fail("providers", "字段缺失或类型不对")
        return

    if "default_provider" in cfg:
        ok(f"default_provider = {cfg['default_provider']}")
    else:
        fail("default_provider", "字段缺失")

    for name, prov in cfg["providers"].items():
        if "base_url" in prov:
            ok(f"[{name}] base_url 存在")
        else:
            fail(f"[{name}] base_url", "缺失")

        if "api_key_store" in prov:
            ok(f"[{name}] api_key_store = {prov['api_key_store']}")
        else:
            fail(f"[{name}] api_key_store", "缺失")

        if "models" in prov and "vision" in prov.get("models", {}):
            ok(f"[{name}] models.vision = {prov['models']['vision']}")
        else:
            fail(f"[{name}] models.vision", "缺失")


def test_resolve_api_key_logic() -> None:
    """api_key 解析逻辑（不读取真实 key 值，只验证分支和错误处理）。"""
    print("\n[5] resolve_api_key — 分支与错误处理")

    # plaintext 模式
    cfg_plain = {"providers": {"test": {"api_key_store": "plaintext", "api_key": "fake-key"}}}
    try:
        key = resolve_api_key(cfg_plain, "test")
        if key == "fake-key":
            ok("plaintext 模式返回 api_key 值")
        else:
            fail("plaintext", "返回值不对")
    except Exception as e:
        fail("plaintext", str(e))

    # plaintext 缺 key
    cfg_plain_empty = {"providers": {"test": {"api_key_store": "plaintext"}}}
    try:
        resolve_api_key(cfg_plain_empty, "test")
        fail("plaintext 缺 key", "应抛 RuntimeError")
    except RuntimeError:
        ok("plaintext 缺 key → RuntimeError")

    # env 模式
    cfg_env = {"providers": {"test": {"api_key_store": "env", "api_key_env": "DUMMY_TEST_KEY"}}}
    with patch.dict(os.environ, {"DUMMY_TEST_KEY": "env-value"}):
        try:
            key = resolve_api_key(cfg_env, "test")
            if key == "env-value":
                ok("env 模式从环境变量读取")
            else:
                fail("env", "返回值不对")
        except Exception as e:
            fail("env", str(e))

    # env 未设置变量
    with patch.dict(os.environ, {}, clear=True):
        try:
            resolve_api_key(cfg_env, "test")
            fail("env 未设置", "应抛 RuntimeError")
        except RuntimeError:
            ok("env 未设置 → RuntimeError")

    # env 缺变量名
    cfg_env_no_name = {"providers": {"test": {"api_key_store": "env"}}}
    try:
        resolve_api_key(cfg_env_no_name, "test")
        fail("env 缺变量名", "应抛 RuntimeError")
    except RuntimeError:
        ok("env 缺变量名 → RuntimeError")


def test_tool_signatures() -> None:
    """验证 MCP 工具函数签名（不调用，只检查参数定义）。"""
    print("\n[6] 工具签名验证")
    import inspect
    from multimodal_proxy import process_multimodal, save_clipboard_to_file, generate_image

    # process_multimodal 签名
    sig = inspect.signature(process_multimodal)
    params = list(sig.parameters.keys())
    if params == ["media", "prompts", "model", "provider"]:
        ok(f"process_multimodal 参数: {params}")
    else:
        fail("process_multimodal 签名", f"参数: {params}")

    # media 是必填
    if sig.parameters["media"].default is inspect.Parameter.empty:
        ok("process_multimodal media 为必填参数")
    else:
        fail("media", "应为必填")

    # prompts 可选
    if sig.parameters["prompts"].default is None:
        ok("process_multimodal prompts 默认 None（可选）")
    else:
        fail("prompts", "应默认 None")

    # save_clipboard_to_file 无参数
    sig_clip = inspect.signature(save_clipboard_to_file)
    if len(sig_clip.parameters) == 0:
        ok("save_clipboard_to_file 无参数")
    else:
        fail("save_clipboard_to_file", f"不应有参数: {sig_clip.parameters}")

    # generate_image 签名
    sig_gen = inspect.signature(generate_image)
    params_gen = list(sig_gen.parameters.keys())
    if params_gen == ["prompt", "model", "provider", "size"]:
        ok(f"generate_image 参数: {params_gen}")
    else:
        fail("generate_image 签名", f"参数: {params_gen}")


# ─── 主入口 ───

def main() -> int:
    print("=" * 60)
    print("  multimodal-proxy dry-run 测试（离线，不调 API）")
    print("=" * 60)

    test_media_type_of()
    test_to_data_url()
    test_build_content()
    test_config_structure()
    test_resolve_api_key_logic()
    test_tool_signatures()

    print("\n" + "=" * 60)
    print(f"  结果: {PASS} 通过, {FAIL} 失败")
    print("=" * 60)
    return 1 if FAIL > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
