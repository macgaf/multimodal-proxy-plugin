---
name: multimodal-proxy
description: >
  通过 multimodal-proxy MCP 把图像/视频/音频处理外包给外部多模态模型（OpenAI 兼容
  API）。仅当当前主模型是纯文本模型（不支持多模态）且用户提出多模态处理需求时激活：
  图像分析、OCR 文字提取、多图对比、视频分析、图表解读、UI 审查等。触发词：分析图片/
  看图/识别图像/OCR/截图分析/多图对比/视频内容/图表解读，或用户给出图片/视频/音频文件
  路径并要求处理其内容。不触发的情况：当前主模型本身支持多模态（如 GPT-4o/4.1/5、
  Claude 3.5+、Gemini、doubao-vision、qwen-vl、glm-4v 等视觉/音频模型），此时由主模型
  直接处理；除非用户显式声明"用外部模型处理""强制外包""用 doubao 分析"等。不确定主
  模型是否多模态时，默认激活本 skill（纯文本模型直接处理媒体会失败）。
---

# multimodal-proxy 使用规范

通过 `multimodal-proxy` MCP 的 `process_multimodal` 工具，把多模态任务外包给配置好的
外部多模态模型，再把文字结果回填给当前主模型。适用场景：主模型是纯文本模型
（如 glm-5.2、deepseek-v4 等），无法直接理解图像/视频/音频。

## 激活决策（必须先判断）

1. **判断当前主模型是否多模态**
   - 已知多模态模型：GPT-4o / GPT-4.1 / GPT-5、Claude 3.5+、Gemini 全系、
     doubao-vision、qwen-vl、glm-4v、Kimi-vision 等
   - 已知纯文本模型：glm-5.2、deepseek-v4-flash/pro、多数纯文本 LLM
   - 不确定 → 视为纯文本（默认激活本 skill）

2. **若主模型是多模态模型**
   - 默认由主模型直接处理，**不调用** multimodal-proxy
   - 仅当用户显式要求"用外部模型""强制外包""用 doubao 分析"时才调用

3. **若主模型是纯文本模型，且用户有多模态需求**
   - **必须**调用 `process_multimodal`；不要尝试让纯文本主模型直接"看"图

## 工具

### process_multimodal（核心工具）

接收任意数量的图片/视频/音频 + 提示词，按顺序组装成多模态请求交给模型处理。

参数：
- `media`（必填）：媒体文件列表，每个元素是本地路径或 http(s) URL
  - 图片：jpg/png/gif/webp/bmp/svg
  - 视频：mp4/mov/webm/avi/mkv
  - 音频：mp3/wav/m4a/flac/aac/ogg
  - 可混用多种类型
- `prompts`（可选）：提示词列表，0~n 条，作为任务指令在媒体之前提交
- `model`（可选）：覆盖默认模型
- `provider`（可选）：覆盖默认 provider

用法示例：
- 单图分析：`process_multimodal(["/path/img.png"], ["描述这张图"])`
- 多图对比：`process_multimodal(["/a.png", "/b.png"], ["对比这两张图"])`
- OCR 提取：`process_multimodal(["/scan.jpg"], ["提取图中所有文字", "保留原始格式"])`
- 图表解读：`process_multimodal(["/chart.png"], ["解读这个图表的数据"])`

### generate_image（图像生成）

根据文字提示词生成图片。需在配置中设置 image_generation 模型。

## 使用要点

- **媒体输入**：本地文件路径（自动转 base64）或 http(s) URL 均可。
- **prompts 要具体**：OCR 用"提取图中所有文字"；物体识别用"列出图中物体及颜色"。
- **结果回填**：工具返回的是文字，直接用于后续回答。
- **错误处理**：若报"未找到配置文件"或"无法获取 api_key"，提示用户运行
  `bash scripts/install.sh` 重新配置。
- **模型能力差异**：doubao-seed-2.0-pro（260215）实测支持多图和视频，
  不支持音频。doubao-seed-2-0-mini/lite 260428 元数据标注含 audio，
  但 Coding Plan key 实测仍被拒——需在控制台确认音频开通状态。

## 配置

- 配置文件：`~/.config/multimodal-proxy/config.json`
- api_key：mac 默认 keychain（service=multimodal-proxy，account=provider名）
- 重新配置：`bash scripts/install.sh`
