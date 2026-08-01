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

uv 部署不支持 WebUI 升级（WebUI 的 `/api/update_project` 会报 "please use `pip` or `uv tool upgrade`"，属预期，忽略即可）：

```bash
uv tool upgrade astrbot --python 3.12
```

升级前先备份配置、插件配置、插件数据、Skills 和知识库；升级后执行 `framework check`、插件 reload 和日志检查。升级是改生产环境，须用户确认 + `--yes`。

## 更新后故障排查

- 升级后服务启动失败，报 `ModuleNotFoundError: No module named 'urllib3'`（或 "The requests library is not installed"）：升级常残留损坏的包安装（只剩 dist-info、包文件缺失）。修复：
  ```bash
  uv tool upgrade --reinstall astrbot   # 注意不是 --force，uv 无该参数
  ```
  重装后验证 `uv tool python` 环境能导入 urllib3/requests，再 `service restart --yes`。
- 日志会短暂混杂旧失败进程的 Traceback（PID 与当前不同）；确认当前进程（`service status` 的 Main PID）无 `[ERRO]`/Traceback 再判定恢复。
