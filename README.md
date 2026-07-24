# AstrBot Assistant Skill

面向 **AstrBot 远程运维 + 插件工程** 的 Codex/Agent Skill：把易错操作收成 CLI，把排障路径写成契约。

> Agent 入口：[`SKILL.md`](./SKILL.md)  
> 人类快速上手：本文 + `references/`

## 安装

1. 克隆或拷贝本目录到任意路径  
2. 链接/拷贝到 Codex skills 目录（或配置 skill 搜索路径）  
3. `pip install paramiko`（远程工具依赖）  
4. 生成凭据：

```powershell
python scripts/ssh-exec.py init-config
# 编辑 login.config（不要提交 git）
python scripts/ssh-exec.py whoami
```

可选环境变量：`ASTRBOT_SKILL_ROOT`、`ASTRBOT_LOGIN_CONFIG`、`ASTRBOT_SSH_IDENTITY`、`ASTRBOT_SSH_PASSWORD`。

## 目录

```
Astrbot-Assistant-Skill/
├── SKILL.md                 # Agent 导航 + 硬约束
├── agents/openai.yaml       # UI 元数据
├── scripts/                 # CLI（首选）
├── assets/                  # 模板 / tunnel HTML；*.py 仅为兼容 shim
├── references/              # 按需 SOP
├── tests/                   # skill 自身最小回归
└── AstrBot/                 # 可选源码缓存（gitignore）
```

## 常用命令

```powershell
$A = Join-Path $env:ASTRBOT_SKILL_ROOT "scripts"
python "$A\ssh-exec.py" diagnose --full
python "$A\ssh-exec.py" trace --since "30 min ago"
python "$A\ssh-exec.py" service status
python "$A\ssh-exec.py" tunnel print
python "$A\ssh-exec.py" framework check
python "$A\config-tool.py" get platform.0
python "$A\astrbot-api.py" --via-ssh plugins list
python "$A\plugin-scaffold.py" --from-login-config --name astrbot_plugin_demo --desc "demo"
# optional lifecycle: add --with-lifecycle
python "$A\plugin-check.py" .\astrbot_plugin_demo
python "$A\git-identity.py" check-push --repo .\astrbot_plugin_demo
```

## 安全提示

- `login.config` 含主机与密钥/密码信息，**禁止入库**（已在 `.gitignore`）
- 优先 `identity_file` / ssh-agent；`tunnel` 不会把密码写进命令行
- 生产环境避免长期 root + 明文密码

## 框架源码缓存

本地 `./AstrBot` 仅供参考。写依赖框架 API 的代码前先：

```powershell
python scripts/ssh-exec.py framework check
# 不一致时（需确认）：
python scripts/ssh-exec.py framework sync --yes
```

详见 [`references/source-version-align.md`](./references/source-version-align.md)。

## 文档地图

| 场景 | 文档 |
|------|------|
| 远程排障 | `references/remote-ops-playbook.md` |
| 插件开发 | `references/plugin-dev-playbook.md` |
| API 速查 | `references/api-cheatsheet.md` |
| Agent / Tools | `references/agent-tools.md` |
| Debug | `references/debug-handbook.md` |
| 版本对齐 | `references/source-version-align.md` |
| 配置权威表 | `references/config-reference.md` |
| Plugin Page | `references/plugin-page-patterns.md` |

## License

[MIT](./LICENSE)
