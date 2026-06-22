#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multimodal-proxy MCP server

通用多模态代理：通过 OpenAI 兼容 API（base_url + api_key + model）访问任意多模态模型，
按用户提示词对图像、视频、音频进行处理。

设计目标：让不支持多模态的纯文本主模型（如 glm-5.2、deepseek-v4）能把多模态任务
外包给支持多模态的模型（如火山引擎 doubao-vision），再把文字结果回填给主模型。

配置来源（启动时读取 ~/.config/multimodal-proxy/config.json）：
  - base_url / models：来自配置文件
  - api_key：mac 上优先 keychain，其次环境变量，最后配置文件明文（不推荐）

工具：
  - understand_image  图像分析 / OCR
  - understand_video  视频分析
  - transcribe_audio  音频转字幕
  - generate_image    图像生成
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

# --------------------------------------------------------------------------- #
# 配置加载
# --------------------------------------------------------------------------- #

CONFIG_PATH = Path(os.environ.get(
    "MULTIMODAL_PROXY_CONFIG",
    str(Path.home() / ".config" / "multimodal-proxy" / "config.json"),
))

# 各能力对应的 chat.completions content 类型名。
# OpenAI 兼容标准为 image_url / input_audio；视频无统一标准，火山方舟用 video_url。
# 若 provider 使用不同类型名，可在配置中通过 content_types 覆盖。
DEFAULT_CONTENT_TYPES = {
    "image": "image_url",
    "video": "video_url",
    "audio": "input_audio",
}


def load_config() -> dict[str, Any]:
    """读取配置文件；不存在时返回空配置并给出友好提示。"""
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"未找到配置文件 {CONFIG_PATH}。请先运行安装脚本 scripts/install.sh "
            "配置多模态模型的 base_url、api_key 和模型名称。"
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def read_keychain(service: str, account: str) -> str | None:
    """从 macOS keychain 读取密码；非 mac 或读取失败返回 None。"""
    if platform.system() != "Darwin":
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def resolve_api_key(provider_cfg: dict[str, Any]) -> str:
    """按优先级解析 api_key：keychain > 环境变量 > 配置文件明文。"""
    store = provider_cfg.get("api_key_store", "env")
    # 1. keychain（仅 mac）
    if store == "keychain":
        key = read_keychain(
            provider_cfg.get("keychain_service", "multimodal-proxy"),
            provider_cfg.get("keychain_account", "default"),
        )
        if key:
            return key
        # keychain 读取失败时回退到环境变量
    # 2. 环境变量
    env_name = provider_cfg.get("api_key_env")
    if env_name:
        key = os.environ.get(env_name)
        if key:
            return key
    # 3. 配置文件明文（不推荐，仅作兜底）
    key = provider_cfg.get("api_key")
    if key:
        return key
    raise RuntimeError(
        f"无法获取 api_key（store={store}, env={env_name}）。"
        "请检查 keychain / 环境变量 / 配置文件。"
    )


def get_provider(cfg: dict[str, Any], name: str | None = None) -> tuple[str, dict[str, Any]]:
    """选取 provider：显式指定 > 默认 > 第一个。"""
    providers = cfg.get("providers", {})
    if not providers:
        raise RuntimeError("配置中没有 providers。请运行 scripts/install.sh。")
    name = name or cfg.get("default_provider") or next(iter(providers))
    if name not in providers:
        raise RuntimeError(f"provider '{name}' 不存在，可选: {list(providers)}")
    return name, providers[name]


def make_client(provider_cfg: dict[str, Any]) -> OpenAI:
    """构造 OpenAI 兼容客户端。"""
    return OpenAI(
        api_key=resolve_api_key(provider_cfg),
        base_url=provider_cfg["base_url"],
    )


def pick_model(provider_cfg: dict[str, Any], capability: str, override: str | None = None) -> str:
    """按能力选取模型；允许工具调用时显式覆盖。"""
    model = override or provider_cfg.get("models", {}).get(capability)
    if not model:
        raise RuntimeError(
            f"未配置 '{capability}' 模型。请在配置文件 models 中设置，"
            f"或在调用时通过 model 参数指定。"
        )
    return model


# --------------------------------------------------------------------------- #
# 媒体处理工具
# --------------------------------------------------------------------------- #

def to_data_url(path_or_url: str) -> str:
    """本地文件转 base64 data URL；http(s) URL 原样返回。"""
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    p = Path(path_or_url)
    if not p.exists():
        raise FileNotFoundError(f"媒体文件不存在: {path_or_url}")
    mime, _ = mimetypes.guess_type(str(p))
    if not mime:
        mime = "application/octet-stream"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def content_types_of(provider_cfg: dict[str, Any]) -> dict[str, str]:
    """合并默认与 provider 自定义的 content 类型名。"""
    return {**DEFAULT_CONTENT_TYPES, **provider_cfg.get("content_types", {})}


