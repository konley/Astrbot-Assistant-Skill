# 框架源码版本对齐（source cache）

> **使用前必读**：依赖框架 API / 查 `./AstrBot/` 源码前，先跑 `framework check`。  
> 远端 runtime 是真相源；本地缓存只是按版本 pin 的只读参考。

## 问题

Skill 会在 skill 根维护：

- `AstrBot/` — **当前激活**的只读参考树（Agent 默认 read/grep 这里）
- `cache/AstrBot/<version>/` — 多版本 pin 缓存
- `framework-cache.meta.json` — 最近一次成功对齐的元数据（TTL 辅助）

真实机器人跑在远端（uv tool / pip / 源码安装皆可能）。**本地缓存版本 ≠ 远端运行版本** 时：

- 插件调用了新版才有的 API → 远端 ImportError / AttributeError
- 按旧版写适配 → 新版行为变化踩坑
- `references/source-*.md` 行号漂移，误导定位

因此：**本地 AstrBot/ 只是参考副本，不是生产真相源。**

## 标准流程

### 1. 查源码 / 写依赖框架 API 的代码之前

```powershell
$S = $env:ASTRBOT_SKILL_ROOT  # 或 skill 根绝对路径
python "$S\scripts\ssh-exec.py" framework check
python "$S\scripts\ssh-exec.py" framework check --json
python "$S\scripts\ssh-exec.py" framework check --offline
```

| status | 含义 | 动作 |
|--------|------|------|
| `match` | 本地 version == 远端 | 可用本地缓存查阅 |
| `mismatch` | 不一致 | **先 sync** 或不要依赖本地 API 形状 |
| `local_missing` | 无可用缓存版本 | `framework sync --yes` |
| `remote_unknown` | 探不到远端版本 | 配 `[paths].python_bin` / 查 unit；以运行时验证为准 |

退出码：`0` match，`3` mismatch，`2` 其它未知。

### 2. 对齐本地缓存（版本 pin，禁止 latest fallback）

```powershell
python "$S\scripts\ssh-exec.py" framework sync --yes
python "$S\scripts\ssh-exec.py" framework sync --yes --tag 4.26.7
```

实现要点：

1. 先探测远端版本（uv tool python → systemd ExecStart → `astrbot version` → 系统 python）
2. 只拉取 `v{version}` / `{version}` **精确 tag**
3. 写入 `cache/AstrBot/<version>/`，再激活到 `AstrBot/`
4. 写 `framework-cache.meta.json`
5. **tag 拉不到 → 硬失败**，绝不 clone 默认分支当成功

### 3. 对齐后如何查

1. 用符号/字符串搜，不要死扣行号
2. 再打开 `references/source-*.md` 当索引
3. 改插件只在插件仓库；验证走远端 reload + 日志

### 4. 无法对齐时的降级策略

1. 远端用探测到的 python 做 `import astrbot,inspect`
2. 读远端 site-packages / uv tool 树
3. 最小插件探针
4. 文档声明基于远端 x.y.z，不假装本地权威

## Agent 检查清单

- [ ] 需要框架 API？先 `framework check`
- [ ] mismatch 已告知并 `sync --yes`？
- [ ] 未误改 `./AstrBot/` / `cache/AstrBot/`？
- [ ] 验证走远端 reload + log？
