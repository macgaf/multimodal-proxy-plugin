#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# multimodal-proxy 插件安装脚本
# 功能：创建虚拟环境 + 安装依赖 + 交互配置多模态模型 + 生成 .mcp.json + 注册宿主（Codex/ZCode）
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PLUGIN_ROOT/.venv"
PY="$VENV_DIR/bin/python"

echo "═══════════════════════════════════════════════════════════"
echo "  multimodal-proxy 插件安装"
echo "  为纯文本主模型配置多模态外包能力（图像/视频/音频/图像生成）"
echo "═══════════════════════════════════════════════════════════"

# 1. 依赖检查
command -v python3 >/dev/null || { echo "✗ 未找到 python3，请先安装 Python 3.10+"; exit 1; }

# 2. 创建虚拟环境 + 安装依赖
if [ ! -d "$VENV_DIR" ]; then
  echo "→ 创建虚拟环境 $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
echo "→ 安装依赖"
"$VENV_DIR/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
"$VENV_DIR/bin/pip" install -q -r "$PLUGIN_ROOT/requirements.txt"
echo "✓ 依赖已就绪"

# 3. 交互收集配置
echo ""
echo "── 多模态模型配置 ──"
read -rp "provider 名称 [openai]: " PROVIDER
PROVIDER="${PROVIDER:-openai}"

read -rp "base_url [https://api.openai.com/v1]: " BASE_URL
BASE_URL="${BASE_URL:-https://api.openai.com/v1}"

read -rp "图像理解模型 (vision) [gpt-4o]: " VISION_MODEL
VISION_MODEL="${VISION_MODEL:-gpt-4o}"

read -rp "视频理解模型 (video，可留空): " VIDEO_MODEL
read -rp "音频理解模型 (audio，可留空): " AUDIO_MODEL
read -rp "图像生成模型 (image_generation，可留空): " IMAGE_GEN_MODEL

# 4. api_key 存储方式（三选一）
echo ""
echo "── api_key 存储方式 ──"
echo "  1) keychain  —— 存入 macOS 钥匙串，配置文件无明文（推荐，仅 macOS）"
echo "  2) plaintext —— 明文写入配置文件"
echo "  3) env       —— 从环境变量读取，配置文件只记录变量名"

IS_MAC="false"
[ "$(uname)" = "Darwin" ] && IS_MAC="true"

DEFAULT_KEY_STORE="3"
if [ "$IS_MAC" = "true" ]; then
  DEFAULT_KEY_STORE="1"
fi

while true; do
  read -rp "选择 (1/2/3) [$DEFAULT_KEY_STORE]: " KEY_CHOICE
  KEY_CHOICE="${KEY_CHOICE:-$DEFAULT_KEY_STORE}"
  case "$KEY_CHOICE" in
    1)
      if [ "$IS_MAC" != "true" ]; then
        echo "  ✗ 非 macOS 平台不支持 keychain，请选 2 或 3"
        continue
      fi
      KEY_STORE="keychain"
      break
      ;;
    2) KEY_STORE="plaintext"; break ;;
    3) KEY_STORE="env"; break ;;
    *) echo "  无效选择，请输入 1、2 或 3" ;;
  esac
done

# 5. 根据存储方式收集 api_key / 环境变量名
CONFIG_ARGS=(--provider "$PROVIDER" --base-url "$BASE_URL" --vision-model "$VISION_MODEL" --key-store "$KEY_STORE" --keychain-account "$PROVIDER")

if [ "$KEY_STORE" = "env" ]; then
  DEFAULT_ENV_NAME="MULTIMODAL_PROXY_API_KEY_${PROVIDER^^}"
  read -rp "环境变量名 [$DEFAULT_ENV_NAME]: " ENV_NAME
  ENV_NAME="${ENV_NAME:-$DEFAULT_ENV_NAME}"
  CONFIG_ARGS+=(--api-key-env "$ENV_NAME")
  echo "→ 配置文件将记录环境变量名: $ENV_NAME"
  echo "  请在运行 Agent 客户端前设置该环境变量："
  echo "    export $ENV_NAME='你的-api-key'"
  echo "  （建议写入 ~/.zshrc 或 ~/.bashrc）"
else
  read -rsp "api_key: " API_KEY; echo
  [ -z "$API_KEY" ] && { echo "✗ api_key 不能为空"; exit 1; }
  CONFIG_ARGS+=(--api-key-stdin)
fi

# 6. 写入配置
echo "→ 写入配置"
if [ "$KEY_STORE" = "env" ]; then
  "$PY" "$PLUGIN_ROOT/scripts/configure.py" "${CONFIG_ARGS[@]}"
else
  # 通过标准输入传递密钥，避免出现在 Python 的进程参数中。
  printf '%s' "$API_KEY" | "$PY" "$PLUGIN_ROOT/scripts/configure.py" "${CONFIG_ARGS[@]}"
  unset API_KEY
fi

# 7. 生成 .mcp.json（注入本机绝对路径）
echo "→ 生成 .mcp.json"
cat > "$PLUGIN_ROOT/.mcp.json" <<MCPJSON
{
  "mcpServers": {
    "multimodal-proxy": {
      "command": "$PY",
      "args": ["$PLUGIN_ROOT/mcp/multimodal_proxy.py"],
      "cwd": "$PLUGIN_ROOT"
    }
  }
}
MCPJSON
echo "✓ .mcp.json 已生成"

# 8. 探测宿主并注册
#    --target codex|zcode|auto（默认 auto）：auto 优先 codex CLI，其次 ~/.zcode/cli/
TARGET="auto"
shift_next=0
for a in "$@"; do
  case "$a" in
    --target) shift_next=1 ;;
    --target=*) TARGET="${a#--target=}" ;;
    codex|zcode|auto) [ "$shift_next" = "1" ] && TARGET="$a" && shift_next=0 ;;
    *) shift_next=0 ;;
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
    VERSION="$("$PY" -c "import json;print(json.load(open('$PLUGIN_ROOT/.zcode-plugin/plugin.json'))['version'])")"
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
  *)
    echo "✗ 未知 --target: $TARGET（可选值：zcode | codex | auto）"; exit 1
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
