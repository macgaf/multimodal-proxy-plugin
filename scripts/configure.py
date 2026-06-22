#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multimodal-proxy 配置工具：写入配置文件 + 管理 api_key 存储（keychain/env/明文）。

被 install.sh 调用，也可独立运行。配置文件位于
~/.config/multimodal-proxy/config.json。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path(os.environ.get(
    "MULTIMODAL_PROXY_CONFIG_DIR",
    str(Path.home() / ".config" / "multimodal-proxy"),
))
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_SERVICE = "multimodal-proxy"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"providers": {}}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    # 配置文件可能含敏感引用，限制权限
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def keychain_store(service: str, account: str, key: str) -> bool:
    """将 api_key 存入 macOS keychain；成功返回 True。"""
    if platform.system() != "Darwin":
        return False
    try:
        subprocess.run(
            ["security", "add-generic-password", "-s", service, "-a", account,
             "-w", key, "-U"],
            check=True, capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"⚠ keychain 存储失败: {e}", file=sys.stderr)
        return False


def prompt(name: str, default: str | None = None, secret: bool = False) -> str:
    """交互式提示输入。"""
    suffix = f" [{default}]" if default else ""
    if secret:
        # 隐藏输入（简单实现：不回显）
        import getpass
        val = getpass.getpass(f"{name}{suffix}: ").strip()
    else:
        val = input(f"{name}{suffix}: ").strip()
    return val or (default or "")


def main() -> int:
    ap = argparse.ArgumentParser(description="配置 multimodal-proxy")
    ap.add_argument("--provider", default=None, help="provider 名称，如 volcengine")
    ap.add_argument("--base-url", default=None, help="OpenAI 兼容接入地址")
    ap.add_argument("--api-key", default=None, help="api_key（不传则交互输入）")
    ap.add_argument("--vision-model", default=None, help="图像理解模型")
    ap.add_argument("--video-model", default=None, help="视频理解模型")
    ap.add_argument("--audio-model", default=None, help="音频理解模型")
    ap.add_argument("--image-gen-model", default=None, help="图像生成模型")
    ap.add_argument("--keychain", action="store_true", help="mac 上将 api_key 存入 keychain")
    ap.add_argument("--keychain-service", default=DEFAULT_SERVICE)
    ap.add_argument("--keychain-account", default=None)
    ap.add_argument("--api-key-env", default=None, help="改用环境变量读取 key 的变量名")
    ap.add_argument("--set-default", action="store_true", help="设为默认 provider")
    args = ap.parse_args()

    interactive = not sys.stdin.isatty() is False and not any(
        [args.provider, args.base_url]
    )
    # 交互模式补全缺失项
    provider = args.provider or prompt("provider 名称", "volcengine")
    base_url = args.base_url or prompt(
        "base_url", "https://ark.cn-beijing.volces.com/api/v3"
    )
    account = args.keychain_account or provider

    cfg = load_config()
    prov = cfg.setdefault("providers", {}).setdefault(provider, {})
    prov["base_url"] = base_url

    # api_key 存储策略
    if args.keychain and platform.system() == "Darwin":
        key = args.api_key or prompt("api_key", secret=True)
        if not key:
            print("✗ api_key 不能为空", file=sys.stderr)
            return 1
        if keychain_store(args.keychain_service, account, key):
            prov["api_key_store"] = "keychain"
            prov["keychain_service"] = args.keychain_service
            prov["keychain_account"] = account
            prov.pop("api_key", None)
            prov.pop("api_key_env", None)
            print(f"✓ api_key 已存入 keychain (service={args.keychain_service}, account={account})")
        else:
            print("⚠ keychain 不可用，回退到环境变量方式", file=sys.stderr)
            prov["api_key_store"] = "env"
            prov["api_key_env"] = args.api_key_env or f"{provider.upper()}_API_KEY"
            prov["api_key"] = key
    elif args.api_key_env:
        prov["api_key_store"] = "env"
        prov["api_key_env"] = args.api_key_env
    else:
        key = args.api_key or prompt("api_key", secret=True)
        prov["api_key_store"] = "plaintext"
        prov["api_key"] = key
        print("⚠ api_key 以明文存入配置文件，建议改用 --keychain 或 --api-key-env", file=sys.stderr)

    # 模型配置（按能力）
    models = prov.setdefault("models", {})
    caps = {
        "vision": (args.vision_model, "图像理解模型", "doubao-Seed-2.0-pro"),
        "video": (args.video_model, "视频理解模型", ""),
        "audio": (args.audio_model, "音频理解模型", ""),
        "image_generation": (args.image_gen_model, "图像生成模型", ""),
    }
    for cap, (val, label, default) in caps.items():
        m = val or (prompt(label, default) if interactive else val or default)
        if m:
            models[cap] = m

    if args.set_default or "default_provider" not in cfg:
        cfg["default_provider"] = provider

    save_config(cfg)
    print(f"✓ 配置已写入 {CONFIG_PATH}")
    print(f"  provider={provider}  base_url={base_url}")
    print(f"  models={prov.get('models', {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
