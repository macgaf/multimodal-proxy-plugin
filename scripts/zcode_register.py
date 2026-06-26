#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZCode 插件注册：把插件根路径写入 config.json 的 plugins.dirs。

由 install.sh 的 ZCode 分支调用。CLI 用法：
    zcode_register.py --plugin-root <PLUGIN_ROOT>

注册机制（逆向 zcode.cjs 确认）：
  ZCode 不动态扫描 marketplace 目录发现第三方插件。官方插件来自硬编码的
  Ole 定义数组（带 rootCandidates 相对路径）。第三方插件唯一入口是
  config["plugins"]["dirs"]——用户显式声明的插件目录路径列表，每个 dir
  直接作为 rootPath，marketplace 标记为 "inline"，defaultEnabled=true
  （即默认启用，无需在 enabledPlugins 里显式写）。

  因此注册 = 把 plugin_root 的绝对路径 upsert 进 plugins.dirs（幂等，保留
  其他已声明的目录）。不写 marketplace.json / cache / enabledPlugins。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def register(cli_root: str, plugin_root: str) -> None:
    """把 plugin_root 写入 config.json 的 plugins.dirs。失败抛异常，不破坏已有文件。"""
    cli = Path(cli_root).expanduser()
    config_path = cli / "config.json"
    plugin_root_resolved = str(Path(plugin_root).resolve())

    # 读 config.json
    cfg: dict = {}
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise ValueError(f"config.json 不是合法 JSON 对象，未覆盖: {config_path}")

    plugins_cfg = cfg.setdefault("plugins", {})
    if not isinstance(plugins_cfg, dict):
        raise ValueError(f"config.json 的 plugins 字段不是对象，未覆盖: {config_path}")

    # upsert plugin_root 进 dirs（幂等，去重）
    dirs = plugins_cfg.setdefault("dirs", [])
    if not isinstance(dirs, list):
        raise ValueError(f"config.json 的 plugins.dirs 不是数组，未覆盖: {config_path}")
    if plugin_root_resolved not in dirs:
        dirs.append(plugin_root_resolved)

    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="注册 multimodal-proxy-plugin 到 ZCode（写入 plugins.dirs）")
    ap.add_argument("--plugin-root", required=True)
    ap.add_argument("--cli-root", default=os.path.expanduser("~/.zcode/cli"))
    args = ap.parse_args()

    register(cli_root=args.cli_root, plugin_root=args.plugin_root)
    print(f"✓ 已注册到 ZCode（plugins.dirs += {args.plugin_root}）")
    print("  dirs 插件默认启用，无需 enabledPlugins")
    print("  重启 ZCode 生效；在 ZCode 里用 /plugins list 验证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
