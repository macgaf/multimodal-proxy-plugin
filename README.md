# multimodal-proxy-plugin

为纯文本主模型（如 glm-5.2、deepseek-v4）提供多模态外包能力的 Codex 插件。

当主模型不支持图像/视频/音频时，通过内置 MCP 把多模态任务转交给外部多模态模型
（火山引擎 Coding Plan，如 doubao-seed-2.0-pro）处理，再把文字结果回填给主模型。
配套 skill 规范了激活规则：仅纯文本主模型且有多模态需求时才启用。

## 架构

```
用户（纯文本主模型 glm-5.2）
  │  遇到"分析这张图" → skill 判断主模型是纯文本 → 调用 process_multimodal
  ▼
multimodal-proxy MCP
  │  读配置 + keychain key → 调用火山引擎 doubao-seed-2.0-pro
  ▼
doubao-seed-2.0-pro（多模态模型）
  │  返回图片/视频分析结果
  ▼
文字结果回填给主模型
```

## 组成

| 部分 | 路径 | 作用 |
|---|---|---|
| MCP server | `mcp/multimodal_proxy.py` | 通用多模态代理，2 个工具 |
| Skill | `skills/multimodal-proxy/SKILL.md` | 激活规则与使用规范 |
| 安装脚本 | `scripts/install.sh` | 配置 + keychain + 依赖 + 注册 |
| 配置工具 | `scripts/configure.py` | 写配置文件 + 管理 key 存储 |

## MCP 工具

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

### generate_image

根据文字提示词生成图片。需配置 image_generation 模型。

## 模型能力（已验证 doubao-seed-2.0-pro, Coding Plan）

| 媒体类型 | 支持 | 说明 |
|---|---|---|
| 图片 image_url | ✅ | 支持多图对比 |
| 视频 video_url | ✅ | 需可访问 URL |
| 音频 input_audio | ❌ | 该模型不支持，需换专用模型 |

## 安装

```bash
cd multimodal-proxy-plugin
bash scripts/install.sh
```

交互式引导输入 provider、base_url、api_key（mac 存 keychain）、模型名。
默认值已针对火山引擎 Coding Plan 预填。

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
      "models": {"vision": "doubao-seed-2.0-pro"}
    }
  }
}
```

api_key 存储优先级：mac keychain > 环境变量 > 配置文件明文。

## skill 激活规则

1. 主模型是纯文本模型且有多模态需求 → **激活** MCP
2. 主模型是多模态模型 → **不激活**，除非用户显式要求外包
3. 不确定 → 默认激活

## 测试

```bash
# 端到端测试（需已配置）
.venv/bin/python scripts/test_e2e.py
```

验证场景：主模型 glm-5.2 + 图片分析转 doubao-seed-2.0-pro。
