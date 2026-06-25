# multimodal-proxy-plugin

为纯文本主模型（如 glm-5.2、deepseek-v4）提供多模态外包能力的 Codex 插件。

当主模型不支持图像/视频/音频时，通过内置 MCP 把多模态任务转交给外部多模态模型
（火山引擎 Coding Plan，如 doubao-seed-2.0-pro）处理，再把文字结果回填给主模型。
配套 skill 规范了激活规则：仅纯文本主模型且有多模态需求时才启用。
外部模型不绑定火山引擎——任何 OpenAI 兼容的多模态 API 均可（OpenAI / Qwen-VL / Ollama 等），火山引擎 doubao 仅为默认示例。

## 架构

```
用户（纯文本主模型 glm-5.2）
  │
  ├─ 场景A：用户给出图片文件路径
  │    → skill 判断主模型是纯文本 → 调用 process_multimodal
  │
  └─ 场景B：用户说"分析一下截屏"（Ctrl-V 粘贴被 Codex 硬拦截）
       → skill 判断主模型是纯文本 → 先调用 save_clipboard_to_file
       → 剪贴板图片落盘为临时文件 → 再调用 process_multimodal
       ▼
multimodal-proxy MCP
  │  读配置 → 按 api_key_store 获取 key → 调用 doubao-seed-2.0-pro
  ▼
doubao-seed-2.0-pro（多模态模型）
  │  返回图片/视频分析结果
  ▼
文字结果回填给主模型
```

## 组成

| 部分 | 路径 | 作用 |
|---|---|---|
| MCP server | `mcp/multimodal_proxy.py` | 通用多模态代理，3 个工具 |
| Skill | `skills/multimodal-proxy/SKILL.md` | 激活规则与使用规范 |
| 安装脚本 | `scripts/install.sh` | 虚拟环境 + 依赖 + 配置 + 注册 |
| 配置工具 | `scripts/configure.py` | 写配置文件 + 管理 api_key 存储方式 |

## MCP 工具

### save_clipboard_to_file

读取系统剪贴板内容，如果是图片则保存为临时 PNG 文件并返回路径。

**用途**：绕过 Codex 对纯文本模型的图片输入硬拦截。用户 Ctrl-V 粘贴截图会被拦截，
但截图仍在系统剪贴板中。本工具从剪贴板读取图片，落盘为文件，返回路径供后续分析。

**跨平台支持**：

| 平台 | 实现方式 | 依赖 |
|---|---|---|
| macOS | osascript（AppleScript 读 `«class PNGf»`） | 系统自带 |
| Windows | PowerShell + `System.Windows.Forms.Clipboard` | 系统自带 |
| Linux (Wayland) | `wl-paste` | 需安装 `wl-clipboard` |
| Linux (X11) | `xclip` | 需安装 `xclip` |

工作流：
1. 用户先截图到剪贴板（macOS: `Ctrl-Shift-Cmd-4`，Windows: `Win-Shift-S`，Linux: 桌面截图工具）
2. 在 Codex 里输入文本指令，如"分析一下我刚截的屏"（不要 Ctrl-V 粘贴图片）
3. 主模型调用本工具 → 剪贴板图片落盘 → 返回路径
4. 主模型调用 `process_multimodal([路径], [提示词])` 完成分析

### process_multimodal（核心）

接收任意数量的图片/视频/音频 + 提示词，按顺序组装成多模态请求交给模型处理。

```
process_multimodal(
  media: list[str],         # 媒体路径或URL列表（图片/视频/音频可混用）
  prompts: list[str],       # 提示词列表（0~n条，作为任务指令）
  model: str | None,        # 可选，覆盖默认模型
  provider: str | None      # 可选，覆盖默认 provider
)
```

用法：
- 单图分析：`process_multimodal(["/img.png"], ["描述这张图"])`
- 多图对比：`process_multimodal(["/a.png", "/b.png"], ["对比这两张图"])`
- OCR 提取：`process_multimodal(["/scan.jpg"], ["提取图中所有文字"])`
- 截屏分析：先 `save_clipboard_to_file()` 拿到路径，再 `process_multimodal([路径], ["分析"])`

