#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multimodal-proxy MCP server

通用多模态代理：通过火山引擎 Coding Plan API 将多模态任务外包给支持视觉的模型
（如 doubao-seed-2.0-pro）。专供主模型为纯文本模型（glm-5.2/deepseek-v4 等）时使用。

核心设计：单个通用工具 process_multimodal，接收任意数量的图片/视频/音频 + 提示词，
按顺序组装成多模态 content，交给配置好的模型处理。

已验证的模型能力（doubao-seed-2.0-pro, Coding Plan）：
  - 图片 image_url      ✅ 支持（多图对比）
  - 视频 video_url      ✅ 类型被接受（需可访问 URL）
  - 音频 input_audio    ❌ 该模型不支持（需换专用模型）

配置文件：~/.config/multimodal-proxy/config.json
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from openai import OpenAI

CONFIG_DIR = Path(os.environ.get(
    "MULTIMODAL_PROXY_CONFIG_DIR",
    str(Path.home() / ".config" / "multimodal-proxy"),
))
CONFIG_PATH = CONFIG_DIR / "config.json"

mcp = FastMCP("multimodal-proxy")


def load_config() -> dict[str, Any]:
    """读取配置文件；不存在给出友好提示。"""
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"未找到配置文件 {CONFIG_PATH}。请先运行：bash scripts/install.sh"
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_api_key(cfg: dict[str, Any], provider: str) -> str:
    """按优先级解析 api_key：keychain > 环境变量 > 明文。"""
    p = cfg["providers"][provider]
    store = p.get("api_key_store", "plaintext")

    # 1. keychain（mac）
    if store == "keychain" and platform.system() == "Darwin":
        try:
            r = subprocess.run(
                ["security", "find-generic-password",
                 "-s", p.get("keychain_service", "multimodal-proxy"),
                 "-a", p.get("keychain_account", provider), "-w"],
                capture_output=True, text=True, check=True,
            )
            key = r.stdout.strip()
            if key:
                return key
        except subprocess.CalledProcessError:
            pass
        raise RuntimeError(f"keychain 读取失败，请重新运行：bash scripts/install.sh")

    # 2. 环境变量
    if p.get("api_key_env"):
        key = os.environ.get(p["api_key_env"])
        if key:
            return key

    # 3. 明文
    key = p.get("api_key")
    if key:
        return key

    raise RuntimeError("无法获取 api_key，请重新运行：bash scripts/install.sh")


def get_client(cfg: dict[str, Any], provider: str | None = None) -> tuple[str, OpenAI, dict]:
    """选取 provider 并构造客户端，返回 (provider名, 客户端, provider配置)。"""
    provider = provider or cfg.get("default_provider") or next(iter(cfg.get("providers", {})))
    if provider not in cfg.get("providers", {}):
        raise ValueError(f"provider '{provider}' 不存在，可选: {list(cfg.get('providers', {}))}")
    p = cfg["providers"][provider]
    return provider, OpenAI(api_key=resolve_api_key(cfg, provider), base_url=p["base_url"]), p


