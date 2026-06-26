# Natural Language To Implementation Workflow

Use this when the user only provides free-form natural language requirements.

## 1) Requirement Parsing
Extract and restate:
- Goal: what plugin should solve
- Triggers: command/event/timing
- Inputs: user text, config, context
- Outputs: reply/action/side effects
- Constraints: adapters, version, performance, security

If any item is missing, use safe defaults and mark assumptions explicitly.

## 2) Implementation Planning
Turn parsed requirements into concrete artifacts:
- Files to create/update
- Core functions/classes to implement
- Error handling strategy
- Data persistence location (`data` directory)

## 3) Build Order
1. metadata.yaml (include `repo` field = `{github_root}/{plugin_folder_name}` if GitHub link is available)
2. requirements.txt
3. plugin code
4. tests
5. logo processing (optional: run `assets/logo-process.py`)
6. final checklist (remind user about logo on first git commit)

## 4) Completion Contract
Before finish, verify:
- behavior matches requirement summary
- assumptions are listed
- `repo` field in metadata.yaml is correctly populated (if GitHub link available)
- user can run/debug/reload with clear steps
- remind user about optional logo on first git commit
