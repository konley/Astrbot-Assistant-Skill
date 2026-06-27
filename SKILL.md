---
name: astrbot-assistant
description: >-
  AstrBot 全流程助手。当用户需要部署、安装、配置、管理 AstrBot，
  或涉及 NapCat QQ 适配器、aiocqhttp 对接、AstrBot 插件开发与脚手架生成、
  插件修复、机器人面板端口、systemd 保活、SSH 远程操作服务器、
  MiniMax/LLM 配置、AI 人格 Prompt 生成、SSH 隧道访问内网面板时使用。
  覆盖从零部署到日常运维、从插件开发到合规检查的完整链路。
cn_name: AstrBot 助手
cn_description: >-
  AstrBot 全流程助手。部署、安装、配置、管理 AstrBot，NapCat QQ 适配器对接，
  插件开发脚手架生成与合规检查，插件修复，端口配置，systemd 保活自启，
  AI 人格生成，SSH 隧道管理，OpenAPI 集成，测试生成。
---

# AstrBot 助手

协助用户部署、配置、管理 AstrBot 聊天机器人框架，并从自然语言需求生成合规插件。

## 核心能力

### 一、部署与运维

1. **从零部署 AstrBot** — uv 包管理器安装、初始化、端口配置、systemd 保活
2. **NapCat QQ 适配器** — 安装、扫码登录、WebUI 配置、WebSocket 对接 AstrBot
3. **插件运维管理** — 安装、修复 metadata.yaml 语法错误、修改插件源码（如去除 markdown）
4. **AI 人格 Prompt** — 生成猫娘/自定义人格，含主人识别、群聊行为、报错文案
5. **SSH 隧道工具** — 生成 HTML 隧道管理器，可视化配置端口转发，一键生成指令

### 二、插件开发

6. **插件脚手架生成** — 从自然语言需求生成 metadata.yaml、requirements.txt、插件代码
7. **合规检查** — metadata 字段校验、适配器键校验、代码规范（异步 HTTP、data 目录持久化）
8. **测试生成** — smoke test、behavior test、OpenAPI 鉴权测试模板
9. **OpenAPI 集成** — 调用 AstrBot HTTP API（`/api/v1/*`，`X-API-Key` 鉴权）
10. **调试与发布** — WebUI 热重载、ruff 格式化、发布检查清单

## 参考文档（按需加载）

### 部署运维

| 文件 | 内容 |
|------|------|
| `references/deploy-guide.md` | AstrBot + NapCat 完整部署流程，含命令、路径、配置参数 |
| `references/troubleshooting.md` | 常见问题排障：BOM、端口冲突、WebSocket 405、插件 YAML 解析失败、插件开发问题 |
| `references/config-reference.md` | 关键配置文件路径、结构、字段说明，含 paramiko 脚本模板 |
| `references/plugin-lifecycle.md` | 插件生命周期管理：重载/重新安装/重启的优先级 SOP，WebUI API 端点 |

### 插件开发

| 文件 | 内容 |
|------|------|
| `references/plugin-new-checklist.md` | 新插件官方检查清单：环境搭建、metadata、适配器键、调试重载、依赖管理 |
| `references/nl-to-implementation.md` | 自然语言→实现工作流：需求解析→实现规划→构建顺序→完成合约 |
| `references/compliance-checklist.md` | 合规检查清单：metadata、适配器、代码、测试、交付合规 |
| `references/testing-guide.md` | 测试指南：smoke/behavior/integration 三层测试，pytest 运行 |
| `references/openapi-integration.md` | OpenAPI 集成参考：端点列表、鉴权、响应结构、测试策略 |

## 附带资源

