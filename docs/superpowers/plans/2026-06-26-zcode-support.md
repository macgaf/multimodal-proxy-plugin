# multimodal-proxy-plugin ZCode 渠道支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `.zcode-plugin` 打包渠道并改造 install.sh，使本机 ZCode（GLM-5.2 纯文本主模型）能一键装上并用起 multimodal-proxy MCP，同时保留现有 Codex/Claude 渠道。

**Architecture:** 新增 `.zcode-plugin/plugin.json`（MCP server 内联，用 `${ZCODE_PLUGIN_ROOT}` 变量路径，与官方 android-emulator/ios-simulator 同构）。新增 `scripts/zcode_register.py` 用 Python 完成 ZCode 的三步注册（cache symlink、marketplace.json 合并、enabledPlugins 写入），被 install.sh 的"探测宿主"分支调用。文案全面去 Codex 化为通用措辞。

**Tech Stack:** Bash (install.sh)、Python 3 (zcode_register.py 及测试)、JSON 清单。无新依赖。

**Spec:** `docs/superpowers/specs/2026-06-26-zcode-support-design.md`

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `.zcode-plugin/plugin.json` | 新建 | ZCode 清单：mcpServers 内联 + 变量路径，skills 指向 skills/ |
| `scripts/zcode_register.py` | 新建 | ZCode 注册逻辑（cache symlink + marketplace.json 合并 + enabledPlugins 写入） |
| `scripts/test_zcode_register.py` | 新建 | zcode_register 的单测（含幂等 + 错误路径） |
| `scripts/install.sh` | 修改 | 第 8 步改为探测宿主（--target zcode\|codex\|auto），ZCode 分支调用 zcode_register.py |
| `mcp/multimodal_proxy.py` | 修改 | docstring/工具描述去 Codex 化 |
| `skills/multimodal-proxy/SKILL.md` | 修改 | 去 Codex 化措辞 |
| `scripts/configure.py` | 修改 | 一句提示文案去 Codex 化 |
| `README.md` | 修改 | badge + 安装节 ZCode 分支 + 去 Codex 化措辞 |

---

### Task 1: 新建 `.zcode-plugin/plugin.json`

**Files:**
- Create: `.zcode-plugin/plugin.json`

- [ ] **Step 1: 创建清单文件**

```json
{
  "name": "multimodal-proxy-plugin",
  "version": "0.1.0",
  "description": "为纯文本主模型（如 glm-5.2、deepseek-v4）提供多模态外包能力：通过 MCP 把图像分析、OCR、视频分析、音频转字幕、图像生成转交给外部多模态模型。",
  "author": {
    "name": "local"
  },
  "license": "MIT",
  "keywords": [
    "multimodal",
    "vision",
    "ocr",
    "audio",
    "image-generation",
    "mcp"
  ],
  "skills": "skills",
  "mcpServers": {
    "multimodal-proxy": {
      "command": "${ZCODE_PLUGIN_ROOT}/.venv/bin/python",
      "args": ["${ZCODE_PLUGIN_ROOT}/mcp/multimodal_proxy.py"],
      "cwd": "${ZCODE_PROJECT_DIR}"
    }
  },
  "interface": {
    "displayName": "多模态代理",
    "shortDescription": "为纯文本模型外包图像/视频/音频处理",
    "longDescription": "当主模型不支持多模态时，通过 MCP 工具把图像分析、OCR、视频分析、音频转字幕、图像生成外包给配置好的外部多模态模型（OpenAI 兼容 API）。附带的 skill 规范了激活规则：仅纯文本主模型且有多模态需求时才启用。",
    "developerName": "local",
    "category": "Productivity",
    "capabilities": [
      "Read"
    ],
    "defaultPrompt": [
      "分析这张图片",
      "提取图片中的文字(OCR)",
      "把这段音频转成字幕"
    ]
  }
}
```

- [ ] **Step 2: 校验 JSON 合法**

Run: `python3 -m json.tool .zcode-plugin/plugin.json > /dev/null`
Expected: 无输出，退出码 0

- [ ] **Step 3: Commit**

```bash
git add .zcode-plugin/plugin.json
git commit -m "feat: 新增 .zcode-plugin/plugin.json ZCode 清单（内联 MCP + 变量路径）"
```

---

### Task 2: 新建 `scripts/zcode_register.py` —— 失败测试先行

