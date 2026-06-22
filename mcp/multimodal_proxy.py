#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multimodal-proxy MCP server

通用多模态代理：通过火山引擎 Coding Plan API 将多模态任务外包给支持视觉的模型
（如 doubao-seed-2.0-pro）。专供主模型为纯文本模型（glm-5.2/deepseek-v4 等）时使用。

核心设计：
  - save_clipboard_to_file：读系统剪贴板，图片落盘返回路径（绕过 Ctrl-V 硬拦截）
  - process_multimodal：接收任意数量的图片/视频/音频 + 提示词，交给模型处理

已验证的模型能力（doubao-seed-2.0-pro, Coding Plan）：
  - 图片 image_url      ✅ 支持（多图对比）
  - 视频 video_url      ✅ 类型被接受（需可访问 URL）
  - 音频 input_audio    ⚠️ 需在火山方舟控制台确认音频能力开通状态

配置文件：~/.config/multimodal-proxy/config.json
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import keyring
from mcp.server.fastmcp import FastMCP
from openai import OpenAI

CONFIG_DIR = Path(os.environ.get(
    "MULTIMODAL_PROXY_CONFIG_DIR",
    str(Path.home() / ".config" / "multimodal-proxy"),
))
CONFIG_PATH = CONFIG_DIR / "config.json"

# 剪贴板临时文件目录
CLIPBOARD_TMP_DIR = Path(os.environ.get(
    "MULTIMODAL_PROXY_CLIP_DIR",
    tempfile.gettempdir(),
))

mcp = FastMCP("multimodal-proxy")