| 文件 | 用途 |
|------|------|
| `assets/tunnel-generator.html` | SSH 隧道生成器，可视化配置端口转发，生成 ssh 命令 |
| `assets/metadata.yaml.template` | 插件 metadata.yaml 模板 |
| `assets/requirements.txt.template` | 插件依赖模板 |
| `assets/test_plugin_smoke.py.template` | 插件 smoke 测试模板 |
| `assets/test_plugin_behavior.py.template` | 插件行为测试模板 |
| `assets/test_openapi_auth_and_shape.py.template` | OpenAPI 鉴权与响应结构测试模板 |
| `assets/dev-commands.txt` | 本地开发常用命令 |
| `assets/logo-process.py` | 插件 Logo 自动处理脚本（任意图→256x256 居中正方形 PNG） |

## 工作流程

### 部署 AstrBot

1. SSH 连接远程主机（需用户提供 IP、端口、用户名、密码）
2. 检查系统环境（OS、Python 版本、内存、磁盘）
3. 安装 uv → `uv tool install astrbot`
4. 初始化 → `astrbot init`（交互式，需自动应答 Y）
5. 配置端口 → `astrbot conf set dashboard.port {端口}`
6. 创建 systemd 服务 → 启用开机自启 + 崩溃重启
7. 验证 WebUI 可访问

### 部署 NapCat

1. 下载官方 NapCat-Installer 脚本
2. 运行安装（会自动安装 Linux QQ）
3. 配置 WebUI 端口 → 编辑 `config/webui.json`
4. 启动 → `napcat start {QQ号}` → 扫码登录
5. 配置反向 WebSocket → 对接 AstrBot aiocqhttp 适配器
6. 设置开机自启 → `napcat startup {QQ号}`

### 对接 AstrBot ↔ NapCat

1. AstrBot 配置 aiocqhttp 适配器（WebUI 或 `cmd_config.json`）
2. NapCat 配置反向 WebSocket 地址：`ws://127.0.0.1:{astrbot_ws_port}/ws`
   - 注意：必须带 `/ws` 路径，否则返回 405
3. 双方重启验证连通

### 开发 AstrBot 插件

1. **收集需求**：
   - 若 `login.config` 包含 GitHub 链接，将其作为仓库根地址。向用户确认："检测到你的 GitHub 仓库 `{链接}`，是否以此为基础创建插件？"
   - 功能描述、目标适配器、AstrBot 版本约束、第三方依赖、是否需要 OpenAPI。
2. **需求解析**：将自然语言转为具体实现计划——功能列表、触发方式、输入输出行为、错误路径。
3. **插件命名**：根据需求给出 2-3 个建议名（格式 `astrbot_plugin_xxx`，小写、无空格），与用户确认后确定。
4. **按序生成**：
   - `metadata.yaml`（必填：name/desc/version/author/repo；可选：display_name/support_platforms/astrbot_version）
     - `repo` 字段 = GitHub 根地址 + `/` + 插件文件夹名（如 `https://github.com/konley/astrbot_plugin_xxx`）
     - 若无 GitHub 根地址，`repo` 字段可选，不强制
   - `requirements.txt`（有第三方依赖时）
   - 插件代码（异步 HTTP 优先用 aiohttp/httpx，持久化数据存 data 目录）
   - 测试文件（至少一个 smoke test）
5. **合规检查**：metadata 字段合法、适配器键有效、无 requests 同步调用、数据不写插件源目录。
6. **Logo 处理**（可选）：若用户有 logo 图片，调用 `assets/logo-process.py` 自动转为 256x256 PNG。
7. **首次 Git 提交**：提交前检查 `logo.png` 是否存在，若不存在则提醒用户："可添加 logo 图片，运行 `python assets/logo-process.py <图片路径>` 自动生成"，非强制。
8. **调试工作流**：本地 ruff 格式化 → (可选 git push) → 同步文件到服务器插件目录 → WebUI 重载插件。**不得重启机器人。**

### 插件生命周期管理（重载 vs 重新安装 vs 重启）

**核心原则：重载 >> 重新安装 >>> 重启。重启机器人必须征得用户确认。**

#### 重载插件（优先级最高）

重载会完整地**终止→解绑→重新加载**插件，所有文件修改都会被重新读取执行，**无需重启机器人**。

