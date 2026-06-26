# AstrBot Plugin New Checklist (Official-doc aligned)

## Environment Setup
1. Create plugin repository from template (helloworld):
   - https://github.com/Soulter/helloworld
2. Repository naming rules:
   - prefer prefix astrbot_plugin_
   - lowercase only
   - no spaces
   - keep short
3. Local setup example:

```bash
git clone https://github.com/AstrBotDevs/AstrBot
mkdir -p AstrBot/data/plugins
cd AstrBot/data/plugins
git clone <your_plugin_repo_url>
```

4. Open AstrBot project in VS Code and locate plugin under data/plugins/<plugin_name>.

## Must-have Metadata
AstrBot relies on metadata.yaml to identify plugin metadata.

Required minimum:
- name
- desc
- version
- author
- repo (repository URL; if login.config contains GitHub link, auto-fill as {github_url}/{plugin_name})

Optional common fields:
- display_name
- support_platforms (list[str])
- astrbot_version (PEP 440 constraint, no v prefix)

AstrBot version examples:
- >=4.17.0
- >=4.16,<5
- ~=4.17

## Adapter Keys For support_platforms
- aiocqhttp
- qq_official
- telegram
- wecom
- lark
- dingtalk
- discord
- slack
- kook
- vocechat
- weixin_official_account
- satori
- misskey
- line

## Optional Assets
- logo.png in plugin root
- 1:1 ratio, recommended 256x256
- Use `assets/logo-process.py` to auto-convert any image to 256x256 centered-square PNG

## Config Schema (`_conf_schema.json`)
可选，用于在 WebUI 渲染配置面板。

- 支持的类型：`int`、`float`、`bool`、`string`、`text`、`list`、`file`、`object`、`template_list`
- `type: "string"` 配合 `options` 数组可在 WebUI 显示为下拉菜单（不支持 `choices` 或 `type: "select"`）
- 示例：
  ```json
  "default_tone": {
    "description": "默认辞气",
    "type": "string",
    "default": "自动",
    "options": ["自动", "温言", "辩经"],
    "hint": "选择默认辞气风格"
  }
  ```

## Debug and Reload
- Start AstrBot runtime for plugin debugging.
- After code changes, use WebUI plugin management and reload plugin.
- If load fails, use one-click reload/repair option in management panel.

## Dependency Management
- Use requirements.txt for third-party dependencies.
- Missing dependencies can break plugin installation.

## Development Principles
- Test features before release.
- Keep useful comments.
- Store persistent data under data directory, not plugin directory.
- Add robust error handling.
- Prefer async HTTP clients (aiohttp/httpx), avoid requests.
- Run ruff formatting before commit.

## Related Docs
- New plugin guide: https://docs.astrbot.app/dev/star/plugin-new.html
- Minimal example: https://docs.astrbot.app/dev/star/guides/simple.html
- Plugin publish: https://docs.astrbot.app/dev/star/plugin-publish.html