def load_config() -> dict[str, Any]:
    """读取配置文件；不存在给出友好提示。"""
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"未找到配置文件 {CONFIG_PATH}。请先运行：bash scripts/install.sh"
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_api_key(cfg: dict[str, Any], provider: str) -> str:
    """按 api_key_store 字段指定的方式获取 api_key。

    支持三种存储方式（严格匹配，不回退）：
      - keychain  ：从 macOS 钥匙串读取（仅 macOS）
      - env       ：从环境变量读取（变量名记录在 api_key_env 字段）
      - plaintext ：从配置文件的 api_key 字段读取
    """
    p = cfg["providers"][provider]
    store = p.get("api_key_store", "plaintext")

    if store == "keychain":
        # macOS keychain
        if platform.system() != "Darwin":
            raise RuntimeError(
                "api_key_store=keychain 但当前平台非 macOS。"
                "请重新运行：bash scripts/install.sh 选择其他存储方式。"
            )
        key = keyring.get_password(
            p.get("keychain_service", "multimodal-proxy"),
            p.get("keychain_account", provider),
        )
        if key:
            return key
        raise RuntimeError(
            f"keychain 读取失败 (service={p.get('keychain_service')}, "
            f"account={p.get('keychain_account')})，请重新运行：bash scripts/install.sh"
        )

    elif store == "env":
        # 环境变量
        env_var = p.get("api_key_env")
        if not env_var:
            raise RuntimeError(
                "api_key_store=env 但未配置 api_key_env 字段。"
                "请重新运行：bash scripts/install.sh"
            )
        key = os.environ.get(env_var)
        if not key:
            raise RuntimeError(
                f"环境变量 {env_var} 未设置。请先设置：export {env_var}='你的-api-key'"
            )
        return key

    else:
        # plaintext（默认）
        key = p.get("api_key")
        if not key:
            raise RuntimeError(
                "配置文件中未找到 api_key（api_key_store=plaintext）。"
                "请重新运行：bash scripts/install.sh"
            )
        return key


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
        low = path_or_url.lower().split("?")[0]
    else:
        low = str(path_or_url).lower()
    if any(low.endswith(e) for e in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")):
        return "image"
    if any(low.endswith(e) for e in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv")):
        return "video"
    if any(low.endswith(e) for e in (".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus")):
        return "audio"
    mime, _ = mimetypes.guess_type(low)
    if mime:
        if mime.startswith("image/"): return "image"
        if mime.startswith("video/"): return "video"
        if mime.startswith("audio/"): return "audio"
    return "image"


def build_content(media: list[str], prompts: list[str], provider_cfg: dict) -> list[dict]:
    """把媒体和提示词组装成多模态 content 数组。

    约定：prompts 在前（作为任务指令），media 按顺序在后。
    """
    content: list[dict[str, Any]] = []
    for p in prompts:
        if p.strip():
            content.append({"type": "text", "text": p})
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
            data_part = url.split(",", 1)[1] if url.startswith("data:") else url
            fmt = "wav"
            if url.startswith("data:"):
                fmt = url.split(";")[0].split(":")[1].split("/")[1] if "/" in url.split(";")[0] else "wav"
            content.append({"type": ctypes.get("audio", "input_audio"),
                            "input_audio": {"data": data_part, "format": fmt}})
    return content


# ─── 剪贴板工具（跨平台：macOS / Windows / Linux） ───


def _read_clipboard_macos(dest_path: str) -> str:
    """macOS：通过 osascript 读剪贴板，返回 "image:path" / "text:内容" / "empty:"。"""
    script = r"""
on run
    try
        set pngData to (get the clipboard as «class PNGf»)
        set fp to open for access POSIX file "%s" with write permission
        set eof of fp to 0
        write pngData to fp
        close access fp
        return "image:" & "%s"
    on error
        try
            set txt to (get the clipboard as text)
            if txt is "" then
                return "empty:"
            end if
            return "text:" & txt
        on error
            return "empty:"
        end try
    end try
end run
""" % (dest_path, dest_path)
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    out = r.stdout.strip()
    if out:
        return out
    return "empty:"


def _read_clipboard_windows(dest_path: str) -> str:
    """Windows：通过 PowerShell 读剪贴板，返回 "image:path" / "text:内容" / "empty:"。"""
    # PowerShell 路径需要用反斜杠
    win_path = dest_path.replace("/", "\\")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "if ([System.Windows.Forms.Clipboard]::ContainsImage()) { "
        f"$img = [System.Windows.Forms.Clipboard]::GetImage(); "
        f"$img.Save('{win_path}', [System.Drawing.Imaging.ImageFormat]::Png); "
        f"Write-Output 'image:{dest_path}' "
        "} elseif ([System.Windows.Forms.Clipboard]::ContainsText()) { "
        "$txt = [System.Windows.Forms.Clipboard]::GetText(); "
        "Write-Output ('text:' + $txt) "
        "} else { "
        "Write-Output 'empty:' "
        "}"
    )
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
        capture_output=True, text=True, timeout=15,
    )
    out = r.stdout.strip()
    if out:
        return out
    return "empty:"


def _read_clipboard_linux(dest_path: str) -> str:
    """Linux：通过 wl-paste（Wayland）或 xclip（X11）读剪贴板。

    返回 "image:path" / "text:内容" / "empty:"。
    """
    # 优先 Wayland（wl-paste），其次 X11（xclip）
    if shutil.which("wl-paste"):
        return _read_clipboard_wlpaste(dest_path)
    if shutil.which("xclip"):
        return _read_clipboard_xclip(dest_path)
    return ("error:未找到 wl-paste 或 xclip。"
            "Wayland 请安装 wl-clipboard，X11 请安装 xclip。")