# --------------------------------------------------------------------------- #
# MCP 工具
# --------------------------------------------------------------------------- #

mcp = FastMCP("multimodal-proxy")


def _understand(
    media: str, prompt: str, capability: str, media_key: str,
    model: str | None, provider: str | None,
    extra_content: dict[str, Any] | None = None,
) -> str:
    """理解类任务（图像/视频/音频）的通用实现：chat.completions + 多模态 content。"""
    cfg = load_config()
    _, prov_cfg = get_provider(cfg, provider)
    client = make_client(prov_cfg)
    mdl = pick_model(prov_cfg, capability, model)
    ctypes = content_types_of(prov_cfg)
    url = to_data_url(media)

    # 组装 content：先文本提示词，再媒体
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    media_part: dict[str, Any] = {"type": ctypes[media_key]}
    # input_audio 用 data 字段，其余用 url 字段
    if media_key == "audio":
        # OpenAI input_audio 格式：{type:input_audio, input_audio:{data, format}}
        fmt = (url.split(";")[0].split(":")[1] if url.startswith("data:") else "wav")
        media_part = {"type": "input_audio",
                      "input_audio": {"data": url.split(",", 1)[1] if "," in url else url,
                                      "format": fmt}}
    else:
        media_part[ctypes[media_key]] = {"url": url}
    if extra_content:
        media_part.update(extra_content)
    content.append(media_part)

    resp = client.chat.completions.create(model=mdl, messages=[{"role": "user", "content": content}])
    return resp.choices[0].message.content or ""


@mcp.tool()
def understand_image(
    image: str,
    prompt: str = "请详细描述这张图片的内容",
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """分析图片内容并返回文字描述。可用于图像分析、OCR 文字提取、图表解读、UI 审查等。

    参数:
      image: 图片路径，支持本地文件路径或 http(s) URL（jpg/png/gif/webp/bmp）
      prompt: 想问的问题，如"提取图中所有文字""图中有哪些物体"
      model: 可选，覆盖配置中的 vision 模型（模型名或 endpoint id）
      provider: 可选，指定使用哪个 provider（默认配置中的 default_provider）
    """
    return _understand(image, prompt, "vision", "image", model, provider)


@mcp.tool()
def understand_video(
    video: str,
    prompt: str = "请分析这段视频的内容",
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """分析视频内容并返回文字描述。可用于视频理解、动作识别、内容摘要等。

    参数:
      video: 视频路径，支持本地文件路径或 http(s) URL
      prompt: 想问的问题
      model: 可选，覆盖配置中的 video 模型
      provider: 可选，指定 provider
    """
    return _understand(video, prompt, "video", "video", model, provider)


@mcp.tool()
def transcribe_audio(
    audio: str,
    prompt: str = "请将这段音频转录为文字字幕",
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """音频转字幕/文字。可用于语音转写、会议纪要、字幕生成等。

    参数:
      audio: 音频路径，支持本地文件路径或 http(s) URL（mp3/wav/m4a 等）
      prompt: 想问的问题或转录要求，如"转成带时间戳的 srt 字幕"
      model: 可选，覆盖配置中的 audio 模型
      provider: 可选，指定 provider
    """
    return _understand(audio, prompt, "audio", "audio", model, provider)


@mcp.tool()
def generate_image(
    prompt: str,
    model: str | None = None,
    provider: str | None = None,
    size: str | None = None,
) -> str:
    """根据文字提示词生成图片，返回生成结果的 URL 或保存路径信息。

    参数:
      prompt: 图像生成提示词
      model: 可选，覆盖配置中的 image_generation 模型
      provider: 可选，指定 provider
      size: 可选，图像尺寸（取决于模型支持）
    """
    cfg = load_config()
    _, prov_cfg = get_provider(cfg, provider)
    client = make_client(prov_cfg)
    mdl = pick_model(prov_cfg, "image_generation", model)

    kwargs: dict[str, Any] = {"model": mdl, "prompt": prompt}
    if size:
        kwargs["size"] = size
    resp = client.images.generate(**kwargs)
    # 优先返回 url，其次 b64_json
    if resp.data and resp.data[0].url:
        return f"已生成图片，URL: {resp.data[0].url}"
    if resp.data and getattr(resp.data[0], "b64_json", None):
        return "已生成图片（base64），已返回 base64 数据。"
    return "图像生成完成，但未返回可用的 URL 或数据。"


if __name__ == "__main__":
    mcp.run()
