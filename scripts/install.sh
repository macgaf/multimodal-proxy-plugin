#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# multimodal-proxy 插件安装脚本
# 功能：创建虚拟环境 + 安装依赖 + 交互配置多模态模型 + 生成 .mcp.json
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
read -rp "provider 名称 [volcengine]: " PROVIDER
PROVIDER="${PROVIDER:-volcengine}"

read -rp "base_url [https://ark.cn-beijing.volces.com/api/v3]: " BASE_URL
BASE_URL="${BASE_URL:-https://ark.cn-beijing.volces.com/api/v3}"

# api_key 存储方式（mac 优先 keychain）
USE_KEYCHAIN=""
if [ "$(uname)" = "Darwin" ]; then
  read -rp "检测到 macOS，是否将 api_key 存入 keychain？(Y/n): " kc
  case "${kc:-Y}" in
    [Yy]*) USE_KEYCHAIN="--keychain"; echo "→ 将使用 keychain 存储 api_key";;
    *) echo "→ api_key 将以明文存入配置文件（不推荐）";;
  esac
fi

read -rp "图像理解模型 (vision) [doubao-Seed-2.0-pro]: " VISION_MODEL
VISION_MODEL="${VISION_MODEL:-doubao-Seed-2.0-pro}"
read -rp "视频理解模型 (video，可留空): " VIDEO_MODEL
read -rp "音频理解模型 (audio，可留空): " AUDIO_MODEL
read -rp "图像生成模型 (image_generation，可留空): " IMAGE_GEN_MODEL

# 4. 写入配置（非交互模式，参数传入）
echo "→ 写入配置"
CONFIG_ARGS=(--provider "$PROVIDER" --base-url "$BASE_URL"
  --vision-model "$VISION_MODEL" --set-default)
[ -n "$VIDEO_MODEL" ] && CONFIG_ARGS+=(--video-model "$VIDEO_MODEL")
[ -n "$AUDIO_MODEL" ] && CONFIG_ARGS+=(--audio-model "$AUDIO_MODEL")
[ -n "$IMAGE_GEN_MODEL" ] && CONFIG_ARGS+=(--image-gen-model "$IMAGE_GEN_MODEL")

if [ -n "$USE_KEYCHAIN" ]; then
  # keychain 模式：交互输入 key 后传入
  read -rsp "api_key: " API_KEY; echo
  [ -z "$API_KEY" ] && { echo "✗ api_key 不能为空"; exit 1; }
  "$PY" "$PLUGIN_ROOT/scripts/configure.py" "${CONFIG_ARGS[@]}" \
    $USE_KEYCHAIN --keychain-account "$PROVIDER" --api-key "$API_KEY"
else
  # 非 keychain：让 configure.py 交互输入 key
  "$PY" "$PLUGIN_ROOT/scripts/configure.py" "${CONFIG_ARGS[@]}"
fi

# 5. 生成 .mcp.json（注入本机绝对路径）
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

# 6. 完成提示
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✓ 安装完成"
echo "═══════════════════════════════════════════════════════════"
echo "配置文件: ~/.config/multimodal-proxy/config.json"
echo "MCP 配置: $PLUGIN_ROOT/.mcp.json"
echo ""
# 7. 注册到 Codex（软链到 ~/plugins + 更新 personal marketplace + 安装）
echo "→ 注册插件到 Codex"
mkdir -p "$HOME/plugins" "$HOME/.agents/plugins"
ln -sfn "$PLUGIN_ROOT" "$HOME/plugins/multimodal-proxy-plugin"
echo "✓ 已软链到 ~/plugins/multimodal-proxy-plugin"
if command -v codex >/dev/null 2>&1; then
  codex plugin add multimodal-proxy-plugin@personal 2>/dev/null || echo "  (插件已安装或 marketplace 需手动初始化)"
  echo "✓ 已注册到 Codex，新开 Codex 线程即可使用"
else
  echo "⚠ 未找到 codex CLI，请在 Codex 应用中通过 /plugins 安装"
fi
echo ""
echo "如需重新配置模型，再次运行：bash scripts/install.sh"
