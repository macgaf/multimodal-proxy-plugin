#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multimodal-proxy 配置工具

写入配置文件到 ~/.config/multimodal-proxy/config.json
Mac 上支持将 api_key 存入 keychain（推荐）
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
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def keychain_store(service: str, account: str, key: str) -> bool:
    """将 api_key 存入 macOS keychain。成功返回 True"""
    if platform.system() != "Darwin":
        return False
    try:
        subprocess.run(
            ["security", "add-generic-password", "-s", service, "-a", account, "-w", key, "-U"],
            capture_output=True, text=True, check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠ keychain 存储失败: {e.stderr}", file=sys.stderr)
        return False


def prompt(name: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{name}{suffix}: ").strip()
    return val or (default or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="配置 multimodal-proxy")
    parser.add_argument("--provider", default="volcengine", help="provider 名称")
    parser.add_argument("--base-url", default="https://ark.cn-beijing.volces.com/api/coding/v3", help="base_url")
    parser.add_argument("--api-key", default=None, help="api_key（不传则交互式输入）")
    parser.add_argument("--vision-model", default="doubao-seed-2.0-pro", help="视觉模型名")
    parser.add_argument("--no-keychain", action="store_true", help="不使用 keychain，明文存配置")
    parser.add_argument("--keychain-service", default=DEFAULT_SERVICE)
    parser.add_argument("--keychain-account", default=None)
    args = parser.parse_args()

    interactive = not sys.stdin.isatty() is False and not args.api_key

    if interactive:
        print("=" * 60)
        print("  multimodal-proxy 配置工具")
        print("=" * 60)
        args.provider = prompt("provider 名称", args.provider)
        args.base_url = prompt("base_url", args.base_url)
        args.vision_model = prompt("视觉模型名称", args.vision_model)

    cfg = load_config()
    prov = cfg["providers"].setdefault(args.provider, {})
    prov["base_url"] = args.base_url
    prov.setdefault("models", {})["vision"] = args.vision_model

    account = args.keychain_account or args.provider

    if interactive and platform.system() == "Darwin" and not args.no_keychain:
        use_kc = prompt("是否将 api_key 存入 keychain？(Y/n)", "Y").lower()
        if use_kc in ("y", "yes", "1"):
            args.no_keychain = False
        else:
            args.no_keychain = True

    use_kc = platform.system() == "Darwin" and not args.no_keychain
    if use_kc:
        key = args.api_key or (prompt("api_key", secret=True) if interactive else "")
        if not key:
            print("✗ api_key 不能为空", file=sys.stderr)
            return 1
        if keychain_store(args.keychain_service, account, key):
            prov["api_key_store"] = "keychain"
            prov["keychain_service"] = args.keychain_service
            prov["keychain_account"] = account
            prov.pop("api_key", None)
            print(f"✓ api_key 已存入 keychain (service={args.keychain_service}, account={account})")
        else:
            print("⚠ keychain 不可用，回退到明文存储", file=sys.stderr)
            prov["api_key_store"] = "plaintext"
            prov["api_key"] = key
    else:
        key = args.api_key or (prompt("api_key", secret=True) if interactive else "")
        if not key:
            print("✗ api_key 不能为空", file=sys.stderr)
            return 1
        prov["api_key_store"] = "plaintext"
        prov["api_key"] = key
        if interactive:
            print("⚠ api_key 以明文存入配置文件", file=sys.stderr)

    if "default_provider" not in cfg:
        cfg["default_provider"] = args.provider

    save_config(cfg)
    print(f"✓ 配置已写入: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