本任务先写测试（TDD）。测试用一个临时目录模拟 `~/.zcode/cli/`，调用注册函数，断言三步注册正确且幂等。

**Files:**
- Create: `scripts/test_zcode_register.py`
- Create: `scripts/zcode_register.py`（本步只建空壳让测试能 import 并失败）

- [ ] **Step 1: 写失败测试**

Create `scripts/test_zcode_register.py`:

```python
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
        assert os.readlink(cache_dir) == str(plugin_root), "symlink 应指向 plugin_root"

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
```

- [ ] **Step 2: 建空壳实现让测试能 import**

Create `scripts/zcode_register.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""占位：TDD 空壳，下个任务实现。"""


def register(*args, **kwargs):
    raise NotImplementedError
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python3 scripts/test_zcode_register.py`
Expected: 失败，`NotImplementedError`

- [ ] **Step 4: Commit（测试先行）**

```bash
git add scripts/test_zcode_register.py scripts/zcode_register.py
git commit -m "test: 新增 zcode_register 注册逻辑测试（含幂等与错误路径）"
```

---

### Task 3: 实现 `scripts/zcode_register.py`

**Files:**
- Modify: `scripts/zcode_register.py`（整体替换）

- [ ] **Step 1: 实现注册函数**

Replace entire content of `scripts/zcode_register.py` with:

```python
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
```

- [ ] **Step 2: 运行测试确认全绿**

Run: `python3 scripts/test_zcode_register.py`
Expected: 输出 `✓ 全部通过`，退出码 0

- [ ] **Step 3: Commit**

```bash
git add scripts/zcode_register.py
git commit -m "feat: 实现 zcode_register.py ZCode 三步注册逻辑"
```

---

### Task 4: 改造 `scripts/install.sh` 增加 ZCode 注册分支

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: 替换第 8 步注册逻辑**

将 `scripts/install.sh` 中从 `# 8. 注册到 Codex` 到文件末尾 `echo ""` 之前（即第 121-139 行那段）整体替换。

原内容（要被替换的起始锚点）：

```bash
# 8. 注册到 Codex
echo "→ 注册插件到 Codex"
mkdir -p "$HOME/plugins" "$HOME/.agents/plugins"
ln -sfn "$PLUGIN_ROOT" "$HOME/plugins/multimodal-proxy-plugin"
if command -v codex >/dev/null 2>&1; then
  codex plugin add multimodal-proxy-plugin@personal 2>/dev/null || echo "  (插件已安装或需手动通过 /plugins 安装)"
  echo "✓ 已注册到 Codex，新开 Codex 线程即可使用"
else
  echo "⚠ 未找到 codex CLI，请在 Codex 应用中通过 /plugins 安装"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✓ 安装完成"
echo "═══════════════════════════════════════════════════════════"
echo "配置文件: ~/.config/multimodal-proxy/config.json"
echo "MCP 配置: $PLUGIN_ROOT/.mcp.json"
echo ""
echo "如需重新配置模型，再次运行：bash scripts/install.sh"
```

替换为：

