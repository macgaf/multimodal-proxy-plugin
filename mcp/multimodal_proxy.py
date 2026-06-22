#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multimodal-proxy MCP server

通过火山引擎 Coding Plan API 将多模态任务外包给支持视觉的模型（如 doubao-seed-2.0-pro）。
专供主模型为纯文本模型（glm-5.2/deepseek-v4 等）时使用。

配置文件：~/.config/multimodal-proxy/config.json
  {
    "default_provider": "volcengine",
    "providers": {
      "volcengine": {
        "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "api_key_store": "keychain",
        "keychain_service": "multimodal-proxy",
        "keychain_account": "volcengine",
        "models": {"vision": "doubao-seed-2.0-pro"}
      }
    }
  }
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import platform
import subprocess
import sys
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
    """读取配置文件"""
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"未找到配置文件 {CONFIG_PATH}。请先运行：\n"
            f"  python3 -m pip install -r requirements.txt\n"
            f"  python3 scripts/configure.py"
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_api_key(cfg: dict[str, Any], provider: str) -> str:
    """按优先级解析 api_key：keychain > env > 明文"""
    p = cfg["providers"].get(provider, {})
    store = p.get("api_key_store", "plaintext")

    if store == "keychain" and platform.system() == "Darwin":
        try:
            r = subprocess.run(
                ["security", "find-generic-password",
                 "-s", p.get("keychain_service", "multimodal-proxy"),
                 "-a", p.get("keychain_account", provider),
                 "-w"],
                capture_output=True, text=True, check=True,
            )
            key = r.stdout.strip()
            if key:
                return key
        except subprocess.CalledProcessError:
            pass
        raise RuntimeError(f"keychain 读取失败，请重新配置：python3 scripts/configure.py")

    if p.get("api_key_env"):
        key = os.environ.get(p["api_key_env"])
        if key:
            return key

    key = p.get("api_key")
    if key:
        return key

    raise RuntimeError("无法获取 api_key，请重新配置：python3 scripts/configure.py")


def get_client(cfg: dict[str, Any], provider: str | None = None) -> tuple[str, OpenAI]:
    provider = provider or cfg.get("default_provider") or next(iter(cfg.get("providers", {})))
    if not cfg.get("providers", {}).get(provider):
        raise ValueError(f"provider '{provider}' 不存在，可选: {list(cfg.get('providers', {}))}")
    p = cfg["providers"][provider]
    return provider, OpenAI(
        api_key=resolve_api_key(cfg, provider),
        base_url=p["base_url"],
    )


def to_data_url(path_or_url: str) -> str:
    """本地文件转 base64 data URL；http(s) 原样返回"""
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


@mcp.tool()
def understand_image(
    image: str,
    prompt: str = "请详细描述这张图片的内容",
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """分析图片内容并返回文字描述。可用于图片分析、OCR文字提取、图表解读、UI审查等。

    参数:
      image: 图片路径，支持本地文件路径或 http(s) URL（jpg/png/gif/webp/bmp）
      prompt: 想问的问题，如"提取图中所有文字""图中有哪些物体"
      model: 可选，覆盖配置中的视觉模型名
      provider: 可选，指定使用哪个 provider
    """
    cfg = load_config()
    prov, client = get_client(cfg, provider)
    p = cfg["providers"][prov]
    m = model or p.get("models", {}).get("vision")
    if not m:
        raise ValueError("未配置视觉模型，请运行：python3 scripts/configure.py")

    url = to_data_url(image)
    r = client.chat.completions.create(model=m, messages=[
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": url}},
        ]}
    ], max_tokens=1024)
    return r.choices[0].message.content or ""


if __name__ == "__main__":
    mcp.run()
