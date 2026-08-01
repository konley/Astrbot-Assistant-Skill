# AstrBot Skill — 快速入门

给机器人维护人的最短上手路径。更详细的契约见 `remote-ops-playbook.md` / `plugin-dev-playbook.md`。

## 第一步：确认能干活

```bash
python scripts/astrobot.py ops whoami        # 确认 runtime 模式（local/remote）与凭据
python scripts/astrobot.py doctor            # 环境体检 + login.config 配置漂移检查
python scripts/astrobot.py version           # 框架版本是否与 skill 缓存对齐
```

> 建议每次新会话先跑 `whoami`。`doctor` 里的 `config_drift` 有值时说明 login.config 与主机不一致。

## 日常三件事

### 1. 看日志 / 排障

```bash
python scripts/astrobot.py ops log astrbot --profile errors   # 最近报错
python scripts/astrobot.py ops log astrbot --since "30 min ago"  # 看一段时间
python scripts/astrobot.py ops trace                          # 消息流 5 步定位不回复
python scripts/astrobot.py ops diagnose                       # 全面开局体检
```

### 2. 重启 / 更新 / 自愈

```bash
python scripts/astrobot.py ops service status                 # 服务状态
python scripts/astrobot.py heal --yes                          # 启动失败自动修复（uv 依赖损坏）
python scripts/astrobot.py ops service restart --yes          # 重启（需确认）
```

更新 AstrBot 本体（uv 部署）：`uv tool upgrade astrbot`，WebUI 的更新按钮对 uv 部署无效。

### 3. 插件管理

```bash
python scripts/astrobot.py api plugins list                   # 已装插件及启停状态
python scripts/astrobot.py api plugins reload <name>          # 重载插件
python scripts/astrobot.py plugin new                         # 新建插件骨架
python scripts/astrobot.py plugin check <dir>                 # 交付前合规检查
```

## 记住的硬规矩

1. 改 cmd_config 用 `python scripts/astrobot.py config set ...`，别手改 JSON。
2. 重启服务、改生产配置前先问用户，带 `--yes` 才算确认。
3. 插件运行日志必须走 `astrbot.api.logger`，带 `[插件名]` 前缀。
4. `data/plugins/` 是插件目录，插件配置在 `data/config/`，数据在 `data/plugin_data/`。
5. 依赖框架 API 前先 `python scripts/astrobot.py version` 对齐版本。

## 完全不会了怎么办

`python scripts/astrobot.py ops whoami` → `ops diagnose --full`，然后按诊断提示走。最坏情况去看 `references/debug-handbook.md` 的故障决策表。