```bash
# 8. 探测宿主并注册
#    --target codex|zcode|auto（默认 auto）：auto 优先 codex CLI，其次 ~/.zcode/cli/
TARGET="auto"
for a in "$@"; do
  case "$a" in
    --target) shift_next=1 ;;
    --target=*) TARGET="${a#--target=}" ;;
    codex|zcode|auto) [ "${shift_next:-0}" = "1" ] && TARGET="$a" && shift_next=0 ;;
  esac
done

ZCODE_CLI="$HOME/.zcode/cli"
HAS_CODEX="no"; command -v codex >/dev/null 2>&1 && HAS_CODEX="yes"
HAS_ZCODE="no"; [ -d "$ZCODE_CLI" ] && HAS_ZCODE="yes"

# 决定目标
if [ "$TARGET" = "auto" ]; then
  if [ "$HAS_CODEX" = "yes" ]; then TARGET="codex"
  elif [ "$HAS_ZCODE" = "yes" ]; then TARGET="zcode"
  else TARGET="none"
  fi
fi

case "$TARGET" in
  codex)
    if [ "$HAS_CODEX" != "yes" ]; then
      echo "✗ --target codex 但未找到 codex CLI"; exit 1
    fi
    echo "→ 注册插件到 Codex"
    mkdir -p "$HOME/plugins" "$HOME/.agents/plugins"
    ln -sfn "$PLUGIN_ROOT" "$HOME/plugins/multimodal-proxy-plugin"
    codex plugin add multimodal-proxy-plugin@personal 2>/dev/null || echo "  (插件已安装或需手动通过 /plugins 安装)"
    echo "✓ 已注册到 Codex，新开 Codex 线程即可使用"
    ;;
  zcode)
    if [ "$HAS_ZCODE" != "yes" ]; then
      echo "✗ --target zcode 但未检测到 ZCode 安装（~/.zcode/cli/ 不存在）"; exit 1
    fi
    echo "→ 注册插件到 ZCode"
    MARKETPLACE="${ZCODE_MARKETPLACE:-personal}"
    VERSION="$(python3 -c "import json;print(json.load(open('$PLUGIN_ROOT/.zcode-plugin/plugin.json'))['version'])")"
    "$PY" "$PLUGIN_ROOT/scripts/zcode_register.py" \
      --plugin-root "$PLUGIN_ROOT" \
      --marketplace "$MARKETPLACE" \
      --version "$VERSION" \
      --cli-root "$ZCODE_CLI"
    echo "✓ 已注册到 ZCode，重启 ZCode 后即可使用"
    ;;
  none)
    echo "ℹ 未检测到 codex CLI 或 ZCode（~/.zcode/cli/），跳过自动注册"
    echo "  MCP 配置已生成: $PLUGIN_ROOT/.mcp.json"
    echo "  可手动将该 MCP server 配置加入你的 Agent 客户端"
    ;;
esac

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✓ 安装完成"
echo "═══════════════════════════════════════════════════════════"
echo "配置文件: ~/.config/multimodal-proxy/config.json"
echo "MCP 配置: $PLUGIN_ROOT/.mcp.json"
[ "$TARGET" = "zcode" ] && echo "ZCode 清单: $PLUGIN_ROOT/.zcode-plugin/plugin.json"
echo ""
echo "如需重新配置模型，再次运行：bash scripts/install.sh"
echo "指定宿主：bash scripts/install.sh --target zcode|codex"
```

- [ ] **Step 2: 语法检查**

Run: `bash -n scripts/install.sh`
Expected: 无输出，退出码 0

- [ ] **Step 3: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: install.sh 探测宿主（--target zcode|codex|auto），新增 ZCode 注册分支"
```

---

### Task 5: MCP server docstring / 工具描述去 Codex 化

**Files:**
- Modify: `mcp/multimodal_proxy.py`

- [ ] **Step 1: 改 save_clipboard_to_file 工具描述**

在 `mcp/multimodal_proxy.py` 第 390-404 行，将：

```python
    用于绕过 Codex 对纯文本模型的图片输入硬拦截：用户 Ctrl-V 粘贴截图会被拦截，
    但截图仍在系统剪贴板中。本工具从剪贴板读取图片数据，保存为临时 PNG 文件，
    返回文件路径，供后续 process_multimodal 工具分析。
```

改为：

```python
    用于绕过纯文本 Agent 主模型对图片输入的硬拦截：用户 Ctrl-V 粘贴截图会被拦截，
    但截图仍在系统剪贴板中。本工具从剪贴板读取图片数据，保存为临时 PNG 文件，
    返回文件路径，供后续 process_multimodal 工具分析。
```

同段第 404 行，将：

```python
      2. 在 Codex 里输入文本指令，如"分析一下我刚截的屏"
```

改为：

```python
      2. 在 Agent 客户端里输入文本指令，如"分析一下我刚截的屏"
```

- [ ] **Step 2: 改模块 docstring 第 4 行**

将第 4 行附近的：

```python
"""multimodal-proxy MCP server

通用多模态代理：通过火山引擎 Coding Plan API 将多模态任务外包给支持视觉的模型
```

改为：

```python
"""multimodal-proxy MCP server

