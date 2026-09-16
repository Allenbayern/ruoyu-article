#!/usr/bin/env python3
"""共享 LLM 客户端（shenwendp openai-completions，凭据走最小通路）。

供仓库内脚本（dailyhot_classify / ledger_coverage_precheck 等）复用：
- 凭据：~/.config/ruoyu-llm/env（600 权限：RUOYU_LLM_API_KEY/BASE_URL/MODEL），
  或同名环境变量；密钥只进内存，不写日志、不回显、不入产物；
- chat()：单轮对话，reasoning_effort=low，失败抛 LlmUnavailable（调用方降级）；
- parse_json_array()：从模型输出中稳健提取 JSON 数组（容忍代码块与前后噪声）。
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ENV_FILE = Path.home() / ".config" / "ruoyu-llm" / "env"

MAX_TOKENS = 6000
TIMEOUT = 180


class LlmUnavailable(RuntimeError):
    """LLM 调用失败：调用方应降级（关键词启发式 / 人工）。"""


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith("RUOYU_LLM_")})
    if not values.get("RUOYU_LLM_API_KEY"):
        raise SystemExit("未找到 RUOYU_LLM_API_KEY（~/.config/ruoyu-llm/env 或环境变量）")
    return values


def chat(env: dict[str, str], system: str, user: str, max_tokens: int = MAX_TOKENS) -> str:
    payload = {
        "model": env.get("RUOYU_LLM_MODEL", "deepseek-v4.1-flash"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "reasoning_effort": "low",
    }
    req = urllib.request.Request(
        f"{env['RUOYU_LLM_BASE_URL']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {env['RUOYU_LLM_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise LlmUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if body.get("error"):
        raise LlmUnavailable(str(body["error"])[:200])
    message = (body.get("choices") or [{}])[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise LlmUnavailable("empty_content")
    return content


def parse_json_array(text: str) -> list[dict] | None:
    """从模型输出里稳健提取 JSON 数组；失败返回 None（调用方降级）。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(stripped[start : end + 1])
        return value if isinstance(value, list) else None
    except json.JSONDecodeError:
        return None


__all__ = ["ENV_FILE", "LlmUnavailable", "chat", "load_env", "parse_json_array"]
