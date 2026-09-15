---
name: codex-ops-portable
description: "Use for portable, evidence-first Codex operations: source/deployment audits, Python CLI validation, secret-safe execution, and review packets."
---

# Portable Codex Operations

> **DEPRECATED 2026-09-15 — Codex CLI 已退役。**
> 本技能描述的是 `codex review` / `codex exec` / Codex 沙箱与凭据边界，退役后不再有可执行路径。
> - 只作历史记录保留，**不要**按其中的命令操作。
> - 现行等价能力：dsh 会话本身（只读审计用只读命令 + `runs/` 证据），代码复核用 `python -m article_group.codex_review --mode l2 --review-json <review.json>`。
> - 全局技能已迁移到 `~/.agents/skills/`。


Use this skill for bounded work that can run from a Git repository without Hermes private state. The skill covers evidence collection, local validation, and review preparation. It does not grant permission to publish, merge, deploy, change access boundaries, promote state, or modify remote systems.

## Scope and safety

1. Read the project `AGENTS.md` and the task-specific acceptance criteria before acting.
2. Run `git status --short --branch` before editing. Preserve unrelated modified and untracked files.
3. Keep writes inside the explicitly named project paths. Use `--sandbox read-only` for inspection and `--sandbox workspace-write` only for a bounded local edit.
4. Never read or copy `auth.json`, `.env`, cookies, tokens, private keys, or Hermes session, memory, Gateway, Dashboard, or Kanban databases.
5. Credentials may be used only through an already-approved local login or a narrowly whitelisted runtime environment. Never put a credential in a prompt, command argument, source file, review artifact, or log.
6. Treat Codex output as evidence. The controller or user retains publication, merge, deployment, configuration, and state-promotion authority.

## Source and deployment sync audit

Use this when a source tree and a running or deployed tree may differ.

1. Identify the exact source root, deployment root, service unit, and file/object under review.
2. Capture read-only facts first:

```bash
git status --short --branch
systemctl --user status <service> --no-pager
systemctl --user show <service> -p MainPID -p WorkingDirectory -p ExecStart
readlink -f /proc/<pid>/cwd
```

3. Inspect import identity and hashes for named files. Do not recursively dump configuration directories; exclude credential-like names from inspection.
4. Record the source revision, deployment identity, command, timestamp, exit status, and freshness basis in the review run directory.
5. If a change is explicitly authorized, retain an exact recovery point or inverse before changing one bounded object. Verify the exact post-change state by reading the same object back.
6. Do not infer that a directory named `deploy`, `runtime`, or `.hermes` is active. Confirm the service process and import path.

For local code review, Codex provides a bounded read-only path:

```bash
codex review --uncommitted "Check the requested contract and report evidence-backed findings only."
codex exec --sandbox read-only --ephemeral -C /path/to/repo "Inspect the named files; do not edit or access credentials."
```

## Python CLI runtime validation

1. Read `pyproject.toml` and the neighboring tests before choosing a command.
2. Prefer the project environment and existing test entrypoint:

```bash
uv run pytest -q tests/test_<focused>.py
python -m py_compile scripts/<entrypoint>.py
python scripts/<entrypoint>.py --help
```

3. Exercise both a valid path and a negative path such as missing input, missing credential, malformed schema, or an existing immutable artifact.
4. Use `subprocess.run` with an argument list and an explicit, minimal environment in helper code. Avoid `shell=True` and avoid printing inherited environment variables.
5. Verify generated manifests, hashes, and status fields by reading them back. A zero exit code alone is not acceptance evidence.

For a structured Codex response, pass a reviewed schema and retain the raw output alongside the parsed result:

```bash
codex exec --sandbox read-only --ephemeral \
  --output-schema schemas/review-contract.json \
  -C /path/to/repo \
  "Return only the fields required by the schema and cite the files inspected."
```

## Deterministic secret-safe handling

- Keep secret presence, source, permission, and acquisition method as metadata when needed; replace values with `[REDACTED]`.
- Do not use `env`, `set`, `printenv`, shell tracing, debug dumps, or credential-bearing command arguments.
- Prefer an existing secure wrapper or native Codex login. A provider bridge may whitelist only explicitly approved names such as `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL`; the values must remain in the child process and never enter project artifacts.
- Scan output and evidence artifacts for known credential markers before delivery. If a secret appears, stop, remove the exposed artifact, and rerun the operation with a clean output path.

## Review-readiness packet

For material review work, prepare a versioned packet containing:

- original request reference and controller-assigned risk tier;
- acceptance criteria with one evidence reference per criterion;
- non-goals and the exact artifact/version identity;
- command or path, execution timestamp, exit/result, and freshness basis for each evidence item;
- negative-path evidence for each falsifiable criterion, or a named justified gap;
- attack-surface notes and named coverage gaps.

A review packet is ready only when every required field is present and every reference resolves. Missing fields block review intake; they are not review findings. A reviewer may identify findings, but the result remains evidence and does not authorize publication, merge, deployment, or configuration change.

## Codex-native substitutes

- Reusable procedure: project-local `.agents/skills/<name>/SKILL.md`.
- Project rules: `AGENTS.md`.
- One-shot bounded execution: `codex exec` with an explicit `-C` and sandbox mode.
- Code review: `codex review --uncommitted`, `--base`, or `--commit`.
- Structured output: `codex exec --output-schema <schema.json>`.
- External systems: an explicitly reviewed MCP server (`codex mcp list`, `codex mcp get`) or a narrowly scoped local CLI.
- Local scheduling: a user-level `systemd` timer or another existing scheduler, with immutable run artifacts and no implicit state promotion.
- Multi-agent work: Codex agents or separate worktrees only when the task is explicitly partitioned and each result is independently checked.

Do not emulate Hermes Gateway, Dashboard, Kanban, memory, session database, cost router, or model-authority semantics inside this skill. Use the project documents and the approved local bridge for those boundaries.