通过 WebUI 调用：`POST /api/plugin/reload`，body `{"name": "插件名"}`（省略则重载全部）。

适用场景：
- 修改了已安装插件的源码文件
- 修改了插件配置文件
- 更新了插件 metadata.yaml
- 在线热修改任何插件文件后

操作步骤：
1. SSH/SFTP 将修改后的文件同步到服务器插件目录（`{data_dir}/addons/plugins/{plugin_name}/`）
2. 通过 Dashboard API 触发重载
3. 验证功能正常
4. **无需重启**

#### 重新安装插件（次优先）

通过 WebUI 调用：先 `POST /api/plugin/uninstall` `{"plugin_name": "..."}`，再 `POST /api/plugin/install` `{"repo_url": "..."}`。

适用场景：
- 本地完成了完整开发周期，需要从 GitHub 重新拉取最新版本
- 插件依赖发生变化（新增/删除 requirements.txt）
- 插件目录结构变化（新增 pages/、skills/ 等）

本地开发部署最佳实践：
1. 本地修改完成 → `git add` → `git commit` → `git push`
2. push 成功后 → WebUI 重新安装插件（或先卸后装）
3. **无需重启**

#### 同步本地修改的快速路径

若尚未 push 到 GitHub 但需要在服务器上验证：
1. SFTP 将本地修改的文件同步到服务器插件目录
2. 触发重载即可
3. 验证通过后 push 到 GitHub

#### 何时需要重启机器人（必须征得用户确认）

仅以下情况**可能**需要重启（需先告知用户原因并获确认）：
- AstrBot 核心版本升级（`uv tool upgrade astrbot`）
- 修改 `cmd_config.json` 中影响核心生命周期的配置（平台适配器、LLM Provider 等）
- AstrBot Dashboard 配置变更（端口、API Key 等）
- 系统级故障（进程僵死、内存泄漏等）

### 修复插件常见问题

- **metadata.yaml 解析失败** → 检查 YAML 语法，`help` 字段以 `[` 开头需加引号
- **AI 输出带 markdown** → 修改插件源码，添加 `_strip_markdown` 后处理函数
- **BOM 导致 JSON 解析失败** → 用 `printf` 或 SFTP 重写文件，确保无 BOM

### 生成 SSH 隧道工具

直接提供 `assets/tunnel-generator.html` 给用户，或根据其服务器信息定制。
用户在浏览器中配置隧道 → 生成 ssh 命令 → 粘贴到终端执行。

### 处理插件 Logo

1. 用户提供任意格式的原始图片（jpg/png/webp/gif/bmp 等）
2. 调用 `assets/logo-process.py <图片路径>` 自动处理：
   - 转为 PNG 格式
   - 居中裁剪为正方形
   - 缩放至 256×256
   - 输出到插件根目录 `logo.png`
3. 若不指定输出路径，默认输出到当前目录的 `logo.png`

## 支持的适配器键

用于 `metadata.yaml` 的 `support_platforms` 字段：

`aiocqhttp` · `qq_official` · `telegram` · `wecom` · `lark` · `dingtalk` · `discord` · `slack` · `kook` · `vocechat` · `weixin_official_account` · `satori` · `misskey` · `line`

## 关键注意事项

### 部署运维

- **禁止随意重启机器人**：能重载解决就用重载，能重新安装解决就用重新安装。**重启机器人必须征得用户确认**，严禁擅自重启。详细 SOP 见 `references/plugin-lifecycle.md`。
- **login.config 凭据读取 SOP**：当用户提到 SSH 远程操作时，先检查项目根目录下是否存在 `login.config` 文件。若存在且可解析，直接读取 IP/端口/用户名/密码，**不要询问用户凭据**，只需确认"要帮你远程操作吗？"即可。若文件不存在或解析失败，再向用户索取。
  - 文件解析逻辑：第一行为 `IP:端口`（或 `ssh:IP:端口`），第二行为用户名，第三行为密码。
  - 可选行：若某行匹配 GitHub 链接（`https://github.com/...`），自动识别为用户的仓库根地址。后续制作插件时，`metadata.yaml` 的 `repo` 字段将基于此地址拼接插件文件夹名生成。
  - `login.config` 示例：
  ```
  152.67.140.25:62122
  root
  konley44448888
  https://github.com/konley
  ```
