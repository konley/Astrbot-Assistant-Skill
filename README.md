# AstrBot Assistant Skill

AstrBot 全流程助手 Skill，覆盖从零部署到日常运维、从插件开发到合规检查的完整链路。

## 功能概览

### 部署与运维
- AstrBot 框架部署（uv 包管理器、systemd 保活）
- NapCat QQ 适配器安装与对接
- SSH 隧道可视化工具
- AI 人格 Prompt 生成
- 常见问题排障

### 插件开发
- 从自然语言需求生成插件脚手架
- metadata.yaml / requirements.txt 模板
- 合规检查（适配器键、版本约束、代码规范）
- 测试模板（smoke / behavior / OpenAPI 鉴权）
- AstrBot OpenAPI 集成指南

## 目录结构

```
├── SKILL.md                          # Skill 主入口
├── references/
│   ├── deploy-guide.md               # AstrBot + NapCat 部署指南
│   ├── troubleshooting.md            # 常见问题排障
│   ├── config-reference.md           # 配置文件参考
│   ├── plugin-new-checklist.md       # 新插件官方检查清单
│   ├── nl-to-implementation.md       # 自然语言→实现工作流
│   ├── compliance-checklist.md       # 合规检查清单
│   ├── testing-guide.md              # 测试指南
│   └── openapi-integration.md        # OpenAPI 集成参考
└── assets/
    ├── tunnel-generator.html         # SSH 隧道生成器
    ├── metadata.yaml.template        # 插件 metadata 模板
    ├── requirements.txt.template     # 依赖模板
    ├── test_plugin_smoke.py.template # 冒烟测试模板
    ├── test_plugin_behavior.py.template  # 行为测试模板
    ├── test_openapi_auth_and_shape.py.template  # OpenAPI 测试模板
    └── dev-commands.txt              # 开发常用命令
```

## 使用方式

将本目录安装为 Box/VS Code Copilot 的 Skill，即可在对话中触发 AstrBot 全流程辅助。

## 相关文档

- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot OpenAPI](https://docs.astrbot.app/scalar.html)
- [AstrBot GitHub](https://github.com/AstrBotDevs/AstrBot)

## License

MIT
