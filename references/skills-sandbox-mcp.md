# Skills / Sandbox / MCP

这些是 AstrBot runtime 能力，不是本 Codex/OpenCode skill。写插件或排障时先确认运行环境。

## Skills

来源和优先级：

- `data/skills/<name>/SKILL.md`
- 插件内 `skills/<name>/SKILL.md`
- Sandbox 预置 Skills
- 当前会话 workspace：`data/workspaces/{normalized_umo}/skills/<name>/SKILL.md`

同名时 workspace 优先于本地、插件和 sandbox；插件卸载或更新会同步影响其内置 Skills。local 与 sandbox 的文件路径和同步语义不同。

## Sandbox

官方当前推荐 Shipyard Neo，也兼容旧 Shipyard 和 CUA。Neo 的 Bay 默认端口为 `8114`，workspace 根为 `/workspace`，profile 的 `capabilities` 决定是否提供 browser、shell、python、filesystem。

排障重点：

- `Computer Use Runtime=sandbox`
- driver、endpoint、profile、TTL、API token
- Bay 连通性、session、Cargo 持久化、warm pool 和 GC
- CUA 需要额外 `cua` 依赖，非 POSIX 镜像不保证 `sh/ls/rm`

## MCP

MCP server 通常通过 `uv` 或 `node/npm` 启动。Docker 部署必须在 AstrBot 容器或数据卷中准备依赖。使用 API 时需要 `mcp` scope；不要把 token 放进日志，配置改动后按实例能力 reload 或 restart。

相关 API：`GET/POST /api/v1/mcp/servers`、`PATCH /api/v1/mcp/servers/{name}/enabled`、ModelScope sync。

## 主动 Agent

FutureTask/Cron 是全局持久化任务，不等同于插件临时 task。任务需要可恢复的 UMO、时区和主动消息平台支持。官方当前支持主动推送的平台包括 Telegram、OneBot v11、Slack、Lark、Discord、Misskey、Satori。
