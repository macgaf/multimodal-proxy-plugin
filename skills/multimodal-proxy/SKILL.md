---
name: multimodal-proxy
description: >
  通过 multimodal-proxy MCP 把图像/视频/音频处理外包给外部多模态模型（OpenAI 兼容
  API）。仅当当前主模型是纯文本模型（不支持多模态）且用户提出多模态处理需求时激活：
  图像分析、OCR 文字提取、多图对比、视频分析、图表解读、UI 审查、截屏分析等。触发词：
  分析图片/看图/识别图像/OCR/截图分析/多图对比/视频内容/图表解读/分析截屏/分析剪贴板/
  刚截的/刚截屏，或用户给出图片/视频/音频文件路径并要求处理其内容，或用户提到剪贴板中
  的截图/图片。不触发的情况：当前主模型本身支持多模态（如 GPT-4o/4.1/5、Claude 3.5+、
  GPT-5.5、Gemini、doubao-vision、qwen-vl、glm-4v 等视觉/音频模型），此时由主模型直接
  处理；除非用户显式声明"用外部模型处理""强制外包""用 doubao 分析"等。无法确认主模型能力时
  不自动激活本 skill，应优先尝试主模型的原生多模态能力或请用户指定处理方式。
---

# multimodal-proxy 使用规范

通过 `multimodal-proxy` MCP 的工具，把多模态任务外包给配置好的外部多模态模型，再把文字
结果回填给当前主模型。仅适用场景：已确认主模型是纯文本模型（如 glm-5.2、deepseek-v4 等），
且无法直接理解图像/视频/音频。

## 激活决策（必须先判断）

1. **先判断当前主模型是否多模态（能力信息优先于模型名称）**
   - 优先读取当前运行时、系统提示或模型元数据声明的输入能力；若标明支持图片、视频或音频，
     即视为多模态。
   - 已知多模态模型：GPT-4o / GPT-4.1 / GPT-5（包括 GPT-5.5 及后续支持多模态的版本）、
     Claude 3.5+、Gemini 全系、doubao-vision、qwen-vl、glm-4v、Kimi-vision 等
   - 已知纯文本模型：glm-5.2、deepseek-v4-flash/pro、多数纯文本 LLM
   - 不确定 → **不得**仅因用户提交媒体或使用触发词而激活本 skill；优先由主模型原生处理，
     或在无法接收媒体时向用户说明能力状态不明并询问是否要使用外部代理。

2. **若主模型是多模态模型**
   - 默认由主模型直接处理，**不调用** multimodal-proxy
   - 仅当用户显式要求"用外部模型""强制外包""用 doubao 分析"时才调用

3. **若主模型已确认是纯文本模型，且用户有多模态需求**
   - **必须**调用 multimodal-proxy 工具；不要尝试让纯文本主模型直接"看"图

4. **优先级**
   - 用户明确要求外部代理 > 已确认纯文本模型 > 主模型原生多模态能力 > 能力不明时不自动代理。

## 工具

### save_clipboard_to_file（剪贴板落盘）

读取系统剪贴板内容，如果是图片则保存为临时 PNG 文件并返回路径。

**跨平台支持**：macOS（osascript）、Windows（PowerShell）、Linux（wl-paste / xclip）。

**用途**：绕过 Codex 对纯文本模型的图片输入硬拦截。用户 Ctrl-V 粘贴截图会被拦截，
但截图仍在系统剪贴板中。本工具从剪贴板读出图片，落盘为文件，返回路径供后续分析。

**无参数**。

**返回值**：
- 图片：返回文件路径（如 `/tmp/mmp-clip-1234567890.png`）
- 文本：返回 `clipboard_text: <内容>`（剪贴板里是文字而非图片）
- 空：返回提示信息（剪贴板为空或不含图片）

**调用时机**：当用户说"分析一下我刚截的屏""看看剪贴板里的截图""分析截屏"等，
且当前无法通过 Ctrl-V 粘贴图片时，先调用本工具获取文件路径。

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

## 工作流

### 场景一：用户给出文件路径

仅在主模型已确认是纯文本模型，或用户明确要求外部代理时：用户直接提供图片/视频/音频文件路径
→ 直接调用 `process_multimodal` 分析。否则由主模型原生处理。

### 场景二：用户提到"截屏/截图/剪贴板"但没给路径

仅在主模型已确认是纯文本模型，或用户明确要求外部代理时，用户说"分析一下我刚截的屏"
""看看剪贴板里的图"等：

1. **先调用 `save_clipboard_to_file`** → 获取临时文件路径
2. 如果返回的是文件路径（以 `/tmp/mmp-clip-` 开头）→ **再调用 `process_multimodal`**，
   传入该路径 + 用户的分析需求作为 prompts
3. 如果返回 `clipboard_text:` → 告诉用户剪贴板里是文字不是图片
4. 如果返回"剪贴板为空" → 提示用户先截图到剪贴板
   - macOS：Ctrl-Shift-Cmd-4
   - Windows：Win-Shift-S
   - Linux：使用桌面环境截图工具并复制到剪贴板

示例对话：
```
用户：分析一下我刚截的屏
→ 调用 save_clipboard_to_file()
→ 返回 /tmp/mmp-clip-1234567890.png
→ 调用 process_multimodal(["/tmp/mmp-clip-1234567890.png"], ["描述这张截图的内容"])
→ 返回分析结果给用户
```

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

- 配置文件：
- Linux 剪贴板依赖：Wayland 需安装 wl-clipboard（提供 wl-paste），X11 需安装 xclip
- api_key：mac 默认 keychain（service=multimodal-proxy，account=provider名）
- 重新配置：`bash scripts/install.sh`
