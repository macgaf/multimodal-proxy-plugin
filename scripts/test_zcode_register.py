#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zcode_register 单测：用临时目录模拟 ~/.zcode/cli/，验证注册逻辑与幂等性。"""
import json
import os
import sys
import tempfile
from pathlib import Path

# 让脚本能 import 同目录的 zcode_register
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zcode_register import register  # noqa: E402


def _setup_fake_cli(tmpdir: Path) -> Path:
    """在 tmpdir 下建出 ~/.zcode/cli/ 的目录骨架。"""
    cli = tmpdir / "cli"
    (cli / "plugins" / "cache").mkdir(parents=True)
    (cli / "plugins" / "marketplaces").mkdir(parents=True)
    (cli / "config.json").write_text("{}", encoding="utf-8")
    return cli


def test_register_creates_cache_symlink_and_marketplace_and_enables():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        register(
            cli_root=str(cli),
            plugin_root=str(plugin_root),
            plugin_name="multimodal-proxy-plugin",
            marketplace="personal",
            version="0.1.0",
        )

        # 1. cache symlink 指向插件根
        cache_dir = cli / "plugins" / "cache" / "personal" / "multimodal-proxy-plugin" / "0.1.0"
        assert cache_dir.is_symlink(), "cache 目录应为 symlink"
        # macOS 上 /var -> /private/var，resolve() 会展开符号链接，两端都 resolve 比较
        assert os.readlink(cache_dir) == str(plugin_root.resolve()), "symlink 应指向 plugin_root"

        # 2. marketplace.json 含正确条目
        mp = json.loads((cli / "plugins" / "marketplaces" / "personal" / "marketplace.json").read_text("utf-8"))
        assert mp["name"] == "personal"
        assert mp["version"] == 1
        entry = next(p for p in mp["plugins"] if p["name"] == "multimodal-proxy-plugin")
        assert entry["source"] == "filesystem"
        assert entry["version"] == "0.1.0"
        assert entry["cachePath"] == str(cache_dir)

        # 3. enabledPlugins 写入，且不破坏其他键
        cfg = json.loads((cli / "config.json").read_text("utf-8"))
        assert cfg["enabledPlugins"]["multimodal-proxy-plugin@personal"] is True


def test_register_preserves_existing_enabled_plugins_and_marketplace_entries():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        # 预置已有插件
        cfg_path = cli / "config.json"
        cfg_path.write_text(json.dumps({
            "enabledPlugins": {"superpowers@zcode-plugins-official": True}
        }), encoding="utf-8")
        mp_dir = cli / "plugins" / "marketplaces" / "personal"
        mp_dir.mkdir(parents=True)
        (mp_dir / "marketplace.json").write_text(json.dumps({
            "name": "personal",
            "version": 1,
            "plugins": [{"cachePath": "/other", "name": "other-plugin", "source": "filesystem", "version": "0.2.0"}]
        }), encoding="utf-8")

        register(
            cli_root=str(cli),
            plugin_root=str(plugin_root),
            plugin_name="multimodal-proxy-plugin",
            marketplace="personal",
            version="0.1.0",
        )

        cfg = json.loads(cfg_path.read_text("utf-8"))
        assert cfg["enabledPlugins"]["superpowers@zcode-plugins-official"] is True
        assert cfg["enabledPlugins"]["multimodal-proxy-plugin@personal"] is True

        mp = json.loads((mp_dir / "marketplace.json").read_text("utf-8"))
        names = [p["name"] for p in mp["plugins"]]
        assert "other-plugin" in names
        assert "multimodal-proxy-plugin" in names


def test_register_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        kwargs = dict(
            cli_root=str(cli),
            plugin_root=str(plugin_root),
            plugin_name="multimodal-proxy-plugin",
            marketplace="personal",
            version="0.1.0",
        )
        register(**kwargs)
        register(**kwargs)  # 重跑不应报错

        mp = json.loads((cli / "plugins" / "marketplaces" / "personal" / "marketplace.json").read_text("utf-8"))
        assert len(mp["plugins"]) == 1, "重跑不应产生重复条目"


def test_register_refuses_non_symlink_dir():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        # 预占 cache 目录为真实目录
        cache_dir = cli / "plugins" / "cache" / "personal" / "multimodal-proxy-plugin" / "0.1.0"
        cache_dir.mkdir(parents=True)
        (cache_dir / "dummy").write_text("x", encoding="utf-8")

        try:
            register(
                cli_root=str(cli),
                plugin_root=str(plugin_root),
                plugin_name="multimodal-proxy-plugin",
                marketplace="personal",
                version="0.1.0",
            )
            assert False, "应抛异常拒绝覆盖非 symlink 目录"
        except RuntimeError as e:
            assert "非 symlink" in str(e) or "not a symlink" in str(e).lower()
        # 原内容未被删除
        assert (cache_dir / "dummy").exists()


def test_register_rejects_invalid_marketplace_json():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        mp_dir = cli / "plugins" / "marketplaces" / "personal"
        mp_dir.mkdir(parents=True)
        original = "this is { not json"
        (mp_dir / "marketplace.json").write_text(original, encoding="utf-8")

        try:
            register(
                cli_root=str(cli),
                plugin_root=str(plugin_root),
                plugin_name="multimodal-proxy-plugin",
                marketplace="personal",
                version="0.1.0",
            )
            assert False, "应抛异常拒绝非法 JSON"
        except (ValueError, json.JSONDecodeError):
            pass
        # 原文件未被覆盖
        assert (mp_dir / "marketplace.json").read_text("utf-8") == original


if __name__ == "__main__":
    test_register_creates_cache_symlink_and_marketplace_and_enables()
    test_register_preserves_existing_enabled_plugins_and_marketplace_entries()
    test_register_is_idempotent()
    test_register_refuses_non_symlink_dir()
    test_register_rejects_invalid_marketplace_json()
    print("✓ 全部通过")