def _read_clipboard_wlpaste(dest_path: str) -> str:
    """Wayland：用 wl-paste 读剪贴板。"""
    # 先列出剪贴板可用类型
    r_types = subprocess.run(
        ["wl-paste", "-l"],
        capture_output=True, text=True, timeout=10,
    )
    types = r_types.stdout.strip().lower()

    # 检查是否有图片类型
    if any(t in types for t in ("image/png", "image/jpeg", "image/jpg")):
        # 确定具体 MIME 类型
        mime = "image/png"
        if "image/jpeg" in types or "image/jpg" in types:
            mime = "image/jpeg"
        r = subprocess.run(
            ["wl-paste", "-t", mime],
            capture_output=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout:
            Path(dest_path).write_bytes(r.stdout)
            return f"image:{dest_path}"

    # 尝试获取文本
    r = subprocess.run(
        ["wl-paste"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0 and r.stdout:
        return f"text:{r.stdout}"
    return "empty:"


def _read_clipboard_xclip(dest_path: str) -> str:
    """X11：用 xclip 读剪贴板。"""
    # 先列出剪贴板可用类型
    r_types = subprocess.run(
        ["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"],
        capture_output=True, text=True, timeout=10,
    )
    types = r_types.stdout.strip().lower()

    # 检查是否有图片类型
    if any(t in types for t in ("image/png", "image/jpeg", "image/jpg")):
        mime = "image/png"
        if "image/jpeg" in types or "image/jpg" in types:
            mime = "image/jpeg"
        r = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", mime, "-o"],
            capture_output=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout:
            Path(dest_path).write_bytes(r.stdout)
            return f"image:{dest_path}"

    # 尝试获取文本
    r = subprocess.run(
        ["xclip", "-selection", "clipboard", "-o"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0 and r.stdout:
        return f"text:{r.stdout}"
    return "empty:"


def _read_clipboard(dest_path: str) -> str:
    """跨平台读剪贴板，返回 "image:path" / "text:内容" / "empty:" / "error:消息"。

    自动检测平台并分派到对应实现：
      - macOS：osascript（AppleScript）
      - Windows：PowerShell + System.Windows.Forms.Clipboard
      - Linux：wl-paste（Wayland）或 xclip（X11）
    """
    system = platform.system()
    if system == "Darwin":
        return _read_clipboard_macos(dest_path)
    elif system == "Windows":
        return _read_clipboard_windows(dest_path)
    elif system == "Linux":
        return _read_clipboard_linux(dest_path)
    else:
        return f"error:不支持的平台 {system}"


@mcp.tool()
def save_clipboard_to_file() -> str:
    """读取系统剪贴板内容并保存为临时文件（支持 macOS / Windows / Linux）。

    用于绕过 Codex 对纯文本模型的图片输入硬拦截：用户 Ctrl-V 粘贴截图会被拦截，
    但截图仍在系统剪贴板中。本工具从剪贴板读取图片数据，保存为临时 PNG 文件，
    返回文件路径，供后续 process_multimodal 工具分析。

    跨平台支持：
      - macOS：osascript（AppleScript 读 «class PNGf»）
      - Windows：PowerShell + System.Windows.Forms.Clipboard
      - Linux：wl-paste（Wayland）或 xclip（X11）

    工作流：
      1. 用户先截图到剪贴板
         - macOS：Ctrl-Shift-Cmd-4
         - Windows：Win-Shift-S（截图工具）
         - Linux：取决于桌面环境（如 gnome-screenshot -c）
      2. 在 Codex 里输入文本指令，如"分析一下我刚截的屏"
      3. 主模型调用本工具 → 剪贴板图片落盘 → 返回路径
      4. 主模型调用 process_multimodal([路径], [提示词]) 完成分析

    返回值：
      - 图片：返回保存的文件路径（如 /tmp/mmp-clip-1234567890.png）
      - 文本：返回 "clipboard_text: <文本内容>"（剪贴板里是文字而非图片）
      - 空：返回 "剪贴板为空或不含图片数据"
      - 错误：返回 "error: <错误描述>"
    """
    ts = int(time.time() * 1000)
    dest = str(CLIPBOARD_TMP_DIR / f"mmp-clip-{ts}.png")

    result = _read_clipboard(dest)

    if result.startswith("image:"):
        path = result.split(":", 1)[1]
        if Path(path).exists() and Path(path).stat().st_size > 0:
            return path
        return "错误：剪贴板图片保存失败"
    elif result.startswith("text:"):
        text = result.split(":", 1)[1]
        return f"clipboard_text: {text}"
    elif result.startswith("error:"):
        return result
    else:
        return ("剪贴板为空或不含图片数据。请先截图到剪贴板"
                "（macOS: Ctrl-Shift-Cmd-4, Windows: Win-Shift-S, Linux: 截图工具复制到剪贴板），"
                "再重试。")


# ─── 多模态处理工具 ───

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