- Windows 本地通过 paramiko 库实现 SSH 远程操作（系统 ssh.exe 需要交互式密码输入）
- PowerShell 中传递含特殊字符的命令时，优先用 SFTP 上传文件而非 heredoc
- `astrbot init` 是交互式的，需用 `invoke_shell` + 自动应答
- NapCat WebUI 端口配置在 `config/webui.json`，字段为 `port`
- aiocqhttp 反向 WS 连接地址必须包含 `/ws` 路径
- uv 部署方式不支持 WebUI 升级，需用 `uv tool upgrade astrbot`
- **MiniMax Token Plan 推理泄漏问题**：使用 MiniMax M3 等推理模型时，若 `reasoning: true` 但 `anth_thinking_config` 为 `{"type":"","budget":0}`，模型推理内容会混入回复正文泄漏。原因是 `minimax_token_plan` 适配器继承 `ProviderAnthropic`（非 OpenAI 源），Anthropic 源缺少 `<think>` 标签剥离逻辑，而 `anth_thinking_config` 未启用时 API 不返回标准 thinking 块，推理直接进 `completion_text`。`display_reasoning_text: false` 对此无效。修复：将 `anth_thinking_config` 改为 `{"type": "enabled", "budget": 2048}`（WebUI 无配置项，需直接编辑 `cmd_config.json`，然后重启 AstrBot）。
- **无 GPU 服务器安装 torch/sentence-transformers**：必须使用 CPU-only 索引安装 torch，否则会下载 2GB+ 无用的 CUDA/nvidia 包（cudnn 444MB、cublas 542MB 等）。正确命令：
  ```bash
  {astrbot_python} -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  {astrbot_python} -m pip install sentence-transformers --no-deps
  {astrbot_python} -m pip install transformers huggingface-hub scikit-learn scipy nltk tokenizers
  ```
  其中 `{astrbot_python}` 为 uv 部署的 Python 路径，通常为 `/root/.local/share/uv/tools/astrbot/bin/python`。

### 插件开发

- 插件目录命名：小写、无空格、建议前缀 `astrbot_plugin_`（如 `astrbot_plugin_weather`）
- `metadata.yaml` 的 `repo` 字段记录插件仓库地址。若 `login.config` 中有 GitHub 链接，`repo` = `{github链接}/{插件文件夹名}`
- `astrbot_version` 遵循 PEP 440，不加 `v` 前缀（如 `>=4.17.0`）
- 持久化数据必须存放在 AstrBot `data` 目录，不写插件源目录
- 网络请求避免 `requests`，优先异步 `aiohttp` 或 `httpx`
- OpenAPI 基址默认 `http://localhost:6185`，端点 `/api/v1/*`，鉴权头 `X-API-Key`
- API Key 从配置或环境变量读取，不硬编码
- 生成代码提交前用 ruff 格式化
- `_conf_schema.json` 中 `type: "string"` 配合 `options` 数组（如 `"options": ["a", "b"]`）可在 WebUI 渲染为下拉菜单。不支持 `choices` 或 `type: "select"`。支持的类型：`int`、`float`、`bool`、`string`、`text`、`list`、`file`、`object`、`template_list`
- Logo 处理：用户提供原始图，调用 `assets/logo-process.py` 自动转为 256×256 居中方 PNG
- 首次 Git 提交时提醒用户可添加 logo（非强制）
- 官方文档：[插件开发](https://docs.astrbot.app/dev/star/plugin-new.html) · [OpenAPI](https://docs.astrbot.app/scalar.html)
