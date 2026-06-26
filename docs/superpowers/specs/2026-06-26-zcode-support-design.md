# multimodal-proxy-plugin 新增 ZCode 渠道设计

> 日期：2026-06-26
> 范围：在不破坏现有 Codex / Claude Code 渠道的前提下，新增 ZCode 安装渠道，使本机 ZCode（主模型 GLM-5.2，纯文本）能一键装上并用起 multimodal-proxy MCP。

## 背景

multimodal-proxy-plugin 把图像/视频/音频处理外包给任意 OpenAI 兼容多模态模型，专供纯文本主模型使用。现有打包渠道：

- **Codex** — `.codex-plugin/plugin.json` + `scripts/install.sh` 注册到 `codex` CLI（`codex plugin add`）。
- **Claude Code** — `.claude-plugin/marketplace.json`。

用户当前在用 ZCode（`~/.zcode/`，Electron 应用，版本 3.1.8），主模型 `GLM-5.2` 在 `~/.zcode/v2/config.json` 中明确标注 `input: ["text"]`（纯文本），正是本插件要解决的痛点。

## 逆向确认的关键事实

通过分析 `/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs` 确认：

1. **ZCode 已能识别现有 `.codex-plugin/plugin.json`** — 清单查找顺序为 `.zcode-plugin/plugin.json` → `.claude-plugin/plugin.json` → `.codex-plugin/plugin.json`。所以 skill 层面 ZCode 已能加载。
2. **但当前 MCP 在 ZCode 下起不来** — 根因有二：
   - `.mcp.json` 写死了本机绝对路径（`/Users/macgaffin/.../.venv/bin/python`）。
   - `.codex-plugin/plugin.json` 用 `"mcpServers": "./.mcp.json"` 相对引用；ZCode 解析 `mcpServers` 期望内联定义或 `${CLAUDE_PLUGIN_ROOT}`/`${ZCODE_PLUGIN_ROOT}` 变量路径。
3. **ZCode 直接 spawn stdio MCP server 的 `command`**，不需要官方 Node 插件那种 `zcode.cjs __zcode-plugin-host` 包装——Python MCP server 能直接跑。
4. **ZCode 没有 `plugin add` 命令**，只有 `zcode plugins [list|enable <id>|disable <id>]`。插件注册机制：
   - 放进 `~/.zcode/cli/plugins/cache/<marketplace>/<plugin>/<version>/`；
   - 在 `~/.zcode/cli/plugins/marketplaces/<marketplace>/marketplace.json` 累加一条 `{cachePath, name, source:"filesystem", version}`；
   - 在 `~/.zcode/cli/config.json` 的 `enabledPlugins` 写 `"<plugin>@<marketplace>": true`（本机已有先例：`superpowers@zcode-plugins-official`）。
5. **变量插值**：ZCode 对 `${CLAUDE_PLUGIN_ROOT}`、`${ZCODE_PLUGIN_ROOT}`、`${CLAUDE_PLUGIN_DATA}`、`${ZCODE_PLUGIN_DATA}` 做替换（正则 `/\$\{(CLAUDE_PLUGIN_DATA|CLAUDE_PLUGIN_ROOT|ZCODE_PLUGIN_DATA|ZCODE_PLUGIN_ROOT)\}/gu`），并设置 `cwd` 用的 `${ZCODE_PROJECT_DIR}`。

## 方案

**方案 A（已选定）**：新增 `.zcode-plugin/plugin.json`（MCP server 内联，用 `${ZCODE_PLUGIN_ROOT}` 变量路径），改造 `install.sh` 增加 ZCode 注册分支，与官方插件（android-emulator / ios-simulator）同构。三渠道（Codex / Claude / ZCode）共存。

不选 B（只加清单不改 install.sh，手动注册）：用户体验差，marketplace.json 手动合并易错。
不选 C（共用变量化 .mcp.json）：现有 `.mcp.json` 是 install.sh 生成的本机实例文件（含真实 python 路径），与"变量模板"冲突，需引入 example vs 生成物区分，反而更乱。

## §1 架构与组件

