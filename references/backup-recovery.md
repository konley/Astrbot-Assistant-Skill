# Backup and Recovery

备份不是只复制 `cmd_config.json`。至少覆盖：

- `data/cmd_config.json`
- `data/config/`
- `data/plugins/`
- `data/plugin_data/`
- `data/skills/`
- `data/workspaces/`
- `data/knowledge_base/`

恢复前必须创建当前状态备份，显示 runtime/host/实例路径，并要求用户确认。恢复后重新执行 `doctor`、`framework check`、插件 list/reload 和错误日志检查。

API Key、WebUI 密码、provider key 等敏感字段不能出现在诊断输出、备份索引或提交中。生产环境优先备份到权限受限目录，并保留版本和时间戳。