通用多模态代理：通过 OpenAI 兼容 API 将多模态任务外包给支持视觉的模型
```

（注：模块 docstring 第 5 行原为火山引擎专属描述，与 README 已通用化的定位一致地改为通用措辞。）

- [ ] **Step 3: 改第 390 行附近另一处描述**

将文件顶部注释第 9 行（`save_clipboard_to_file：读系统剪贴板，图片落盘返回路径（绕过 Ctrl-V 硬拦截）`）保持不变（已通用）。确认无其他 "Codex" 残留：

Run: `grep -n "Codex" mcp/multimodal_proxy.py`
Expected: 无输出（无残留）。若仍有，逐一改为通用措辞。

- [ ] **Step 4: Commit**

```bash
git add mcp/multimodal_proxy.py
git commit -m "refactor: MCP server docstring/工具描述去 Codex 化为通用措辞"
```

---

### Task 6: SKILL.md 与 configure.py 去 Codex 化

**Files:**
- Modify: `skills/multimodal-proxy/SKILL.md`
- Modify: `scripts/configure.py`

- [ ] **Step 1: SKILL.md 去 Codex 化**

在 `skills/multimodal-proxy/SKILL.md` 中，将：

```
**用途**：绕过 Codex 对纯文本模型的图片输入硬拦截。用户 Ctrl-V 粘贴截图会被拦截，
但截图仍在系统剪贴板中。本工具从剪贴板读出图片，落盘为文件，返回路径供后续分析。
```

改为：

```
**用途**：绕过纯文本 Agent 主模型对图片输入的硬拦截。用户 Ctrl-V 粘贴截图会被拦截，
但截图仍在系统剪贴板中。本工具从剪贴板读出图片，落盘为文件，返回路径供后续分析。
```

- [ ] **Step 2: 确认 SKILL.md 无其他 Codex 残留**

Run: `grep -n "Codex" skills/multimodal-proxy/SKILL.md`
Expected: 无输出。若残留，改为通用措辞。

- [ ] **Step 3: configure.py 提示文案去 Codex 化**

在 `scripts/configure.py` 第 206 行，将：

```python
            print(f"✓ 配置已写入，请在运行 Codex 前设置环境变量：")
```

改为：

```python
            print(f"✓ 配置已写入，请在运行 Agent 客户端前设置环境变量：")