| 组件 | 动作 | 说明 |
|---|---|---|
| `.zcode-plugin/plugin.json` | **新增** | ZCode 清单。`mcpServers` 内联，`command` 用 `${ZCODE_PLUGIN_ROOT}/.venv/bin/python`，`args` 用 `${ZCODE_PLUGIN_ROOT}/mcp/multimodal_proxy.py`，`cwd` 用 `${ZCODE_PROJECT_DIR}`。`skills: "skills"`。version 用短版本号 `0.1.0`。 |
| `scripts/install.sh` | **改造** | 末尾注册步骤由"只注册 Codex"改为"探测宿主"：优先 `codex` CLI → 原 Codex 流程；否则检测 `~/.zcode/cli/` 存在 → ZCode 流程；两者都没有 → 只生成配置 + 提示手动安装。支持 `--target zcode\|codex\|auto` 参数（默认 auto）。 |
| `scripts/zcode_register.py` | **新增** | ZCode 注册逻辑（Python，避免 bash 拼 JSON）：把插件 symlink 进 cache 目录、合并 marketplace.json、写 enabledPlugins。被 install.sh 调用。CLI 接口：`zcode_register.py --plugin-root <PLUGIN_ROOT> --marketplace <name> --version <ver>`，三个参数均由 install.sh 传入。 |
| `README.md` | **改造** | 顶部 badge 增加 ZCode Plugin；安装节增加 ZCode 分支说明；"组成"表新增 `.zcode-plugin` 行；措辞去 Codex 化（"绕过 Codex 硬拦截"→"绕过纯文本模型对图片输入的硬拦截"）。 |
| `skills/multimodal-proxy/SKILL.md` | **改造** | 同上去 Codex 化；激活规则的纯文本模型清单确认包含 GLM-5.2（已含）。 |
| `mcp/multimodal_proxy.py` | **微调** | docstring / 工具描述里的 "Codex" 改为通用措辞（"纯文本 Agent 主模型"）。核心逻辑不动。 |

**ZCode 注册的关键常量**：
- marketplace 名：`personal`（可通过环境变量 `ZCODE_MARKETPLACE` 覆盖）。
- cache 路径：`~/.zcode/cli/plugins/cache/personal/multimodal-proxy-plugin/<version>/`。
- enabledPlugins 键：`multimodal-proxy-plugin@personal`。

## §2 数据流与注册流程

### install.sh 改造后的执行流

步骤 1-7（创建 venv → 装依赖 → 交互收集配置 → 写 config.json → 生成 .mcp.json）**完全保留不变**。Codex 仍需本机 `.mcp.json`；ZCode 走内联 `plugin.json`。仅改第 8 步注册逻辑：

```
第 8 步：探测宿主并注册
  ├─ 解析 --target 参数（默认 auto）
  ├─ target=codex 或 (auto 且 command -v codex)  → 原 Codex 流程（ln ~/plugins + codex plugin add）
  ├─ target=zcode 或 (auto 且无 codex 且 ~/.zcode/cli/ 存在) → ZCode 流程 ↓
  │     1. MARKETPLACE="${ZCODE_MARKETPLACE:-personal}"
  │     2. VERSION = 读 .zcode-plugin/plugin.json 的 version
  │     3. CACHE_DIR=~/.zcode/cli/plugins/cache/$MARKETPLACE/multimodal-proxy-plugin/$VERSION
  │     4. 调用 scripts/zcode_register.py 完成：
  │        a. 若 CACHE_DIR 已存在且非 symlink → 报错退出，不删用户内容
  │        b. rm -rf $CACHE_DIR（仅当为 symlink 或不存在）; ln -sfn $PLUGIN_ROOT $CACHE_DIR
  │        c. 合并 marketplaces/$MARKETPLACE/marketplace.json：
  │           upsert {cachePath:$CACHE_DIR, name:"multimodal-proxy-plugin", source:"filesystem", version:$VERSION}
  │           （文件不存在则新建 {name:$MARKETPLACE, plugins:[...], version:1}）
  │        d. 写 ~/.zcode/cli/config.json 的 enabledPlugins["multimodal-proxy-plugin@$MARKETPLACE"]=true
  │     5. 提示：重启 ZCode 生效；可用 `zcode plugins list` 验证
  └─ 都没有 → 打印 .mcp.json 路径，提示手动配置
```

### 运行时数据流（ZCode 下，核心不变）

```
用户在 ZCode 说"分析这张图"
  → SKILL.md 激活规则判断：GLM-5.2 是纯文本模型 → 激活
  → ZCode spawn: ${ZCODE_PLUGIN_ROOT}/.venv/bin/python mcp/multimodal_proxy.py
  → MCP 工具 process_multimodal 读 ~/.config/multimodal-proxy/config.json
  → 调外部多模态 API → 文字结果回填给 GLM-5.2
```

