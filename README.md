# AstrBot Assistant Skill

AstrBot 全流程助手 Skill，覆盖从零部署到日常运维、从插件开发到合规检查的完整链路。

## 功能概览

### 部署与运维
- AstrBot 框架部署（uv 包管理器、systemd 保活）
- NapCat QQ 适配器安装与对接
- SSH 隧道可视化工具
- 一键三步诊断（服务状态 + 端口 + 近期错误日志）
- 常见问题排障

### 插件开发
- 从自然语言需求生成插件脚手架
- metadata.yaml / requirements.txt 模板
- 合规检查（适配器键、版本约束、代码规范、BOM 预检）
- 测试模板（smoke / behavior / OpenAPI 鉴权）
- AstrBot OpenAPI 集成

### Debug
- 8 类场景 debug 手册（不回复 / 加载失败 / 405 / LLM / 配置 / 指令 / 鉴权 / 性能）
- 框架源码精华查询（消息流 / 插件内部机制 / 配置 schema）
- 本地源码缓存 + 按需 read/grep

## 目录结构

```
├── SKILL.md                              # Skill 主入口（导航 + 硬约束）
├── references/
│   ├── debug-handbook.md                 # Debug 手册（8 类场景 + 三步法）
│   ├── source-message-flow.md            # 消息流源码精华
│   ├── source-plugin-internals.md        # 插件加载/重载/注册机制
│   ├── source-config-schema.md           # 配置 schema 权威详解
│   ├── deploy-guide.md                   # AstrBot + NapCat 部署指南
│   ├── troubleshooting.md                # 边缘案例排障
│   ├── config-reference.md               # 配置文件/路径/login.config 权威表
│   ├── plugin-lifecycle.md               # 插件生命周期 SOP
│   ├── plugin-new-checklist.md           # 新插件官方检查清单
│   └── compliance-checklist.md           # 合规检查 + 需求解析 + 测试
└── assets/
    ├── _common.py                        # SSH 公共库（基座）
    ├── ssh-exec.py                       # SSH/SFTP/查日志 CLI
    ├── astrbot-api.py                    # WebUI/OpenAPI HTTP CLI
    ├── config-tool.py                    # cmd_config.json 读写 CLI
    ├── plugin-scaffold.py                # 插件骨架生成器
    ├── logo-process.py                   # Logo 自动处理
    ├── tunnel-generator.html             # SSH 隧道生成器
    ├── metadata.yaml.template            # 插件 metadata 模板
    ├── requirements.txt.template         # 依赖模板
    ├── test_plugin_smoke.py.template     # 冒烟测试模板
    ├── test_plugin_behavior.py.template  # 行为测试模板
    ├── test_openapi_auth_and_shape.py.template  # OpenAPI 测试模板
    └── dev-commands.txt                  # 开发常用命令
```

## 使用方式

将本目录安装为 opencode 的 Skill（放到 `.opencode/skills/astrbot-assistant/` 下），即可在对话中触发 AstrBot 全流程辅助。

## 相关文档

- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot OpenAPI](https://docs.astrbot.app/scalar.html)
- [AstrBot GitHub](https://github.com/AstrBotDevs/AstrBot)

## License

MIT