def to_data_url(path_or_url: str) -> str:
    """本地文件转 base64 data URL；http(s)/data URL 原样返回。"""
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    p = Path(path_or_url)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {path_or_url}")
    mime, _ = mimetypes.guess_type(str(p))
    if not mime:
        mime = "application/octet-stream"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def media_type_of(path_or_url: str) -> str:
    """根据扩展名/MIME 判断媒体类型：image / video / audio。"""
    if path_or_url.startswith(("http://", "https://")):
        # URL 按扩展名判断
        low = path_or_url.lower().split("?")[0]
    else:
        low = str(path_or_url).lower()
    if any(low.endswith(e) for e in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")):
        return "image"
    if any(low.endswith(e) for e in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv")):
        return "video"
    if any(low.endswith(e) for e in (".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus")):
        return "audio"
    # 兜底：用 MIME 猜
    mime, _ = mimetypes.guess_type(low)
    if mime:
        if mime.startswith("image/"): return "image"
        if mime.startswith("video/"): return "video"
        if mime.startswith("audio/"): return "audio"
    return "image"  # 默认当图片


def build_content(media: list[str], prompts: list[str], provider_cfg: dict) -> list[dict]:
    """把媒体和提示词组装成多模态 content 数组。

    约定：prompts 在前（作为任务指令），media 按顺序在后。
    """
    content: list[dict[str, Any]] = []
    # 提示词部分
    for p in prompts:
        if p.strip():
            content.append({"type": "text", "text": p})
    # 媒体部分
    ctypes = provider_cfg.get("content_types", {})
    for m in media:
        url = to_data_url(m)
        mtype = media_type_of(m)
        if mtype == "image":
            content.append({"type": ctypes.get("image", "image_url"),
                            "image_url": {"url": url}})
        elif mtype == "video":
            content.append({"type": ctypes.get("video", "video_url"),
                            "video_url": {"url": url}})
        elif mtype == "audio":
            # OpenAI 标准：input_audio 用 data + format
            data_part = url.split(",", 1)[1] if url.startswith("data:") else url
            fmt = "wav"
            if url.startswith("data:"):
                fmt = url.split(";")[0].split(":")[1].split("/")[1] if "/" in url.split(";")[0] else "wav"
            content.append({"type": ctypes.get("audio", "input_audio"),
                            "input_audio": {"data": data_part, "format": fmt}})
    return content


@mcp.tool()
def process_multimodal(
    media: list[str],
    prompts: list[str] | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """通用多模态处理：接收任意数量的图片/视频/音频 + 提示词，交给多模态模型处理。

    适用于：图像分析、OCR、多图对比、视频内容分析、图表解读、UI 审查等。
    当主模型是纯文本模型（glm-5.2/deepseek-v4 等）无法直接处理媒体时使用。

    参数:
      media: 媒体文件列表，每个元素是本地路径或 http(s) URL。
             支持图片(jpg/png/gif/webp/bmp)、视频(mp4/mov/webm)、音频(mp3/wav/m4a)。
             可混用多种类型，按顺序提交给模型。
      prompts: 提示词列表，0~n 条。作为任务指令在媒体之前提交。
               例如 ["提取图中所有文字", "用表格输出"] 或 ["对比这两张图"]。
      model: 可选，覆盖配置中的默认模型。
      provider: 可选，指定使用哪个 provider。

    示例:
      分析单图: process_multimodal(["/path/to/img.png"], ["描述这张图"])
      多图对比: process_multimodal(["/a.png", "/b.png"], ["对比这两张图的布局"])
      OCR提取: process_multimodal(["/scan.jpg"], ["提取图中所有文字", "保留原始格式"])
      纯提示词(无媒体): 不适用本工具，直接由主模型回答。
    """
    if not media:
        raise ValueError("media 不能为空。纯文本任务请直接由主模型处理。")
    prompts = prompts or []

    cfg = load_config()
    prov, client, prov_cfg = get_client(cfg, provider)
    m = model or prov_cfg.get("models", {}).get("vision")
    if not m:
        raise ValueError("未配置视觉模型，请运行：bash scripts/install.sh")

    content = build_content(media, prompts, prov_cfg)
    r = client.chat.completions.create(model=m, messages=[
        {"role": "user", "content": content}
    ], max_tokens=2048)
    return r.choices[0].message.content or ""


@mcp.tool()
def generate_image(
    prompt: str,
    model: str | None = None,
    provider: str | None = None,
    size: str | None = None,
) -> str:
    """根据文字提示词生成图片，返回生成结果的 URL 或状态。

    参数:
      prompt: 图像生成提示词
      model: 可选，覆盖配置中的 image_generation 模型
      provider: 可选，指定 provider
      size: 可选，图像尺寸（取决于模型支持）

    注意：需在配置中设置 image_generation 模型（如 doubao-seedream 系列）。
    """
    cfg = load_config()
    prov, client, prov_cfg = get_client(cfg, provider)
    m = model or prov_cfg.get("models", {}).get("image_generation")
    if not m:
        raise ValueError("未配置图像生成模型，请在配置中设置 models.image_generation")

    kwargs: dict[str, Any] = {"model": m, "prompt": prompt}
    if size:
        kwargs["size"] = size
    resp = client.images.generate(**kwargs)
    if resp.data and resp.data[0].url:
        return f"已生成图片，URL: {resp.data[0].url}"
    if resp.data and getattr(resp.data[0], "b64_json", None):
        return "已生成图片（base64），已返回 base64 数据。"
    return "图像生成完成，但未返回可用的 URL 或数据。"


if __name__ == "__main__":
    mcp.run()