### generate_image

根据文字提示词生成图片。需配置 image_generation 模型。

## 模型能力（已验证 doubao-seed-2.0-pro, Coding Plan）

| 媒体类型 | 支持 | 说明 |
|---|---|---|
| 图片 image_url | ✅ | 支持多图对比 |
| 视频 video_url | ✅ | 需可访问 URL |
| 音频 input_audio | ⚠️ | doubao-seed-2-0-pro 不支持；mini/lite 260428 元数据标注支持但 Coding Plan key 实测被拒，需控制台确认开通 |

## 安装

```bash
cd multimodal-proxy-plugin
bash scripts/install.sh
```

交互式引导输入 provider、base_url、模型名，以及 **api_key 存储方式（三选一）**：

| 选项 | 方式 | 说明 |
|---|---|---|
| 1 | keychain | 存入 macOS 钥匙串，配置文件无明文（推荐，仅 macOS） |
| 2 | plaintext | 明文写入配置文件（仅兼容场景使用） |
| 3 | env | 从环境变量读取，配置文件只记录变量名 |

macOS 默认使用 keychain，其他平台默认使用 env；plaintext 仅在明确选择时启用。安装脚本通过标准输入传递密钥，并通过系统钥匙串接口保存，不会将密钥置于进程参数中。默认值已针对火山引擎 Coding Plan 预填。

## 配置文件

`~/.config/multimodal-proxy/config.json`，api_key 有三种存储方式，由 `api_key_store`
字段指定，严格匹配不回退：

### keychain（仅 macOS）

```json
{
  "default_provider": "volcengine",
  "providers": {
    "volcengine": {
      "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
      "api_key_store": "keychain",
      "keychain_service": "multimodal-proxy",
      "keychain_account": "volcengine",
      "models": {"vision": "doubao-seed-2.0-pro"}
    }
  }
}
```

### plaintext

仅在无法使用 keychain 或环境变量时使用。配置文件权限会设为仅当前用户可读写（`0600`），但仍不建议将该文件放入同步盘、备份文件或版本控制。

```json
{
  "default_provider": "volcengine",
  "providers": {
    "volcengine": {
      "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
      "api_key_store": "plaintext",
      "api_key": "ark-xxxxxxxxxxxx",
      "models": {"vision": "doubao-seed-2.0-pro"}
    }
  }
}
```

### env

```json
{
  "default_provider": "volcengine",
  "providers": {
    "volcengine": {
      "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
      "api_key_store": "env",
      "api_key_env": "MULTIMODAL_PROXY_API_KEY_VOLCENGINE",
      "models": {"vision": "doubao-seed-2.0-pro"}
    }
  }
}
```

使用 env 模式时，需在运行 Codex 前设置环境变量：

```bash
export MULTIMODAL_PROXY_API_KEY_VOLCENGINE='ark-xxxxxxxxxxxx'
# 建议写入 ~/.zshrc 或 ~/.bashrc
```

## skill 激活规则

1. 主模型是纯文本模型且有多模态需求 → **激活** MCP
2. 主模型是多模态模型 → **不激活**，除非用户显式要求外包
3. 不确定 → **不自动激活**，优先由主模型原生处理；主模型无法接收媒体时再询问用户是否外包

> 优先级：用户明确要求外包 > 已确认纯文本模型 > 主模型原生多模态 > 能力不明时不自动代理

## 安全边界

- 本插件会把图片/视频/音频发送到你配置的外部多模态 API（默认火山引擎），**不会发往任何第三方**。处理敏感截图前请确认你的 provider 数据政策。
- api_key 三选一存储：macOS 默认 keychain（不入仓库）、env（只记变量名）、plaintext（仅兼容场景，文件权限 0600）。**明文密钥绝不应提交到版本控制。**
- 剪贴板工具只读取、落盘临时文件，不修改、不上传剪贴板文本内容。
- 不会执行任何删除、git 提交或越权操作。

## 测试

```bash
# 端到端测试（需已配置）
.venv/bin/python scripts/test_e2e.py
```

验证场景：主模型 glm-5.2 + 图片分析转 doubao-seed-2.0-pro。