```

- [ ] **Step 4: Commit**

```bash
git add skills/multimodal-proxy/SKILL.md scripts/configure.py
git commit -m "refactor: SKILL.md 与 configure.py 去 Codex 化措辞"
```

---

### Task 7: README.md 适配 ZCode（badge + 安装节 + 去Codex化）

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 顶部增加 ZCode badge**

在 `README.md` 第 8 行（Codex Plugin badge 行）之后新增一行：

```markdown
[![ZCode Plugin](https://img.shields.io/badge/ZCode-Plugin-green)](.zcode-plugin/plugin.json)
```

- [ ] **Step 2: "组成"表新增 .zcode-plugin 行**

在 README 的"组成"表（约第 70-75 行）中，在 `.claude-plugin/marketplace.json` 相关说明后、`| MCP server |` 行之前，新增一行。找到：

```markdown
| 部分 | 路径 | 作用 |
|---|---|---|
| MCP server | `mcp/multimodal_proxy.py` | 通用多模态代理，3 个工具 |
```

改为：

```markdown
| 部分 | 路径 | 作用 |
|---|---|---|
| ZCode 清单 | `.zcode-plugin/plugin.json` | ZCode 插件清单（内联 MCP + 变量路径） |
| MCP server | `mcp/multimodal_proxy.py` | 通用多模态代理，3 个工具 |
```

- [ ] **Step 3: 安装节增加 ZCode 分支说明**

在 README 安装节（`## 安装` 下，`bash scripts/install.sh` 代码块之后），找到：

```markdown
交互式引导输入 provider、base_url、模型名，以及 **api_key 存储方式（三选一）**：
```

在其**之前**插入一段宿主探测说明：

```markdown
安装脚本自动探测宿主（可通过 `--target zcode|codex|auto` 指定，默认 auto）：

| 宿主 | 探测条件 | 注册动作 |
|---|---|---|
| Codex | 存在 `codex` CLI | symlink + `codex plugin add` |
| ZCode | 存在 `~/.zcode/cli/` | symlink 进 cache + 写 marketplace.json + enabledPlugins |
| 无 | 两者都没有 | 仅生成 `.mcp.json`，提示手动配置 |

```

- [ ] **Step 4: 去 Codex 化措辞**

在 README 第 38-39 行的对比表，将：

```markdown
| 截屏穿透 | 假定图片能直接传入 | 剪贴板落盘绕过 Codex 对纯文本模型的硬拦截 |
| 智能激活 | 常驻 | 仅纯文本主模型才激活，多模态模型自动让位 |
```

改为：

```markdown
| 截屏穿透 | 假定图片能直接传入 | 剪贴板落盘绕过纯文本 Agent 主模型对图片输入的硬拦截 |
| 智能激活 | 常驻 | 仅纯文本主模型才激活，多模态模型自动让位 |
```

第 83-84 行附近，将：

```markdown
**用途**：绕过 Codex 对纯文本模型的图片输入硬拦截。用户 Ctrl-V 粘贴截图会被拦截，
但截图仍在系统剪贴板中。本工具从剪贴板读取图片，落盘为文件，返回路径供后续分析。
```

改为：

```markdown
**用途**：绕过纯文本 Agent 主模型对图片输入的硬拦截。用户 Ctrl-V 粘贴截图会被拦截，
但截图仍在系统剪贴板中。本工具从剪贴板读取图片，落盘为文件，返回路径供后续分析。
```

- [ ] **Step 5: 确认无其他 Codex 残留**

Run: `grep -n "Codex" README.md`
Expected: 仅第 8 行 badge `[![Codex Plugin]...]` 与安装表里 "存在 `codex` CLI" 这种合理引用，其余无残留。

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: README 增加 ZCode badge/安装分支/组成表，去 Codex 化措辞"
```

---

### Task 8: 回归测试与最终验证

**Files:** 无新建，仅运行验证

- [ ] **Step 1: 跑 zcode_register 单测**

Run: `python3 scripts/test_zcode_register.py`
Expected: `✓ 全部通过`

- [ ] **Step 2: 跑现有激活规则测试**

Run: `.venv/bin/python scripts/test_activation.py`
Expected: 全绿（确认 GLM-5.2 仍判纯文本、多模态模型不激活）

- [ ] **Step 3: 跑现有 dry-run 测试**

Run: `.venv/bin/python scripts/test_dryrun.py`
Expected: 全绿（确认 MCP 工具行为不变）

- [ ] **Step 4: 校验所有 JSON 清单合法**

Run: `python3 -m json.tool .zcode-plugin/plugin.json > /dev/null && python3 -m json.tool .codex-plugin/plugin.json > /dev/null && python3 -m json.tool .claude-plugin/marketplace.json > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: install.sh 语法 + 帮助路径检查**

Run: `bash -n scripts/install.sh && echo SYNTAX_OK`
Expected: `SYNTAX_OK`

- [ ] **Step 6: 手动验证 install.sh --target zcode（需用户在 ZCode 环境）**

Run: `bash scripts/install.sh --target zcode`
Expected: 走完配置后输出 `✓ 已注册到 ZCode`；`zcode plugins list`（在 ZCode 内）可见 multimodal-proxy-plugin 且 enabled。

> 注：此步需交互式输入配置，且需重启 ZCode 验证。若在 CI/无 ZCode 环境跑，跳过并记录。

- [ ] **Step 7: 确认验收标准全部满足**

逐条核对 spec §4 验收标准：
1. `.zcode-plugin/plugin.json` 合法 ✓（Step 4）
2. `--target zcode` 执行成功 ✓（Step 6）
3. `test_zcode_register.py` 全绿 ✓（Step 1）
4. `test_activation.py`、`test_dryrun.py` 全绿 ✓（Step 2-3）
5. README 有 ZCode badge + 安装分支 + 无 Codex 硬拦截残留 ✓（Task 7）

- [ ] **Step 8: 最终 Commit（如有未提交改动）**

```bash
git status --porcelain
# 若有改动则提交；无则跳过
```

---

## Self-Review 结果

（写计划后自查，已修正）

- **Spec 覆盖**：spec §1 每个组件都有对应任务（plugin.json→T1，zcode_register.py→T2/T3，install.sh→T4，mcp/SKILL/configure→T5/T6，README→T7），§3 错误处理（非 symlink 占位、非法 JSON、幂等）在 T2 测试 + T3 实现覆盖，§4 测试在 T8 回归。无遗漏。
- **占位符扫描**：无 TBD/TODO；每个代码步骤都给了完整代码。
- **类型一致**：`register()` 签名在 T2 测试与 T3 实现完全一致（`cli_root, plugin_root, plugin_name, marketplace, version`）；CLI 参数 `--plugin-root/--marketplace/--version/--plugin-name/--cli-root` 在 T3 实现与 T4 调用一致。