**关键决策**：
- `VERSION` 用短版本号 `0.1.0`（从 `.zcode-plugin/plugin.json` 读），不用 Codex 的 `0.1.0+codex.<timestamp>` 长串——ZCode cache 是 `<plugin>/<version>/` 目录结构，短版本号更干净。
- marketplace.json 合并与 enabledPlugins 写入用 Python（`zcode_register.py`），避免 bash 拼 JSON 出错，且能保留文件已有其他键。
- symlink 而非复制：与现有 Codex 的 `ln -sfn $PLUGIN_ROOT ~/plugins/...` 一致，开发期改代码立即生效。

## §3 错误处理与边界

### install.sh 错误处理
- `~/.zcode/cli/` 不存在且无 `codex` → 走"都没有"分支，只生成 `.mcp.json`，打印路径，不报错退出（exit 0）。
- marketplace.json 已存在但非合法 JSON → 报错退出（exit 1），提示手动检查，**不覆盖**原文件。
- `~/.zcode/cli/config.json` 已存在但无 `enabledPlugins` 键 → 创建该键；已有则 upsert，不动其他键。
- symlink 目标已被占用（非 symlink 的真实目录）→ 报错提示，**不强制删除**用户已有内容，要求用户确认后重跑。
- `--target zcode` 显式指定但 `~/.zcode/cli/` 不存在 → 报错退出，提示未检测到 ZCode 安装。
- `zcode_register.py` 失败 → 保留原文件，打印错误，exit 1。

### 幂等性
重跑 `install.sh` 安全：marketplace.json upsert（同 name 覆盖 version/cachePath）；enabledPlugins 写 `true`（已是 true 无副作用）；symlink 用 `ln -sfn` 幂等。

### 安全边界（沿用现有，不变）
- 不修改剪贴板内容、不执行删除/git 提交。
- ZCode 注册只写 `~/.zcode/cli/` 下三个位置（cache symlink、marketplace.json、config.json 的 enabledPlugins），不碰其他插件。
- api_key 存储三选一逻辑完全不变。

### 不做什么（YAGNI）
- 不实现 `zcode plugins disable` / 卸载逻辑（用户用 `zcode plugins disable` 即可）。
- 不做 ZCode 版本探测 / 兼容性检查（当前只针对本机 3.1.8）。
- 不改 `configure.py` 核心逻辑（仅可能微调一句提示文案）。
- 不为 Codex 渠道引入 `${CLAUDE_PLUGIN_ROOT}` 变量化（保留 Codex 现有行为不动）。

## §4 测试与验证

复用现有测试体系，新增 ZCode 注册逻辑测试，不引入新框架。

| 测试 | 文件 | 内容 |
|---|---|---|
| 注册逻辑单测（新增） | `scripts/test_zcode_register.py` | 用 `tempfile` 造假的 `~/.zcode/cli/` 目录，跑注册函数，断言：cache symlink 存在且指向插件根、marketplace.json 含正确条目、config.json 的 enabledPlugins 含 `multimodal-proxy-plugin@personal: true` 且不破坏其他键；重跑断言幂等。 |
| 注册逻辑错误路径（新增） | 同上 | 传入非法 JSON 的 marketplace.json → 断言函数报错且不覆盖原文件；传入非 symlink 占位目录 → 断言报错不删。 |
| 激活规则测试（现有，确认不破） | `scripts/test_activation.py` | 重跑，确认 GLM-5.2 仍判为纯文本、多模态模型不激活。 |
| 离线 dry-run（现有，确认不破） | `scripts/test_dryrun.py` | 重跑，确认 MCP 工具行为不变。 |
| 手动验证清单 | README 验证节 | (1) 干净环境跑 `bash scripts/install.sh --target zcode`；(2) `zcode plugins list` 见 multimodal-proxy-plugin 且 enabled；(3) 重启 ZCode，新会话说"分析这张图"+给路径 → GLM-5.2 调 process_multimodal 返回文字；(4) 重跑 install.sh 断言幂等无报错。 |

### 验收标准（完成定义）
1. `.zcode-plugin/plugin.json` 存在且 `python3 -m json.tool` 校验合法。
2. `bash scripts/install.sh --target zcode` 在本机执行成功，`~/.zcode/cli/config.json` 的 enabledPlugins 出现该插件。
3. `python3 scripts/test_zcode_register.py` 全绿。
4. 现有 `test_activation.py`、`test_dryrun.py` 仍全绿。
5. README 顶部出现 ZCode badge，安装节有 ZCode 分支，无"Codex 硬拦截"等绑定措辞残留。
