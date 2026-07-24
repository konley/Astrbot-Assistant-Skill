# 插件开发作战手册（做/改插件主路径）

> 本文件是 **做插件 / 改插件** 的权威 SOP。`SKILL.md` 只放硬约束摘要。
> 目标：作者/仓库/logo/版本/身份一气呵成，**绝不静默用本机 global 公司 git 账号 push**。

## 0. 工具一览

| 工具 | 作用 |
|---|---|
| `plugin-scaffold.py` | 生成合规骨架；`--from-login-config` 注入 author/github |
| `plugin-check.py` | 元数据/logo/repo/BOM/@register 检查；`--bump` 升版 |
| `git-identity.py` | 锁定 login.config 个人身份：`show` / `status` / `fix` / `check-push` |
| `logo-process.py` | logo 处理（可选） |
| `ssh-exec.py sync-plugin` | 本地 → 远端插件目录同步 |
| `astrbot-api.py --via-ssh` | 远端 plugins install/reload/list |

路径一律优先 **scripts 绝对路径**（`$env:ASTRBOT_SKILL_ROOT\scripts\...`）。

---

## 1. 身份原则（只认个人）

1. **唯一身份源**：`login.config` 扁平 `[git]`：

```ini
[git]
# 个人身份（唯一默认）。不要填公司账号。
user = yourname
email = you@example.com
github = https://github.com/yourname
```

2. **不提供「公司 profile」工作流**。多 profile 解析代码可兼容旧文件，但 UX/模板/本手册一律只教扁平个人身份。
3. **push 前门禁**：

```bash
python scripts/git-identity.py check-push --repo <plugin_dir>
# 失败 → 锁定 local（从不改 global）
python scripts/git-identity.py fix --repo <plugin_dir>
```

4. 禁止：静默用 global 公司账号推个人插件；禁止在文档里引导用户填写公司账号。

---

## 1.5 框架版本门禁（写依赖 API 前）

依赖 AstrBot 框架符号 / 查 `./AstrBot/` 源码前：

```bash
python scripts/ssh-exec.py framework check
# mismatch / local_missing → 征得用户同意后：
python scripts/ssh-exec.py framework sync --yes
```

详见 `source-version-align.md`。**禁止**在版本未知或 mismatch 时凭本地缓存 invent API。

---

## 2. 新建插件流程

### 2.1 门禁提问（写业务前必做）

1. **author**：是否用 `login.config [git].user`？（默认是）
2. **仓库策略**：
   - `auto`：`{github}/{plugin_name}`（引导用户确认是否已有/需新建/fork）
   - 显式 URL
   - `none`：不写 repo 字段
3. **logo**：有图路径 / 暂无 / 后补

### 2.2 生成骨架

```bash
python scripts/plugin-scaffold.py \
  --name astrbot_plugin_example \
  --desc "一句话描述" \
  --from-login-config \
  --repo auto
# 或 --repo none / --repo https://github.com/you/astrbot_plugin_example
```

### 2.3 写业务 + 合规检查

```bash
python scripts/plugin-check.py ./astrbot_plugin_example
# 无 FAIL 才能交付；logo 缺失通常是 WARN
```

### 2.4 本地迭代部署（未发布）

```bash
python scripts/ssh-exec.py sync-plugin ./astrbot_plugin_example --name astrbot_plugin_example
python scripts/astrbot-api.py --via-ssh plugins reload --name astrbot_plugin_example
```

### 2.5 首次 git 身份锁定

```bash
cd astrbot_plugin_example
git init   # 若尚未
python ../Astrbot-Assistant-Skill/scripts/git-identity.py fix --repo .
python ../Astrbot-Assistant-Skill/scripts/git-identity.py check-push --repo .
```

---

## 3. 修改已有插件流程

1. 读当前 `metadata.yaml` + 改动意图。
2. 改代码 / 配置 / README。
3. 收尾：

| 改动类型 | version | 其它字段 |
|---|---|---|
| 修 bug / 小改 | patch `0.1.0→0.1.1` | 通常不动 desc |
| 新功能 / 新命令 | minor `0.1.x→0.2.0` | 视情况更新 desc / README |
| 破坏性变更 | major | desc + README 必更 |
| 改作者可见信息 | 可 patch | author / repo / display_name |
| 新增依赖 | patch/minor | `requirements.txt`；远端可能需 reinstall |
| 改配置项 | patch/minor | `_conf_schema.json` |
| 仅注释/格式 | 可不升 | 说明「无功能变更」 |
| 首次交付 | 0.1.0 | logo、repo、tests 走门禁 |

```bash
python scripts/plugin-check.py <dir>
python scripts/plugin-check.py <dir> --bump patch   # 需要时
```

`plugin-check --bump` 会同步改 `metadata.yaml` 的 `version` 与 `main.py` 里 `@register(..., version=...)`（能匹配到时）。

---

## 4. Push 前检查清单

- [ ] `git-identity.py check-push` 通过（local == login.config 个人身份）
- [ ] `plugin-check.py` 无 FAIL
- [ ] version 已按改动类型处理（或用户明确不升）
- [ ] repo 字段与真实仓库一致（或 none）
- [ ] logo 三态已处理
- [ ] 用户知道如何 reload

```bash
python scripts/git-identity.py show
python scripts/git-identity.py status --repo .
python scripts/git-identity.py fix --repo .
python scripts/git-identity.py check-push --repo .
```

---

## 5. 发布 vs 本地同步

| 场景 | 动作 |
|---|---|
| 本地快速试 | `sync-plugin` + `plugins reload` |
| 发布 / 分享 / 装到别人机器 | `check-push` 通过 → commit → push → WebUI 安装/更新 |

---

## 6. 与合规文档关系

- 详细字段/测试/BOM：`compliance-checklist.md`
- 官方新插件清单：`plugin-new-checklist.md`
- 重载 vs 重启：`plugin-lifecycle.md`
- **流程门禁与身份：以本文为准**
