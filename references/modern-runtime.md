# Modern AstrBot Runtime

本手册对应官方 `v4.26.x` 运行模型。先执行 `python scripts/doctor.py --json`，再执行 `ssh-exec.py whoami`。

## Runtime 类型

AstrBot 可能运行在：

- uv/package：工作目录由 `ASTRBOT_ROOT` 或当前目录决定，Python 3.12+
- Docker/Compose：容器内根目录通常为 `/AstrBot`，数据通过 `/AstrBot/data` volume 持久化
- systemd：使用 `ssh-exec.py service ...`
- Kubernetes/Desktop/Launcher：优先使用官方控制面或容器 API，不能假设 systemd

Docker 中不要把宿主机 `localhost` 当作 AstrBot 或其他容器地址。远程 dashboard 优先 `astrbot-api.py --via-ssh`。

## 当前路径

官方当前默认：

```text
data/plugins/
data/config/<plugin_name>_config.json
data/plugin_data/
data/skills/
data/workspaces/
data/knowledge_base/
data/backups/
```

`data/addons/plugins/` 仅作为历史实例兼容路径，由 `config discover` 和 `sync-plugin` 探测。

## 更新

uv 部署不支持 WebUI 升级：

```bash
uv tool upgrade astrbot --python 3.12
```

升级前先备份配置、插件配置、插件数据、Skills 和知识库；升级后执行 `framework check`、插件 reload 和日志检查。
