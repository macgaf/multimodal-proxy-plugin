#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zcode_register 单测：用临时目录模拟 ~/.zcode/cli/，验证 plugins.dirs 注册逻辑与幂等性。"""
import json
import sys
import tempfile
from pathlib import Path

# 让脚本能 import 同目录的 zcode_register
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zcode_register import register  # noqa: E402


def _setup_fake_cli(tmpdir: Path) -> Path:
    """在 tmpdir 下建出 ~/.zcode/cli/ 的目录骨架。"""
    cli = tmpdir / "cli"
    cli.mkdir(parents=True)
    (cli / "config.json").write_text("{}", encoding="utf-8")
    return cli


def test_register_adds_plugin_root_to_dirs():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        register(cli_root=str(cli), plugin_root=str(plugin_root))

        cfg = json.loads((cli / "config.json").read_text("utf-8"))
        resolved = str(plugin_root.resolve())
        assert cfg["plugins"]["dirs"] == [resolved], "plugin_root 应被加入 dirs"


def test_register_preserves_existing_dirs_and_other_keys():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        # 预置已有 dirs 和其他键
        cfg_path = cli / "config.json"
        cfg_path.write_text(json.dumps({
            "plugins": {
                "dirs": ["/other/plugin"],
                "enabledPlugins": {"superpowers@zcode-plugins-official": True},
            },
            "recentProjects": ["/some/path"],
        }), encoding="utf-8")

        register(cli_root=str(cli), plugin_root=str(plugin_root))

        cfg = json.loads(cfg_path.read_text("utf-8"))
        resolved = str(plugin_root.resolve())
        assert "/other/plugin" in cfg["plugins"]["dirs"], "应保留已有 dirs 条目"
        assert resolved in cfg["plugins"]["dirs"], "应加入新 plugin_root"
        assert cfg["plugins"]["enabledPlugins"]["superpowers@zcode-plugins-official"] is True
        assert cfg["recentProjects"] == ["/some/path"], "应保留无关顶层键"


def test_register_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        register(cli_root=str(cli), plugin_root=str(plugin_root))
        register(cli_root=str(cli), plugin_root=str(plugin_root))  # 重跑不应报错

        cfg = json.loads((cli / "config.json").read_text("utf-8"))
        resolved = str(plugin_root.resolve())
        assert cfg["plugins"]["dirs"].count(resolved) == 1, "重跑不应产生重复条目"


def test_register_rejects_invalid_config_json():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        cfg_path = cli / "config.json"
        original = "this is { not json"
        cfg_path.write_text(original, encoding="utf-8")

        try:
            register(cli_root=str(cli), plugin_root=str(plugin_root))
            assert False, "应抛异常拒绝非法 JSON"
        except ValueError:
            pass
        # 原文件未被覆盖
        assert cfg_path.read_text("utf-8") == original


def test_register_rejects_non_dict_plugins():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cli = _setup_fake_cli(tmp)
        plugin_root = tmp / "my-plugin"
        plugin_root.mkdir()

        cfg_path = cli / "config.json"
        cfg_path.write_text(json.dumps({"plugins": "not-a-dict"}), encoding="utf-8")

        try:
            register(cli_root=str(cli), plugin_root=str(plugin_root))
            assert False, "应抛异常：plugins 非 dict"
        except ValueError:
            pass


if __name__ == "__main__":
    test_register_adds_plugin_root_to_dirs()
    test_register_preserves_existing_dirs_and_other_keys()
    test_register_is_idempotent()
    test_register_rejects_invalid_config_json()
    test_register_rejects_non_dict_plugins()
    print("✓ 全部通过")
