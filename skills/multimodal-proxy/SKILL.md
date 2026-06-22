---
name: multimodal-proxy
description: >
  通过 multimodal-proxy MCP 把图像/视频/音频处理外包给外部多模态模型（OpenAI 兼容
  API）。仅当当前主模型是纯文本模型（不支持多模态）且用户提出多模态处理需求时激活：
  图像分析、OCR 文字提取、视频分析、音频转字幕、图像生成等。触发词：分析图片/看图/
  识别图像/OCR/截图分析/视频内容/音频转文字/生成图片，或用户给出图片/视频/音频文件
  路径并要求处理其内容。不触发的情况：当前主模型本身支持多模态（如 GPT-4o/4.1/5、
  Claude 3.5+、Gemini、doubao-vision、qwen-vl、glm-4v 等视觉/音频模型），此时由主模型
  直接处理；除非用户显式声明"用外部模型处理""强制外包""用 doubao 分析"等。不确定主
  模型是否多模态时，默认激活本 skill（纯文本模型直接处理媒体会失败）。
---

# multimodal-proxy 使用规范

通过 `multimodal-proxy` MCP 的工具，把多模态任务外包给配置好的外部多模态模型，再把
文字结果回填给当前主模型。适用场景：主模型是纯文本模型（如 glm-5.2、deepseek-v4 等），
无法直接理解图像/视频/音频。

## 激活决策（必须先判断）

按顺序判断，决定是否调用 multimodal-proxy 工具：

1. **判断当前主模型是否多模态**
   - 已知多模态模型（自带视觉/音频能力）：GPT-4o / GPT-4.1 / GPT-5、Claude 3.5+ /
     Sonnet/Opus、Gemini 全系、doubao-vision、qwen-vl、glm-4v、Kimi-vision 等
   - 已知纯文本模型：glm-5.2、deepseek-v4-flash/pro、多数纯文本 LLM
   - 不确定 → 视为纯文本（默认激活本 skill）

2. **若主模型是多模态模型**
   - 默认由主模型直接处理，**不调用** multimodal-proxy
   - 仅当用户显式要求"用外部模型""强制外包""用 doubao/其他模型分析"时，才调用

3. **若主模型是纯文本模型，且用户有多模态需求**
   - **必须**调用 multimodal-proxy 工具；不要尝试让纯文本主模型直接"看"图

## 工具速查

所有工具共享参数：`model`（覆盖默认模型）、`provider`（覆盖默认 provider）。

| 任务 | 工具 | 关键参数 |
|---|---|---|
| 图像分析 / OCR / 图表解读 / UI 审查 | `understand_image` | `image`(路径或URL), `prompt`(问题) |
| 视频内容分析 | `understand_video` | `video`(路径或URL), `prompt` |
| 音频转字幕 / 语音转写 | `transcribe_audio` | `audio`(路径或URL), `prompt` |
| 文字生成图片 | `generate_image` | `prompt`, `size`(可选) |

## 使用要点

- **媒体输入**：本地文件路径（自动转 base64）或 http(s) URL 均可。
- **prompt 要具体**：OCR 用"提取图中所有文字"；物体识别用"列出图中物体及颜色"；
  UI 审查用"这是 UI 截图，评估布局与可读性问题"。
- **结果回填**：工具返回的是文字，直接用于后续回答；不要把 base64 塞回主模型。
- **错误处理**：若工具报"未找到配置文件"或"无法获取 api_key"，提示用户运行
  `bash scripts/install.sh` 重新配置。

## 配置与排错

- 配置文件：`~/.config/multimodal-proxy/config.json`（含 base_url、models、key 存储方式）
- api_key 存储：mac 默认 keychain（service=`multimodal-proxy`，account=provider名）；
  其他平台用环境变量或配置文件明文。
- 重新配置模型/key：`bash scripts/install.sh`
- 测试 MCP 是否就绪：在 Codex 中问"分析这张图 /path/to/test.png"，观察是否调用工具。
