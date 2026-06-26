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

1. **收集需求**：插件仓库名（建议前缀 `astrbot_plugin_`）、功能描述、目标适配器、AstrBot 版本约束、第三方依赖、是否需要 OpenAPI
2. **需求解析**：将自然语言转为具体实现计划——功能列表、触发方式、输入输出行为、错误路径
3. **按序生成**：
   - `metadata.yaml`（必填：name/desc/version/author；可选：display_name/support_platforms/astrbot_version）
   - `requirements.txt`（有第三方依赖时）
   - 插件代码（异步 HTTP 优先用 aiohttp/httpx，持久化数据存 data 目录）
   - 测试文件（至少一个 smoke test）
4. **合规检查**：metadata 字段合法、适配器键有效、无 requests 同步调用、数据不写插件源目录
5. **调试工作流**：运行 AstrBot → WebUI 插件管理热重载 → ruff 格式化

### 修复插件常见问题

- **metadata.yaml 解析失败** → 检查 YAML 语法，`help` 字段以 `[` 开头需加引号
- **AI 输出带 markdown** → 修改插件源码，添加 `_strip_markdown` 后处理函数
- **BOM 导致 JSON 解析失败** → 用 `printf` 或 SFTP 重写文件，确保无 BOM

### 生成 SSH 隧道工具

直接提供 `assets/tunnel-generator.html` 给用户，或根据其服务器信息定制。
用户在浏览器中配置隧道 → 生成 ssh 命令 → 粘贴到终端执行。

## 支持的适配器键

用于 `metadata.yaml` 的 `support_platforms` 字段：

`aiocqhttp` · `qq_official` · `telegram` · `wecom` · `lark` · `dingtalk` · `discord` · `slack` · `kook` · `vocechat` · `weixin_official_account` · `satori` · `misskey` · `line`

## 关键注意事项

### 部署运维

- **login.config 凭据读取 SOP**：当用户提到 SSH 远程操作时，先检查项目根目录下是否存在 `login.config` 文件。若存在且可解析（格式见下），直接读取 IP/端口/用户名/密码，**不要询问用户凭据**，只需确认"要帮你远程操作吗？"即可。若文件不存在或解析失败，再向用户索取。`login.config` 格式：
  ```
  ssh:IP:端口
  name:用户名
  psw:密码
  ```
- Windows 本地通过 paramiko 库实现 SSH 远程操作（系统 ssh.exe 需要交互式密码输入）
- PowerShell 中传递含特殊字符的命令时，优先用 SFTP 上传文件而非 heredoc
- `astrbot init` 是交互式的，需用 `invoke_shell` + 自动应答
- NapCat WebUI 端口配置在 `config/webui.json`，字段为 `port`
- aiocqhttp 反向 WS 连接地址必须包含 `/ws` 路径
- uv 部署方式不支持 WebUI 升级，需用 `uv tool upgrade astrbot`
- **无 GPU 服务器安装 torch/sentence-transformers**：必须使用 CPU-only 索引安装 torch，否则会下载 2GB+ 无用的 CUDA/nvidia 包（cudnn 444MB、cublas 542MB 等）。正确命令：
  ```bash
  {astrbot_python} -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  {astrbot_python} -m pip install sentence-transformers --no-deps
  {astrbot_python} -m pip install transformers huggingface-hub scikit-learn scipy nltk tokenizers
  ```
  其中 `{astrbot_python}` 为 uv 部署的 Python 路径，通常为 `/root/.local/share/uv/tools/astrbot/bin/python`。

### 插件开发

- 插件目录命名：小写、无空格、建议前缀 `astrbot_plugin_`
- `astrbot_version` 遵循 PEP 440，不加 `v` 前缀（如 `>=4.17.0`）
- 持久化数据必须存放在 AstrBot `data` 目录，不写插件源目录
- 网络请求避免 `requests`，优先异步 `aiohttp` 或 `httpx`
- OpenAPI 基址默认 `http://localhost:6185`，端点 `/api/v1/*`，鉴权头 `X-API-Key`
- API Key 从配置或环境变量读取，不硬编码
- 生成代码提交前用 ruff 格式化
- `_conf_schema.json` 中 `type: "string"` 配合 `options` 数组（如 `"options": ["a", "b"]`）可在 WebUI 渲染为下拉菜单。不支持 `choices` 或 `type: "select"`。支持的类型：`int`、`float`、`bool`、`string`、`text`、`list`、`file`、`object`、`template_list`
- 官方文档：[插件开发](https://docs.astrbot.app/dev/star/plugin-new.html) · [OpenAPI](https://docs.astrbot.app/scalar.html)
