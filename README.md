# multimodal-proxy-plugin

为纯文本主模型（如 glm-5.2、deepseek-v4）提供多模态外包能力的 Codex 插件。

当主模型不支持图像/视频/音频时，通过内置 MCP 把多模态任务转交给外部多模态模型
（OpenAI 兼容 API，如火山引擎 doubao-vision）处理，再把文字结果回填给主模型。
配套 skill 规范了激活规则：仅纯文本主模型且有多模态需求时才启用。

## 架构

```
用户（纯文本主模型 glm-5.2）
  │  遇到"分析这张图" → skill 判断主模型是纯文本 → 调用 MCP 工具
  ▼
multimodal-proxy MCP（mcp/multimodal_proxy.py）
  │  读配置 + keychain key → 调用外部多模态模型 API
  ▼
外部多模态模型（火山引擎 doubao-seed-2.0-pro 等）
  │  返回图片/视频/音频分析结果
  ▼
文字结果回填给主模型
```

## 组成

| 部分 | 路径 | 作用 |
|---|---|---|
| MCP server | `mcp/multimodal_proxy.py` | 通用多模态代理，4 个工具 |
| Skill | `skills/multimodal-proxy/SKILL.md` | 激活规则与使用规范 |
| 安装脚本 | `scripts/install.sh` | 配置 + keychain + 依赖 + 注册 |
| 配置工具 | `scripts/configure.py` | 写配置文件 + 管理 key 存储 |
| 插件清单 | `.codex-plugin/plugin.json` | Codex 插件元数据 |
| MCP 声明 | `.mcp.json` | 声明 MCP server（install.sh 生成） |

## MCP 工具

| 工具 | 能力 |
|---|---|
| `understand_image` | 图像分析 / OCR / 图表解读 / UI 审查 |
| `understand_video` | 视频内容分析 |
| `transcribe_audio` | 音频转字幕 / 语音转写 |
| `generate_image` | 文字生成图片 |

工具共享参数：`model`（覆盖默认模型）、`provider`（覆盖默认 provider）。
媒体输入支持本地文件路径（自动转 base64）或 http(s) URL。

## 安装

```bash
cd multimodal-proxy-plugin
bash scripts/install.sh
```

脚本会交互式引导输入：
- provider 名称（如 `volcengine`）
- base_url（如 `https://ark.cn-beijing.volces.com/api/coding/v3`）
- api_key（mac 上优先存入 keychain）
- 各能力模型名（vision 必填，如 `doubao-seed-2.0-pro`）

完成后自动：创建 venv + 装依赖 → 写配置 → 生成 .mcp.json → 注册到 Codex。

## 配置文件

`~/.config/multimodal-proxy/config.json`：

```json
{
  "default_provider": "volcengine",
  "providers": {
    "volcengine": {
      "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
      "api_key_store": "keychain",
      "keychain_service": "multimodal-proxy",
      "keychain_account": "volcengine",
      "models": {
        "vision": "doubao-seed-2.0-pro"
      }
    }
  }
}
```

api_key 存储优先级：mac keychain > 环境变量 > 配置文件明文。

## skill 激活规则

1. 主模型是纯文本模型（glm-5.2、deepseek-v4 等）且有多模态需求 → **激活** MCP
2. 主模型是多模态模型（GPT-4o、Claude、Gemini、doubao-vision 等）→ **不激活**，
   除非用户显式要求外包
3. 不确定主模型是否多模态 → 默认激活（纯文本模型直接处理媒体会失败）

## 测试

以"主模型 glm-5.2 + 图像分析转火山引擎 doubao-seed-2.0-pro"为例：

1. 运行 `bash scripts/install.sh`，配置 volcengine provider + ARK_API_KEY + vision 模型
2. 在 Codex 中配置主模型为 glm-5.2（火山引擎）
3. 新开线程，发送："分析这张图片 /tmp/multimodal_proxy_test.png"
4. 预期：主模型调用 `understand_image` 工具 → doubao 返回图片描述

直接验证 MCP（不依赖 Codex 主模型）：

```bash
# 生成测试图
python3 -c "..."  # 或用任意 png

# 通过 stdio 调用 understand_image 验证
```
