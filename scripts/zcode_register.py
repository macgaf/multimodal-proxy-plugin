#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZCode 插件注册：把插件 symlink 进 cache、合并 marketplace.json、写 enabledPlugins。

由 install.sh 的 ZCode 分支调用。CLI 用法：
    zcode_register.py --plugin-root <PLUGIN_ROOT> --marketplace <name> --version <ver>

注册三步（幂等）：
  1. cache 目录 symlink 到 plugin_root（已存在且非 symlink 则报错，不删用户内容）
  2. 合并 marketplaces/<marketplace>/marketplace.json（upsert，保留其他条目）
  3. 写 ~/.zcode/cli/config.json 的 enabledPlugins["<plugin>@<marketplace>"]=true（保留其他键）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def register(
    cli_root: str,
    plugin_root: str,
    plugin_name: str,
    marketplace: str,
    version: str,
) -> None:
    """执行 ZCode 三步注册。失败抛异常，不破坏已有文件。"""
    cli = Path(cli_root).expanduser()
    plugins_root = cli / "plugins"
    cache_base = plugins_root / "cache" / marketplace / plugin_name / version
    marketplaces_dir = plugins_root / "marketplaces" / marketplace
    config_path = cli / "config.json"

    # ── 1. cache symlink ──
    if cache_base.exists() and not cache_base.is_symlink():
        raise RuntimeError(
            f"cache 目录已存在且非 symlink，拒绝覆盖: {cache_base}。"
            "请确认后手动删除该目录再重跑。"
        )
    # symlink 幂等：先删旧 symlink（ln -sfn 语义）
    if cache_base.is_symlink() or cache_base.exists():
        cache_base.unlink()
    cache_base.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(str(Path(plugin_root).resolve()), str(cache_base))

    # ── 2. 合并 marketplace.json ──
    marketplaces_dir.mkdir(parents=True, exist_ok=True)
    mp_path = marketplaces_dir / "marketplace.json"
    if mp_path.exists():
        try:
            mp = json.loads(mp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"marketplace.json 不是合法 JSON，未覆盖原文件: {mp_path}") from e
        if not isinstance(mp, dict) or "plugins" not in mp:
            raise ValueError(f"marketplace.json 结构异常，未覆盖原文件: {mp_path}")
    else:
        mp = {"name": marketplace, "plugins": [], "version": 1}

    entry = {
        "cachePath": str(cache_base),
        "name": plugin_name,
        "source": "filesystem",
        "version": version,
    }
    # upsert：同名覆盖
    plugins = mp.get("plugins", [])
    for i, p in enumerate(plugins):
        if p.get("name") == plugin_name:
            plugins[i] = entry
            break
    else:
        plugins.append(entry)
    mp["plugins"] = plugins
    mp_path.write_text(json.dumps(mp, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 3. 写 enabledPlugins ──
    cfg = {}
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise ValueError(f"config.json 不是合法 JSON 对象，未覆盖: {config_path}")
    enabled = cfg.setdefault("enabledPlugins", {})
    enabled[f"{plugin_name}@{marketplace}"] = True
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="注册 multimodal-proxy-plugin 到 ZCode")
    ap.add_argument("--plugin-root", required=True)
    ap.add_argument("--marketplace", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--plugin-name", default="multimodal-proxy-plugin")
    ap.add_argument("--cli-root", default=os.path.expanduser("~/.zcode/cli"))
    args = ap.parse_args()

    register(
        cli_root=args.cli_root,
        plugin_root=args.plugin_root,
        plugin_name=args.plugin_name,
        marketplace=args.marketplace,
        version=args.version,
    )
    print(f"✓ 已注册到 ZCode（{args.plugin_name}@{args.marketplace}）")
    print(f"  cache: {os.path.expanduser(args.cli_root)}/plugins/cache/{args.marketplace}/{args.plugin_name}/{args.version}")
    print("  重启 ZCode 生效；用 `zcode plugins list` 验证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
