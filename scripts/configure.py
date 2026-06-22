#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multimodal-proxy 配置工具

写入配置文件到 ~/.config/multimodal-proxy/config.json
支持三种 api_key 存储方式：
  1. keychain（仅 macOS，推荐）—— api_key 存入系统钥匙串，配置文件无明文
  2. plaintext              —— api_key 明文写入配置文件
  3. env                    —— api_key 从环境变量读取，配置文件只记录变量名
"""
from __future__ import annotations

import argparse
import getpass
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

# 支持的存储方式
VALID_STORES = ("keychain", "plaintext", "env")


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


def keychain_delete(service: str, account: str) -> None:
    """从 macOS keychain 删除旧 key（忽略不存在的情况）。"""
    if platform.system() != "Darwin":
        return
    subprocess.run(
        ["security", "delete-generic-password", "-s", service, "-a", account],
        capture_output=True, text=True,
    )


def prompt(name: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{name}{suffix}: ").strip()
    return val or (default or "")


def prompt_secret(name: str) -> str:
    """安全输入敏感信息（不回显）。"""
    return getpass.getpass(f"{name}: ").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="配置 multimodal-proxy")
    parser.add_argument("--provider", default="volcengine", help="provider 名称")
    parser.add_argument("--base-url", default="https://ark.cn-beijing.volces.com/api/coding/v3", help="base_url")
    parser.add_argument("--api-key", default=None, help="api_key（不传则交互式输入）")
    parser.add_argument("--vision-model", default="doubao-seed-2.0-pro", help="视觉模型名")
    parser.add_argument(
        "--key-store",
        choices=VALID_STORES,
        default=None,
        help="api_key 存储方式：keychain（mac）、plaintext（明文）、env（环境变量）",
    )
    parser.add_argument("--keychain-service", default=DEFAULT_SERVICE)
    parser.add_argument("--keychain-account", default=None)
    parser.add_argument("--api-key-env", default=None, help="环境变量名（--key-store=env 时使用）")
    args = parser.parse_args()

    interactive = sys.stdin.isatty() and not args.api_key

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

    # ─── 确定 api_key 存储方式 ───
    is_mac = platform.system() == "Darwin"

    if args.key_store:
        key_store = args.key_store
    elif interactive:
        print()
        print("── api_key 存储方式 ──")
        print("  1) keychain  —— 存入 macOS 钥匙串，配置文件无明文（推荐，仅 macOS）")
        print("  2) plaintext —— 明文写入配置文件")
        print("  3) env       —— 从环境变量读取，配置文件只记录变量名")
        choices = {"1": "keychain", "2": "plaintext", "3": "env"}
        default_choice = "1" if is_mac else "2"
        while True:
            choice = prompt(f"选择 (1/2/3)", default_choice)
            if choice in choices:
                key_store = choices[choice]
                break
            print("  无效选择，请输入 1、2 或 3")
    else:
        # 非交互且未指定，mac 默认 keychain，其他平台默认 plaintext
        key_store = "keychain" if is_mac else "plaintext"

    # keychain 仅 mac 可用
    if key_store == "keychain" and not is_mac:
        print("⚠ 非 macOS 平台不支持 keychain，回退到 plaintext", file=sys.stderr)
        key_store = "plaintext"

    # ─── 清理旧存储方式的残留字段 ───
    old_store = prov.get("api_key_store")
    if old_store == "keychain" and key_store != "keychain":
        keychain_delete(prov.get("keychain_service", DEFAULT_SERVICE), prov.get("keychain_account", account))
    prov.pop("api_key", None)
    prov.pop("api_key_env", None)
    prov.pop("keychain_service", None)
    prov.pop("keychain_account", None)

    # ─── 按存储方式写入 ───
    if key_store == "keychain":
        key = args.api_key or (prompt_secret("api_key") if interactive else "")
        if not key:
            print("✗ api_key 不能为空", file=sys.stderr)
            return 1
        if keychain_store(args.keychain_service, account, key):
            prov["api_key_store"] = "keychain"
            prov["keychain_service"] = args.keychain_service
            prov["keychain_account"] = account
            print(f"✓ api_key 已存入 keychain (service={args.keychain_service}, account={account})")
        else:
            print("⚠ keychain 不可用，回退到明文存储", file=sys.stderr)
            prov["api_key_store"] = "plaintext"
            prov["api_key"] = key

    elif key_store == "plaintext":
        key = args.api_key or (prompt_secret("api_key") if interactive else "")
        if not key:
            print("✗ api_key 不能为空", file=sys.stderr)
            return 1
        prov["api_key_store"] = "plaintext"
        prov["api_key"] = key
        if interactive:
            print("⚠ api_key 以明文存入配置文件", file=sys.stderr)

    elif key_store == "env":
        env_var = args.api_key_env
        if not env_var and interactive:
            print("  将 api_key 存入环境变量，配置文件只记录变量名（不含实际 key）。")
            env_var = prompt("环境变量名", f"MULTIMODAL_PROXY_API_KEY_{args.provider.upper()}")
        if not env_var:
            print("✗ 环境变量名不能为空", file=sys.stderr)
            return 1
        prov["api_key_store"] = "env"
        prov["api_key_env"] = env_var
        # 如果用户同时传了 --api-key，提示如何设置环境变量
        if args.api_key:
            print(f"✓ 配置已写入，请确保环境变量 {env_var} 已设置")
        else:
            print(f"✓ 配置已写入，请在运行 Codex 前设置环境变量：")
            print(f"  export {env_var}='你的-api-key'")
            print(f"  （建议写入 ~/.zshrc 或 ~/.bashrc）")

    if "default_provider" not in cfg:
        cfg["default_provider"] = args.provider

    save_config(cfg)
    print(f"✓ 配置已写入: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
