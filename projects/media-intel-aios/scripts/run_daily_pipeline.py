#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import os
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import openai


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
WORKSPACE = ROOT.parent.parent
HANDOVER = WORKSPACE / "handover-hotspot"
QUALITY = HANDOVER / "04-QUALITY-FEEDBACK"
ARTICLE_SAMPLES = ROOT / "article-vault" / "samples"
STORY_SAMPLES = ROOT / "story-vault" / "samples"
MEDIA_SAMPLES = ROOT / "media-vault" / "samples"
HOTBOARD_SAMPLES = ROOT / "hotboard" / "samples"
ARTICLE_INDUSTRY_SOURCES = {
    "毒眸",
    "dumou",
    "36kr",
    "36氪",
    "huxiu",
    "虎嗅",
    "jiemian",
    "界面",
    "澎湃",
    "thepaper",
    "壹娱观察",
    "娱乐资本论",
    "犀牛娱乐",
    "xiniu-yule",
}
ARTICLE_PRIORITY_SOURCES = ARTICLE_INDUSTRY_SOURCES | {"微信公众号", "wechat", "知乎", "zhihu", "豆瓣", "douban", "vocus"}
EMOTION_RADAR_SOURCES = {"hotboard", "tophub_today", "微博热点", "weibo_hotspot", "微博热搜", "知乎", "zhihu", "豆瓣", "douban", "豆瓣小组", "douban_group", "小红书", "xhs", "reddit", "hupu", "虎扑", "nga", "bilibili_comments", "douyin_comments", "微信公众号", "wechat", "netease_renjian", "网易人间"}
ARTICLE_TODAY_HOOK_SOURCES = EMOTION_RADAR_SOURCES | {"热榜"}
ARTICLE_DISCOVERY_SOURCES = {
    "guduo",
    "骨朵热度指数",
    "weibo_hotspot",
    "微博热点",
    "maoyan",
    "猫眼热榜",
}
ARTICLE_INDUSTRY_ROUTER_SOURCES = ARTICLE_INDUSTRY_SOURCES | {"36kr", "36氪", "huxiu", "虎嗅", "jiemian", "界面", "thepaper", "澎湃"}
ARTICLE_HOTCOMMENT_ROUTER_SOURCES = {
    "微信公众号", "wechat", "weixin",
    "知乎", "zhihu",
    "微博", "weibo", "weibo_media",
    "豆瓣", "douban",
    "豆瓣小组", "douban_group",
    "小红书", "xhs", "xhs_note",
    "netease_renjian", "网易人间",
}
ARTICLE_DISCOVERY_ROUTER_SOURCES = ARTICLE_DISCOVERY_SOURCES | {"hotboard", "tophub_today", "hotlist_web", "微博热搜"}
EMOTION_ROUTER_BLOCKED_SOURCES = {"hotboard", "tophub_today", "hotlist_web", "weibo_hotspot", "微博热点", "微博热搜", "maoyan", "猫眼热榜", "guduo", "骨朵热度指数"}


def load_scoring_config() -> dict[str, Any]:
    config_yaml = ROOT / "config" / "scoring-config.yaml"
    config_json = ROOT / "config" / "scoring-config.json"
    default_config: dict[str, Any] = {
        "anchor": {"floor_with_title_mark": 12, "floor_with_person": 12, "industry_floor": 8},
        "conflict_signals": {
            "strong": ["全网差评", "口碑翻车", "塌房", "扑街", "烂尾", "魔改", "群嘲", "抵制", "对线", "查税", "被封", "官宣离婚"],
            "mid": ["差评", "争议", "删减", "注水", "不买账", "质疑", "回应", "道歉", "维权", "塌", "崩"],
            "reverse": ["逆袭", "压番", "爆冷", "反转", "黑马", "意外"],
            "industry_conflict": ["当众求职", "档期很空", "看看我", "无戏可拍", "影视寒冬", "行业现状", "没人找", "接不到戏", "降咖", "待业", "失业", "没活", "寒冬", "塌方式失业"],
        },
        "analysis_question_terms": ["为什么", "为何", "凭什么", "如何", "怎么", "折射", "背后", "真相", "原因", "启示", "现状"],
        "pool_thresholds": {"S": 85, "A": 70, "B": 55},
        "mainline": {"anchor": 12, "conflict": 10, "analysis": 8},
        "semantic_scoring": {
            "backend": "rules",
            "rules": {
                "today_hook_bonus": 4,
                "pool_floor": {"s": 52, "a": 34, "a_fallback": 24, "b": 16},
                "mainline_anchor_floor": 12,
            },
            "llm": {
                "enabled": False,
                "provider": "openai",
                "model": "gpt-5.4-mini",
                "cache_ttl_hours": 72,
            },
            "embedding": {
                "enabled": False,
                "provider": "openai",
                "model": "text-embedding-3-small",
                "vector_size": 24,
                "prototype_bonus_scale": 18,
                "prototype_floor": 0.42,
                "prototypes": {
                    "entertainment_conflict": ["全网差评 动画 争议 角色 口碑 翻车 影视 作品", "演员 求职 档期很空 影视寒冬 行业现状 平台"],
                    "analysis_question": ["为什么 如何 真相 原因 折射 背后 现状 启示"],
                    "emotion_conflict": ["争议 站队 情绪 破防 愤怒 心疼 群嘲 对线"],
                },
            },
        },
    }
    loaded: dict[str, Any] | None = None
    if config_json.exists():
        try:
            parsed = json.loads(config_json.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                loaded = parsed
        except Exception:
            loaded = None
    elif config_yaml.exists():
        try:
            raw = config_yaml.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                loaded = parsed
        except Exception:
            loaded = None
    if loaded is None:
        return default_config
    merged = dict(default_config)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


SCORING_CONFIG = load_scoring_config()
ENV_SEMANTIC_BACKEND = str(os.environ.get("OPENCLAW_SEMANTIC_BACKEND", "") or "").strip().lower()
ENV_SEMANTIC_EMBEDDING_ENABLED = str(os.environ.get("OPENCLAW_SEMANTIC_EMBEDDING_ENABLED", "") or "").strip().lower()
ENV_SEMANTIC_EMBEDDING_MODEL = str(os.environ.get("OPENCLAW_SEMANTIC_EMBEDDING_MODEL", "") or "").strip()
ENV_SEMANTIC_LLM_ENABLED = str(os.environ.get("OPENCLAW_SEMANTIC_LLM_ENABLED", "") or "").strip().lower()
ENV_SEMANTIC_LLM_MODEL = str(os.environ.get("OPENCLAW_SEMANTIC_LLM_MODEL", "") or "").strip()
ANCHOR_CONFIG = SCORING_CONFIG.get("anchor", {})
CONFLICT_CONFIG = SCORING_CONFIG.get("conflict_signals", {})
ANALYSIS_QUESTION_TERMS = list(SCORING_CONFIG.get("analysis_question_terms", []))
POOL_THRESHOLDS = SCORING_CONFIG.get("pool_thresholds", {"S": 85, "A": 70, "B": 55})
MAINLINE_GATES = SCORING_CONFIG.get("mainline", {"anchor": 12, "conflict": 10, "analysis": 8})
SEMANTIC_SCORING_CONFIG = SCORING_CONFIG.get("semantic_scoring", {})
SEMANTIC_BACKEND = ENV_SEMANTIC_BACKEND or str(SEMANTIC_SCORING_CONFIG.get("backend", "rules") or "rules").lower()
SEMANTIC_RULES_CONFIG = SEMANTIC_SCORING_CONFIG.get("rules", {}) if isinstance(SEMANTIC_SCORING_CONFIG.get("rules", {}), dict) else {}
SEMANTIC_LLM_CONFIG = SEMANTIC_SCORING_CONFIG.get("llm", {}) if isinstance(SEMANTIC_SCORING_CONFIG.get("llm", {}), dict) else {}
SEMANTIC_EMBEDDING_CONFIG = SEMANTIC_SCORING_CONFIG.get("embedding", {}) if isinstance(SEMANTIC_SCORING_CONFIG.get("embedding", {}), dict) else {}
if ENV_SEMANTIC_LLM_ENABLED:
    SEMANTIC_LLM_CONFIG = {
        **SEMANTIC_LLM_CONFIG,
        "enabled": ENV_SEMANTIC_LLM_ENABLED in {"1", "true", "yes", "on"},
    }
if ENV_SEMANTIC_LLM_MODEL:
    SEMANTIC_LLM_CONFIG = {
        **SEMANTIC_LLM_CONFIG,
        "model": ENV_SEMANTIC_LLM_MODEL,
    }
if ENV_SEMANTIC_EMBEDDING_ENABLED:
    SEMANTIC_EMBEDDING_CONFIG = {
        **SEMANTIC_EMBEDDING_CONFIG,
        "enabled": ENV_SEMANTIC_EMBEDDING_ENABLED in {"1", "true", "yes", "on"},
    }
if ENV_SEMANTIC_EMBEDDING_MODEL:
    SEMANTIC_EMBEDDING_CONFIG = {
        **SEMANTIC_EMBEDDING_CONFIG,
        "model": ENV_SEMANTIC_EMBEDDING_MODEL,
    }

SEMANTIC_EMBEDDING_CACHE_DIR = ROOT / "tmp" / "semantic-embedding-cache"
SEMANTIC_EMBEDDING_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_semantic_backend_name() -> str:
    backend = SEMANTIC_BACKEND
    if backend == "embedding" and not bool(SEMANTIC_EMBEDDING_CONFIG.get("enabled", False)):
        return "rules"
    if backend == "llm" and not bool(SEMANTIC_LLM_CONFIG.get("enabled", False)):
        return "rules"
    if backend in {"rules", "llm", "embedding"}:
        return backend
    return "rules"


def _semantic_backend_stub(name: str, row: dict[str, Any]) -> dict[str, int]:
    return {
        "backend": 0,
        "anchor": article_semantic_anchor_floor(row),
        "conflict": 0,
        "analysis": 0,
        "emotion": 0,
        "reverse": 0,
        "industry_reversal": 0,
        "backend_unavailable": 1,
        "backend_name": 0,
        "backend_label": name,
    }


def _semantic_backend_ruleish_scores(row: dict[str, Any]) -> dict[str, int]:
    text = semantic_normalize_text(article_text(row))
    title = compact_text(row.get("title") or "", limit=200)
    semantic = {
        "backend": 0,
        "anchor": article_semantic_anchor_floor(row),
        "conflict": 0,
        "analysis": 0,
        "emotion": 0,
        "reverse": 0,
        "industry_reversal": 0,
        "backend_name": 0,
        "backend_label": "rules",
        "backend_unavailable": 0,
    }
    if any(term in text for term in CONFLICT_CONFIG.get("strong", [])):
        semantic["conflict"] = 16
    elif any(term in text for term in CONFLICT_CONFIG.get("mid", [])):
        semantic["conflict"] = 11
    elif any(term in text for term in CONFLICT_CONFIG.get("reverse", [])):
        semantic["reverse"] = 8
        semantic["conflict"] = 8
    elif any(term in text for term in CONFLICT_CONFIG.get("industry_conflict", [])):
        semantic["industry_reversal"] = 10
        semantic["conflict"] = 10

    if any(term in text for term in ANALYSIS_QUESTION_TERMS) or title.endswith("？") or title.endswith("?"):
        semantic["analysis"] = 10
    elif article_is_industry_source(row) or article_is_anchor_bound_industry_topic(row):
        semantic["analysis"] = 10

    if any(term in text for term in ARTICLE_SCORE_KEYWORDS["emotion"]):
        semantic["emotion"] = 9
    elif any(term in text for term in ["心疼", "愤怒", "破防", "唏嘘", "争议", "站队"]):
        semantic["emotion"] = 6

    if article_has_entertainment_anchor(row):
        semantic["anchor"] = max(semantic["anchor"], 12)
    return semantic


def _llm_semantic_signal_scores(row: dict[str, Any]) -> dict[str, int]:
    if not bool(SEMANTIC_LLM_CONFIG.get("enabled", False)):
        return _semantic_backend_stub("llm-disabled", row)
    model_name = str(SEMANTIC_LLM_CONFIG.get("model", "gpt-5.4-mini") or "gpt-5.4-mini")
    prompt = (
        "你是文章语义评分器，只输出 JSON，不要解释。\n"
        "字段：anchor, conflict, analysis, emotion, reverse, industry_reversal。\n"
        "每项取 0-20 的整数。\n"
        "anchor=作品/人物/行业锚点强度，conflict=冲突/争议/翻车，analysis=可分析性，emotion=情绪强度，reverse=反差/逆转，industry_reversal=行业反转。\n"
        f"标题：{compact_text(row.get('title') or '', limit=180)}\n"
        f"正文：{compact_text(article_text(row), limit=1200)}\n"
        "只输出 JSON。"
    )
    cache_dir = ROOT / "tmp" / "semantic-llm-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(f"{model_name}\n{prompt}".encode('utf-8')).hexdigest()
    cache_path = cache_dir / f"{cache_key}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return {"backend": 1, "backend_name": 0, "backend_label": "llm", "backend_unavailable": 0, **{k: int(cached.get(k, 0) or 0) for k in ["anchor", "conflict", "analysis", "emotion", "reverse", "industry_reversal"]}}
        except Exception:
            pass
    try:
        client = openai.OpenAI()
        response = client.responses.create(model=model_name, input=prompt, temperature=0)
        content = getattr(response, "output_text", None) or ""
        if not content:
            content = json.dumps(getattr(response, "output", {}), ensure_ascii=False)
        parsed = json.loads(content) if content.strip().startswith("{") else {}
        scores = {
            "anchor": int(parsed.get("anchor", 0) or 0),
            "conflict": int(parsed.get("conflict", 0) or 0),
            "analysis": int(parsed.get("analysis", 0) or 0),
            "emotion": int(parsed.get("emotion", 0) or 0),
            "reverse": int(parsed.get("reverse", 0) or 0),
            "industry_reversal": int(parsed.get("industry_reversal", 0) or 0),
        }
        cache_path.write_text(json.dumps(scores, ensure_ascii=False), encoding="utf-8")
        return {"backend": 1, "backend_name": 0, "backend_label": "llm", "backend_unavailable": 0, **scores}
    except Exception as exc:
        try:
            cache_path.write_text(json.dumps({"error": compact_text(str(exc), limit=240)}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        fallback = _semantic_backend_ruleish_scores(row)
        fallback["backend_unavailable"] = 1
        fallback["backend_label"] = "llm-fallback-rules"
        return fallback


def _semantic_tokenize(text: str) -> list[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", semantic_normalize_text(text))
    tokens = [token for token in normalized.split() if token]
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if re.search(r"[\u4e00-\u9fff]", token):
            expanded.extend(token[index:index + 2] for index in range(max(0, len(token) - 1)))
    return expanded or tokens


def _semantic_token_vector(token: str, size: int) -> np.ndarray:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    values = []
    for index in range(size):
        byte = digest[index % len(digest)]
        values.append((byte / 255.0) * 2 - 1)
    vector = np.array(values, dtype=float)
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0 else vector / norm


def _semantic_embed_text(text: str, size: int) -> np.ndarray:
    tokens = _semantic_tokenize(text)
    if not tokens:
        return np.zeros(size, dtype=float)
    vectors = [_semantic_token_vector(token, size) for token in tokens]
    merged = np.mean(vectors, axis=0)
    norm = float(np.linalg.norm(merged))
    return merged if norm == 0 else merged / norm


def _semantic_embedding_cache_key(text: str, model: str) -> Path:
    digest = hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()
    return SEMANTIC_EMBEDDING_CACHE_DIR / f"{digest}.json"


def _semantic_openai_embed_text(text: str, model: str) -> list[float]:
    cache_path = _semantic_embedding_cache_key(text, model)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                return [float(value) for value in cached]
        except Exception:
            pass
    client = openai.OpenAI()
    try:
        response = client.embeddings.create(model=model, input=text)
        vector = list(response.data[0].embedding)
    except Exception as exc:
        cache_path.write_text(json.dumps({"error": compact_text(str(exc), limit=240)}, ensure_ascii=False), encoding="utf-8")
        raise
    try:
        cache_path.write_text(json.dumps(vector, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return vector


def _semantic_vector_from_list(values: list[float]) -> np.ndarray:
    if not values:
        return np.zeros(1, dtype=float)
    vector = np.array(values, dtype=float)
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0 else vector / norm


def _semantic_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def _embedding_semantic_signal_scores(row: dict[str, Any]) -> dict[str, int]:
    if not bool(SEMANTIC_EMBEDDING_CONFIG.get("enabled", False)):
        return _semantic_backend_stub("embedding-disabled", row)
    provider = str(SEMANTIC_EMBEDDING_CONFIG.get("provider", "openai") or "openai").lower()
    vector_size = int(SEMANTIC_EMBEDDING_CONFIG.get("vector_size", 24) or 24)
    floor = float(SEMANTIC_EMBEDDING_CONFIG.get("prototype_floor", 0.42) or 0.42)
    scale = int(SEMANTIC_EMBEDDING_CONFIG.get("prototype_bonus_scale", 18) or 18)
    prototypes = SEMANTIC_EMBEDDING_CONFIG.get("prototypes", {}) if isinstance(SEMANTIC_EMBEDDING_CONFIG.get("prototypes", {}), dict) else {}
    text = semantic_normalize_text(article_text(row))
    model_name = str(SEMANTIC_EMBEDDING_CONFIG.get("model", "text-embedding-3-small") or "text-embedding-3-small")
    try:
        if provider == "openai":
            text_vector = _semantic_vector_from_list(_semantic_openai_embed_text(text, model_name))
            prototype_vectors = {
                name: [_semantic_vector_from_list(_semantic_openai_embed_text(str(sample), model_name)) for sample in samples]
                for name, samples in prototypes.items()
                if isinstance(samples, list) and samples
            }
        else:
            text_vector = _semantic_embed_text(text, vector_size)
            prototype_vectors = {
                name: [_semantic_embed_text(str(sample), vector_size) for sample in samples]
                for name, samples in prototypes.items()
                if isinstance(samples, list) and samples
            }
    except Exception:
        fallback = _semantic_backend_ruleish_scores(row)
        fallback["backend_unavailable"] = 1
        fallback["backend_label"] = "embedding-fallback-rules"
        return fallback
    semantic = {
        "backend": 1,
        "anchor": article_semantic_anchor_floor(row),
        "conflict": 0,
        "analysis": 0,
        "emotion": 0,
        "reverse": 0,
        "industry_reversal": 0,
        "backend_name": 0,
        "backend_label": "embedding",
        "backend_unavailable": 0,
    }
    prototype_scores: dict[str, float] = {}
    for name, vectors in prototype_vectors.items():
        similarities = [_semantic_similarity(text_vector, vector) for vector in vectors]
        prototype_scores[name] = max(similarities) if similarities else 0.0
    conflict_like = prototype_scores.get("entertainment_conflict", 0.0)
    analysis_like = prototype_scores.get("analysis_question", 0.0)
    emotion_like = prototype_scores.get("emotion_conflict", 0.0)
    if conflict_like >= floor:
        semantic["conflict"] = max(semantic["conflict"], max(6, min(16, int(math.ceil(conflict_like * scale)))))
    if analysis_like >= floor:
        semantic["analysis"] = max(semantic["analysis"], max(6, min(12, int(math.ceil(analysis_like * scale)))))
    if emotion_like >= floor:
        semantic["emotion"] = max(semantic["emotion"], max(5, min(10, int(math.ceil(emotion_like * scale)))))
    if article_has_entertainment_anchor(row):
        semantic["anchor"] = max(semantic["anchor"], 12)
    if article_is_anchor_bound_industry_topic(row) and conflict_like >= floor:
        semantic["industry_reversal"] = max(semantic["industry_reversal"], 8)
    return semantic


SEMANTIC_BACKEND_HANDLERS: dict[str, Any] = {
    "rules": _semantic_backend_ruleish_scores,
    "llm": _llm_semantic_signal_scores,
    "embedding": _embedding_semantic_signal_scores,
}


@dataclass
class StepResult:
    name: str
    status: str
    output: str | None = None
    detail: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class SourceDecision:
    name: str
    category: str
    status: str
    reason: str
    outputs: list[str]


def run_json_command(name: str, command: list[str], cwd: Path | None = None) -> StepResult:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return StepResult(name=name, status="ERROR", error=str(exc))

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    detail = None
    if stdout:
        last_line = stdout.splitlines()[-1]
        try:
            detail = json.loads(last_line)
        except json.JSONDecodeError:
            detail = {"raw_stdout": stdout}

    if proc.returncode == 0:
        return StepResult(name=name, status="OK", detail=detail)

    return StepResult(
        name=name,
        status="ERROR",
        detail=detail,
        error=stderr or stdout or f"exit={proc.returncode}",
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def copy_latest(target: Path, link_path: Path) -> None:
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")


def normalize_topic_key(text: str) -> str:
    normalized = re.sub(r"[\W_]+", "", (text or "").lower())
    return normalized[:80]


def row_topic_key(row: dict[str, Any]) -> str:
    title = compact_text(row.get("title") or "", limit=120)
    url = str(row.get("url") or "")
    platform_item_id = str(row.get("platform_item_id") or "")
    if platform_item_id:
        return normalize_topic_key(platform_item_id)
    if title:
        return normalize_topic_key(title)
    return normalize_topic_key(url)


def dedupe_rows(rows: list[dict[str, Any]], score_fn) -> tuple[list[dict[str, Any]], int]:
    kept: dict[str, dict[str, Any]] = {}
    dropped = 0
    for row in rows:
        key = row_topic_key(row)
        if not key:
            key = f"row-{len(kept) + dropped}"
        existing = kept.get(key)
        if existing is None:
            kept[key] = row
            continue
        current_score = score_fn(row)
        existing_score = score_fn(existing)
        if current_score > existing_score:
            kept[key] = row
        dropped += 1
    return list(kept.values()), dropped


def recent_topic_hits(days: int = 3, current_date: str | None = None) -> set[str]:
    hits: set[str] = set()
    base = HANDOVER / "01-DAILY-RUNS"
    if not base.exists():
        return hits
    dated_dirs = sorted(
        [path for path in base.iterdir() if path.is_dir() and path.name != current_date],
        reverse=True,
    )[:days]
    for day_dir in dated_dirs:
        candidate_run_dirs = [day_dir / "media-intel-aios"]
        candidate_run_dirs.extend(path / "media-intel-aios" for path in day_dir.iterdir() if path.is_dir())
        seen_run_dirs: set[Path] = set()
        for run_dir in candidate_run_dirs:
            if run_dir in seen_run_dirs or not run_dir.exists():
                continue
            seen_run_dirs.add(run_dir)
            for sub in ("article-leads", "story-leads", "media-leads"):
                subdir = run_dir / sub
                if not subdir.exists():
                    continue
                for jsonl in subdir.glob("*.jsonl"):
                    for row in load_jsonl(jsonl):
                        key = row_topic_key(row)
                        if key:
                            hits.add(key)
    return hits


def dedupe_summary_text(dropped: dict[str, int], cross_day_hits: dict[str, int]) -> str:
    parts = [
        f"当天去重：article {dropped.get('article', 0)}｜story {dropped.get('story', 0)}｜media {dropped.get('media', 0)}",
        f"跨天命中提示：article {cross_day_hits.get('article', 0)}｜story {cross_day_hits.get('story', 0)}｜media {cross_day_hits.get('media', 0)}",
    ]
    return "；".join(parts)


def apply_cross_day_policy(
    rows: list[dict[str, Any]],
    recent_hits: set[str],
    *,
    mode: str,
    penalty: int,
    score_getter,
) -> tuple[list[dict[str, Any]], int, int]:
    kept_rows: list[dict[str, Any]] = []
    hit_count = 0
    blocked_count = 0

    for row in rows:
        key = row_topic_key(row)
        if not key or key not in recent_hits:
            kept_rows.append(row)
            continue

        hit_count += 1
        row["cross_day_duplicate_hit"] = True
        row["cross_day_policy_mode"] = mode

        if mode == "block":
            row["cross_day_blocked"] = True
            row["cross_day_penalty"] = score_getter(row)
            blocked_count += 1
            continue

        effective_penalty = max(0, penalty)
        row["cross_day_penalty"] = effective_penalty
        row["cross_day_adjusted_score"] = max(0, score_getter(row) - effective_penalty)
        kept_rows.append(row)

    return kept_rows, hit_count, blocked_count


ARTICLE_NOISE_TITLE_TERMS = (
    "公告",
    "签到",
    "导航",
    "删帖",
    "申精",
    "专楼",
    "交友小组",
    "组规",
    "操作记录",
    "宣传",
    "平价茅台",
)


def article_row_is_noise(row: dict[str, Any]) -> bool:
    title = compact_text(row.get("title") or "", limit=120)
    content = compact_text(row.get("content") or "", limit=200)
    content_type = str(row.get("content_type") or "").lower()
    if content_type == "story" and str(row.get("source") or "") == "douban_group":
        return True
    return any(term in title or term in content for term in ARTICLE_NOISE_TITLE_TERMS)


def enrich_article_row_for_scoring(row: dict[str, Any], date: str) -> dict[str, Any]:
    enriched = dict(row)
    zhihu_index = load_local_zhihu_body_index()
    zhihu_backfill_index = load_local_zhihu_backfill_index(date)
    enriched = enrich_today_hook_row_with_local_body(enriched, zhihu_index, zhihu_backfill_index)
    local_excerpt = compact_text(
        enriched.get("local_body_excerpt")
        or enriched.get("content_text")
        or enriched.get("desc")
        or enriched.get("summary")
        or enriched.get("content")
        or enriched.get("title")
        or "",
        limit=220,
    )
    if local_excerpt:
        enriched["content"] = merged_text(enriched.get("content"), local_excerpt)
        enriched["summary"] = merged_text(enriched.get("summary"), local_excerpt)
    enriched.setdefault("summary", compact_text(enriched.get("content") or enriched.get("title") or "", limit=140))
    enriched.setdefault("raw_score", article_daily_score(enriched))
    enriched.setdefault("production_score", article_production_score(enriched, date))
    return enriched


def build_retry_plan(
    article_rows: list[dict[str, Any]],
    story_rows: list[dict[str, Any]],
    media_rows: list[dict[str, Any]],
    date: str,
    lane: str = "all",
) -> tuple[bool, list[str], str]:
    eligible_article_rows = [row for row in article_rows if article_is_whitelist_eligible(row, date)]
    article_has_main = any(article_daily_score(row) >= 75 for row in eligible_article_rows)
    article_has_backup = any(article_daily_score(row) >= 70 for row in eligible_article_rows)
    article_high_blocked = [
        row for row in article_rows
        if not article_is_discovery_source(row)
        and article_daily_score(row) >= 70
        and not article_is_whitelist_eligible(row, date)
    ]
    convertible_story_rows = [row for row in story_rows if story_is_convertible_mother(row)]
    script_ready_story_rows = [row for row in convertible_story_rows if story_script_gap_reason(row) == "可压剧本，待人工拍板"]
    story_has_convertible = bool(convertible_story_rows)
    story_has_a_level = any(story_editorial_score(row) >= 85 for row in convertible_story_rows)
    story_has_script_ready = bool(script_ready_story_rows)
    media_has_strong_narrative = any(media_editorial_score(row) >= 75 for row in media_rows)

    retry_targets: list[str] = []
    reasons: list[str] = []
    if lane != "video" and not article_has_main and not article_has_backup:
        retry_targets.extend(["豆瓣小组", "小红书", "知乎", "微信公众号"])
        if article_high_blocked:
            reasons.append("文章组高分候选缺今天写它的理由或缺二跳正文")
        else:
            reasons.append("文章组无70+影视候选")
    if lane == "article":
        pass
    elif not story_has_convertible and not media_has_strong_narrative:
        retry_targets.extend(["B站", "抖音", "小红书故事向", "豆瓣小组"])
        reasons.append("漫剧组无可用真实叙事母本")
    elif story_has_convertible and not story_has_a_level:
        retry_targets.extend(["知乎", "抖音", "豆瓣小组"])
        reasons.append("漫剧组缺 A 级母本")
    elif story_has_a_level and not story_has_script_ready:
        retry_targets.extend(["知乎", "微信公众号", "豆瓣小组", "抖音"])
        reasons.append("漫剧组 A 级母本缺故事/作品锚点或结构补强")

    deduped_targets = list(dict.fromkeys(retry_targets))
    return bool(deduped_targets), deduped_targets, "；".join(reasons) if reasons else "无需重爬"


RETRY_TARGET_FLAGS = {
    "豆瓣小组": "douban_group",
    "小红书": "xhs",
    "小红书故事向": "xhs",
    "知乎": "zhihu",
    "微信公众号": "wechat",
    "B站": "bilibili",
    "抖音": "douyin",
}


def _retry_query_text(row: dict[str, Any]) -> str:
    return compact_text(
        merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("keyword")),
        limit=48,
    )


def build_evidence_backfill_tasks(article_rows: list[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for row in sort_article_rows(article_rows):
        profile = candidate_profile(row, "article")
        if profile.get("write_readiness") != "needs_evidence_backfill":
            continue
        query = _retry_query_text(row)
        if not query:
            continue
        tasks.append({
            "candidate_title": compact_text(row.get("title") or row.get("candidate_title") or "无标题", limit=100),
            "source": row.get("source_name") or row.get("source") or "未知来源",
            "url": row.get("url") or row.get("source_url") or "",
            "query": query,
            "write_readiness": profile.get("write_readiness"),
            "topic_score": profile.get("topic_score", 0),
            "evidence_score": profile.get("evidence_score", 0),
            "reason": profile.get("reason") or row.get("article_route_reason") or "补二跳正文、评论区高赞观点或可核验数据",
            "targets": ["douban_group", "xhs", "zhihu", "wechat"],
            "next_action": "补二跳正文、评论区高赞观点、平台热度变化后再进人工二审",
        })
    return tasks[:5]


def build_retry_request(
    article_rows: list[dict[str, Any]],
    story_rows: list[dict[str, Any]],
    media_rows: list[dict[str, Any]],
    date: str,
    lane: str = "all",
) -> dict[str, Any]:
    retry_required, targets, reason = build_retry_plan(article_rows, story_rows, media_rows, date, lane=lane)
    runnable_flags = list(dict.fromkeys(
        flag
        for target in targets
        for flag in [RETRY_TARGET_FLAGS.get(target)]
        if flag
    ))
    evidence_backfill_tasks = build_evidence_backfill_tasks(article_rows, date)
    if evidence_backfill_tasks:
        for flag in evidence_backfill_tasks[0]["targets"]:
            if flag not in runnable_flags:
                runnable_flags.append(flag)
    query_candidates = [_retry_query_text(row) for row in sort_article_rows(article_rows)[:3]]
    query_candidates.extend(task["query"] for task in evidence_backfill_tasks)
    queries = [query for query in dict.fromkeys(query_candidates) if query]
    return {
        "status": "retry_request" if retry_required or evidence_backfill_tasks else "ok",
        "retry_required": retry_required or bool(evidence_backfill_tasks),
        "targets": targets,
        "runnable_flags": runnable_flags,
        "queries": queries,
        "reason": reason,
        "evidence_backfill_tasks": evidence_backfill_tasks,
    }


def run_article_retry_loop(
    article_rows: list[dict[str, Any]],
    story_rows: list[dict[str, Any]],
    media_rows: list[dict[str, Any]],
    date: str,
    refetcher,
    lane: str = "all",
) -> dict[str, Any]:
    initial_retry_request = build_retry_request(article_rows, story_rows, media_rows, date, lane=lane)
    if not initial_retry_request["retry_required"]:
        return {
            "status": "ok",
            "initial_retry_request": initial_retry_request,
            "retry_request": initial_retry_request,
            "refetched_count": 0,
            "article_rows": article_rows,
        }

    refetched_rows = list(refetcher(initial_retry_request) or [])
    combined_rows = article_rows + refetched_rows
    scoring_rows = [enrich_article_row_for_scoring(dict(row), date) for row in combined_rows]
    retry_request = build_retry_request(scoring_rows, story_rows, media_rows, date, lane=lane)
    return {
        "status": "retry_request" if retry_request["retry_required"] else "ok",
        "initial_retry_request": initial_retry_request,
        "retry_request": retry_request,
        "refetched_count": len(refetched_rows),
        "article_rows": combined_rows,
    }


def summarize_article_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- 状态：今日未产出文章候选。"

    ranked_rows = sort_article_rows(rows)
    editorial_rows = [row for row in ranked_rows if not article_is_discovery_source(row)]
    discovery_rows = [row for row in ranked_rows if article_is_discovery_source(row)]
    industry_rows = [row for row in editorial_rows if article_is_industry_source(row)]
    general_rows = [row for row in editorial_rows if not article_is_industry_source(row)]
    lines = [f"- 候选总数：{len(rows)}｜正文候选：{len(editorial_rows)}｜行业正文：{len(industry_rows)}｜热点发现：{len(discovery_rows)}"]
    for index, row in enumerate(industry_rows[:5], start=1):
        title = row.get("title") or "无标题"
        source = row.get("source_name") or row.get("source") or "未知来源"
        meta = row.get("publish_time") or row.get("rank_date") or row.get("channel") or "信息缺失"
        score = article_daily_score(row)
        bucket = article_score_bucket_name(score)
        lines.append(f"- 行业正文 {index}. [{source}] {title}｜{meta}｜{bucket} {score}分")
    for index, row in enumerate(general_rows[:5], start=1):
        title = row.get("title") or "无标题"
        source = row.get("source_name") or row.get("source") or "未知来源"
        meta = row.get("publish_time") or row.get("rank_date") or row.get("channel") or "信息缺失"
        score = article_daily_score(row)
        bucket = article_score_bucket_name(score)
        lines.append(f"- 正文候选 {index}. [{source}] {title}｜{meta}｜{bucket} {score}分")
    if discovery_rows:
        lines.append("- 热点发现层：")
        for index, row in enumerate(discovery_rows[:5], start=1):
            title = row.get("title") or "无标题"
            source = row.get("source_name") or row.get("source") or "未知来源"
            meta = row.get("publish_time") or row.get("rank_date") or row.get("channel") or "信息缺失"
            score = article_daily_score(row)
            lines.append(f"  - {index}. [{source}] {title}｜{meta}｜发现分 {score}")
    return "\n".join(lines)


def article_source_priority(row: dict[str, Any]) -> int:
    source = str(row.get("source_name") or row.get("source") or "").lower()
    source_type = str(row.get("source_type") or row.get("content_type") or "").lower()
    url_type = str(row.get("url_type") or "").lower()
    if source in {"zhihu", "知乎", "netease_renjian", "网易人间", "reddit", "xhs", "xhs_note", "小红书", "douban_group", "豆瓣小组", "tieba", "贴吧"}:
        return 0
    if source in {"weibo", "微博", "weibo_media"} and source_type in {"platform_post", "post_detail", "article", "long_text"}:
        return 1
    if source in {"douban", "豆瓣", "wechat", "微信公众号", "vocus", "bilibili"}:
        return 2
    if source in {"guduo", "骨朵热度指数", "maoyan", "猫眼热榜", "tencent", "腾讯视频", "dumou", "xiniu"}:
        return 8
    if source in {"hotboard", "tophub_today", "hotlist_web"}:
        return 12
    if source in ARTICLE_DISCOVERY_SOURCES or source in {"weibo_hotspot", "微博热点", "微博热搜"} or ((source in {"weibo", "微博"}) and (source_type in {"topic", "search", "hot_search"} or url_type in {"topic", "search"})) or "骨朵" in source or "猫眼" in source:
        return 16
    return 20


def article_router_bucket(row: dict[str, Any]) -> str:
    source = str(row.get("source_name") or row.get("source") or "").lower()
    source_type = str(row.get("source_type") or row.get("content_type") or "").lower()
    url_type = str(row.get("url_type") or "").lower()
    if source in ARTICLE_INDUSTRY_ROUTER_SOURCES:
        return "industry"
    if source in {"weibo", "微博", "weibo_media"} and source_type in {"topic", "search", "hot_search"}:
        return "discovery"
    if source in {"weibo", "微博"} and url_type in {"topic", "search"}:
        return "discovery"
    if source in ARTICLE_DISCOVERY_ROUTER_SOURCES or "骨朵" in source or "猫眼" in source:
        return "discovery"
    if source in ARTICLE_HOTCOMMENT_ROUTER_SOURCES:
        return "hotcomment"
    return "general"


def article_router_weight(row: dict[str, Any]) -> int:
    source = str(row.get("source_name") or row.get("source") or "").lower()
    source_type = str(row.get("source_type") or row.get("content_type") or "").lower()
    bucket = article_router_bucket(row)
    if bucket == "industry":
        return 95
    if source in {"微信公众号", "wechat", "weixin"}:
        return 100
    if source in {"weibo", "微博", "weibo_media"} and source_type in {"platform_post", "post_detail", "article", "long_text"}:
        return 90
    if source in {"知乎", "zhihu"}:
        return 85
    if source in {"maoyan", "猫眼热榜", "guduo", "骨朵热度指数"}:
        return 60
    if source in {"weibo_hotspot", "微博热点", "微博热搜"}:
        return 20
    if source == "tophub_today":
        return 10
    if source in {"hotboard", "hotlist_web"}:
        return 5
    if bucket == "hotcomment":
        return 80
    if bucket == "discovery":
        return 30
    return 70


def article_router_capabilities(row: dict[str, Any]) -> list[str]:
    bucket = article_router_bucket(row)
    source = str(row.get("source_name") or row.get("source") or "").lower()
    source_type = str(row.get("source_type") or row.get("content_type") or "").lower()
    capabilities: list[str] = []
    if bucket == "hotcomment":
        capabilities = ["emotion", "hot_opinion", "title_generation", "wechat_article"]
    elif bucket == "industry":
        capabilities = ["industry_analysis", "trend", "data", "wechat_article"]
    elif bucket == "discovery":
        capabilities = ["event_discovery"]
    else:
        capabilities = ["article", "analysis"]
    if source in {"weibo", "微博", "weibo_media"} and source_type in {"platform_post", "post_detail", "article", "long_text"}:
        for capability in ["emotion", "hot_opinion", "title_generation"]:
            if capability not in capabilities:
                capabilities.insert(0, capability)
    return capabilities


def article_is_industry_source(row: dict[str, Any]) -> bool:
    source = str(row.get("source_name") or row.get("source") or "").lower()
    return source in ARTICLE_INDUSTRY_SOURCES


ARTICLE_ENTERTAINMENT_ANCHOR_TERMS = [
    "剧", "电影", "综艺", "演员", "角色", "导演", "编剧", "平台", "短剧", "ip", "作品", "片单", "票房", "豆瓣",
    "番位", "开分", "口碑", "热度", "收视", "爱奇艺", "腾讯视频", "优酷", "芒果", "剧场版", "国剧", "影业",
]
ARTICLE_RESONANCE_CORE_TERMS = [
    "争议", "反转", "人性", "共鸣", "情绪", "现实", "映射", "悬疑", "揭秘", "真相", "社会", "命运", "选择", "冲突",
    "争吵", "愤怒", "心疼", "惋惜", "破防", "唏嘘", "对错", "偏见", "代价", "底层", "家庭", "成长", "创伤", "尊严",
    "差评", "全网差评", "口碑翻车", "翻车", "不买账", "骂", "群嘲", "对线", "质疑", "回应", "维权",
    "为什么", "为何", "背后", "折射", "现状", "机制", "困境", "套路", "抛弃", "问题到底出在哪",
]
ARTICLE_RESONANCE_PRIORITY_TERMS = [
    "戒网瘾", "非法拘禁", "马拉松猝死", "猝死", "家暴", "离婚", "出轨", "原生家庭", "校园", "霸凌", "失业", "求职", "债务",
    "高考", "遗书", "认亲", "失踪", "彩礼", "婚姻", "亲子", "职场", "贫富", "救人", "意外", "争议", "反转",
    "面试", "应届生", "焦虑", "依赖AI", "体面", "整治", "纳税", "行业乱象", "车主", "换回燃油车", "后悔", "选择成本", "范小勤", "围观",
]
ARTICLE_SOFT_TOPIC_TERMS = [
    "婚姻感悟", "女性成长", "自我疗愈", "清醒", "认知提升", "婚内单身", "佛系", "通透", "一句话点醒", "文案", "治愈", "生活美学",
]
ARTICLE_RELATIONSHIP_TERMS = ["婚姻", "离婚", "夫妻", "前任", "感情", "恋爱", "结婚", "婆媳", "出轨"]
ARTICLE_BAD_PAGE_TERMS = ["加载中", "{{=", "{{ ", "模板", "暂无正文", "请稍后"]
ARTICLE_HARD_EXCLUDE_TERMS = [
    "行业新闻", "片单", "平台片单", "演员动态", "官宣", "开机", "杀青", "票房播报", "收视率", "公司动态", "融资", "招商",
    "财报", "发布会", "上新", "排播", "待播", "项目招商", "公司战略", "平台战略",
    "票房", "片单", "剧集榜", "热度榜", "榜单", "排播表",
    "资本", "腾挪", "市值", "上市", "融资", "并购", "收购", "财报", "营收", "利润", "美元", "纳指", "SpaceX",
]
ARTICLE_RECOMMENDED_WRITE_TYPES = {
    "人物命运": ["命运", "选择", "代价", "成长", "悲剧", "翻身"],
    "反派解析": ["反派", "黑化", "对立", "恶", "算计"],
    "伏笔细节": ["伏笔", "细节", "暗线", "铺垫", "回收"],
    "人性社会映射": ["人性", "现实", "社会", "家庭", "偏见", "代价"],
    "悬疑解读": ["悬疑", "真相", "揭秘", "反转", "秘密"],
    "反常识观点": ["反常识", "意外", "没想到", "误判", "颠覆"],
    "被低估角色": ["低估", "配角", "角色", "边角", "忽视"],
    "高共鸣话题": ["共鸣", "情绪", "争议", "争吵", "心疼", "破防"],
}
ARTICLE_RESONANCE_DIMENSIONS = {
    "人性": ["人性", "尊严", "代价", "选择", "家庭", "亲子", "婚姻", "成长", "原生家庭", "霸凌", "家暴", "非法拘禁"],
    "争议": ["争议", "对错", "应不应该", "该不该", "质疑", "回应", "维权", "差评", "全网差评", "群嘲"],
    "现实映射": ["现实", "折射", "现状", "社会", "机制", "困境", "职场", "教育", "行业", "父母", "成年子女"],
    "悬念": ["真相", "为什么", "为何", "背后", "到底", "揭秘", "后背发凉", "谁的锅", "原来"],
}
ARTICLE_SCORE_KEYWORDS = {
    "conflict": ["翻车", "逆袭", "打脸", "争议", "人设崩塌", "口碑分裂", "观众不买账", "内斗", "塌房", "反转", "骂", "撕"],
    "conflict_strong": ["全网差评", "口碑翻车", "塌房", "扑街", "烂尾", "魔改", "群嘲", "抵制", "对线", "查税", "被封", "官宣离婚"],
    "conflict_mid": ["差评", "争议", "删减", "注水", "不买账", "质疑", "回应", "道歉", "维权", "塌", "崩"],
    "conflict_reverse": ["逆袭", "压番", "爆冷", "反转", "黑马", "意外"],
    "industry_conflict": ["当众求职", "档期很空", "看看我", "无戏可拍", "影视寒冬", "行业现状", "没人找", "接不到戏", "降咖", "待业", "失业", "没活", "寒冬", "塌方式失业"],
    "analysis": ["为什么", "为何", "凭什么", "如何", "怎么", "折射", "背后", "真相", "原因", "启示", "现状", "隐喻", "行业", "机制", "变化", "复盘", "解读", "逻辑"],
    "emotion": ["心疼", "愤怒", "解气", "惋惜", "共鸣", "破防", "唏嘘", "炸了", "看哭"],
    "suspense": ["为什么", "到底", "真相", "没人想到", "如何", "谁的锅", "竟然", "原来"],
    "relationship": ["夫妻", "前任", "父亲", "母亲", "兄弟", "姐妹", "师徒", "演员", "角色", "观众", "主创"],
    "vent": ["骂", "喷", "失望", "受不了", "活该", "离谱", "崩了", "塌了", "看不下去"],
}

ARTICLE_ANALYSIS_QUESTION_TERMS = ["为什么", "为何", "凭什么", "如何", "怎么", "折射", "背后", "真相", "原因", "启示", "现状"]

SEMANTIC_ALIAS_GROUPS = {
    "扑街": ["扑街", "糊了", "糊穿了地心", "凉了", "凉透了", "扑了", "暴死"],
    "翻车": ["翻车", "崩了", "塌了", "拉胯", "口碑崩了", "崩盘"],
    "查无此人": ["查无此人", "无人问津", "没人提了", "过气了"],
    "争议": ["争议", "吵翻了", "吵成两派", "吵麻了", "撕起来了"],
    "全网差评": ["全网差评", "被骂惨了", "骂上热搜", "口碑炸了"],
    "影视寒冬": ["影视寒冬", "无戏可拍", "接不到戏", "档期很空", "没活了", "待业"],
}

SEMANTIC_ALIAS_LOOKUP = {
    alias.lower(): canonical
    for canonical, aliases in SEMANTIC_ALIAS_GROUPS.items()
    for alias in aliases
}

ARTICLE_TITLE_FORMULAS = {
    "反差落差": lambda title: f"{compact_text(title, limit=24)}，为什么越看越不对劲？",
    "疑问钩子": lambda title: f"{compact_text(title, limit=24)}，真正的问题到底出在哪？",
    "站队挑事": lambda title: f"{compact_text(title, limit=24)}，这次观众为什么吵成两派？",
    "情绪宣泄": lambda title: f"{compact_text(title, limit=24)}，谁还愿意继续买账？",
    "揭秘内幕": lambda title: f"{compact_text(title, limit=24)}背后，藏着什么没说透？",
}

ARTICLE_COMMENTARY_SIGNAL_TERMS = [
    "人物命运", "反派", "隐藏细节", "伏笔", "人性", "现实映射", "悬疑", "解读", "被低估", "反常识",
    "争议", "反转", "揭秘", "角色", "命运", "结局", "悲剧", "黑化", "成长", "宿命",
]
VIDEO_NOISE_TITLE_TERMS = ["频道入口", "作品1", "作品2", "作品3", "预告片", "VIP 全", "腾讯视频首页", "会员每周"]
VIDEO_STORY_SIGNAL_TERMS = [
    "婚礼", "悔婚", "欠债", "担保", "彩礼", "广播", "离家", "认亲", "失踪", "退婚", "高考", "毕业", "暗恋", "亲子", "家暴",
    "重男轻女", "继父", "继母", "借钱", "骗婚", "流产", "葬礼", "复仇", "当场翻脸", "全村围观", "反转", "真相", "故事", "逆袭",
]
VIDEO_SOFT_VIEW_TERMS = [
    "感悟", "清醒", "通透", "婚姻真相", "自我成长", "女性成长", "爱自己", "一句话点醒", "治愈", "认知提升", "文案", "句子", "生活方式", "情绪价值", "修行", "佛家",
]


def merged_text(*values: Any) -> str:
    return " ".join(compact_text(value or "", limit=400) for value in values if value).strip()


def semantic_normalize_text(text: str) -> str:
    normalized = compact_text(text or "", limit=2000).lower()
    for alias, canonical in sorted(SEMANTIC_ALIAS_LOOKUP.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in normalized:
            normalized = normalized.replace(alias, f" {canonical} ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def article_has_resonance_core(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("notes"), row.get("article_route_reason")).lower()
    if any(term.lower() in text for term in ARTICLE_RESONANCE_CORE_TERMS) or any(term in text for term in ARTICLE_RESONANCE_PRIORITY_TERMS):
        return True
    title = compact_text(row.get("title") or "", limit=200)
    if any(term in title for term in ["医疗行业再掀税务整治", "飞刀费", "公对公", "应届生", "面试", "范小勤", "新能源汽车车主", "换回了燃油车"]):
        return True
    return any(term in title for term in [
        "豆包味很浓的应届生", "依赖豆包AI作答", "应届生", "面试",
        "范小勤", "这幅字", "新能源汽车车主", "换回了燃油车",
    ]) or any(term in text for term in ["AI", "职场", "求职", "车主", "燃油车", "围观", "写字"])


def article_resonance_dimensions(row: dict[str, Any]) -> dict[str, bool]:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("notes"), row.get("article_route_reason"))
    return {name: any(term in text for term in terms) for name, terms in ARTICLE_RESONANCE_DIMENSIONS.items()}


def article_resonance_count(row: dict[str, Any]) -> int:
    dims = article_resonance_dimensions(row)
    return sum(1 for hit in dims.values() if hit)


def article_resonance_level(row: dict[str, Any]) -> str:
    count = article_resonance_count(row)
    if count >= 3:
        return "deep"
    if count >= 1:
        return "mid"
    return "light"


def article_recommended_write_type(row: dict[str, Any]) -> str:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("notes"), row.get("article_route_reason"))
    if any(term in text for term in ["差评", "全网差评", "口碑翻车", "争议", "骂", "群嘲"]):
        return "高共鸣话题"
    for label, terms in ARTICLE_RECOMMENDED_WRITE_TYPES.items():
        if any(term in text for term in terms):
            return label
    return "高共鸣话题"


def article_mapped_ip(row: dict[str, Any]) -> str:
    title = compact_text(row.get("title") or "", limit=120)
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("notes"), row.get("article_route_reason"))
    if any(term in text for term in ["AI 应届生", "豆包味", "全程依赖", "面试", "职场焦虑", "求职"]):
        return "《年会不能停！》/《我不是药神》"
    if any(term in text for term in ["医疗", "税务", "飞刀费", "公对公", "纳税", "行业乱象", "整治"]):
        return "《我不是药神！》/《狂飙》"
    if any(term in text for term in ["范小勤", "这幅字", "写字", "字" ]):
        return "《狂飙》/《繁花》"
    if any(term in text for term in ["新能源汽车", "换回了燃油车", "燃油车", "车主"]):
        return "《年会不能停！》/《我不是药神》"
    if "凡人修仙传" in text:
        return "《凡人修仙传》/《斗破苍穹》"
    if any(term in text for term in ["戒网瘾", "非法拘禁", "家暴", "校园", "霸凌", "失踪", "遗书", "原生家庭"]):
        return "《隐秘的角落》/《漫长的季节》"
    if any(term in text for term in ["马拉松猝死", "猝死", "意外", "救人", "死亡", "真相"]):
        return "《不完美受害人》/《沉默的真相》"
    if any(term in text for term in ["离婚", "出轨", "婚姻", "彩礼", "亲子", "家庭"]):
        return "《小巷人家》/《都挺好》"
    if any(term in text for term in ["失业", "求职", "债务", "职场", "代价", "尊严"]):
        return "《年会不能停！》/《我不是药神》"
    if any(term in text for term in ["反转", "悬疑", "真相", "揭秘", "秘密"]):
        return "《唐朝诡事录》/《漫长的季节》"
    if any(term in title for term in ["剧", "电影", "综艺", "演员", "角色"]):
        return "《狂飙》/《繁花》"
    return "待补映射IP"


def article_mapped_human_core(row: dict[str, Any]) -> str:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("notes"), row.get("article_route_reason"))
    if any(term in text for term in ["AI 应届生", "豆包味", "全程依赖", "面试", "职场焦虑", "求职"]):
        return "体面与生存焦虑"
    if any(term in text for term in ["医疗", "税务", "飞刀费", "公对公", "纳税", "行业乱象", "整治"]):
        return "制度约束与利益出清"
    if any(term in text for term in ["范小勤", "这幅字", "写字", "字"]):
        return "命运与围观边界"
    if any(term in text for term in ["新能源汽车", "换回了燃油车", "燃油车", "车主"]):
        return "选择反悔与现实成本"
    if any(term in text for term in ["戒网瘾", "非法拘禁", "成年子女", "父母"]):
        return "控制与伤害边界"
    if any(term in text for term in ["猝死", "责任", "意外", "追责"]):
        return "公共责任与生命代价"
    if any(term in text for term in ["差评", "群嘲", "不买账", "口碑翻车"]):
        return "观众信任崩塌"
    if any(term in text for term in ["求职", "失业", "寒冬", "档期很空"]):
        return "体面与生存焦虑"
    if any(term in text for term in ["婚姻", "亲子", "家庭", "出轨", "离婚"]):
        return "关系撕裂与情感代价"
    return "待补人性内核"


def article_mapping_is_strong(row: dict[str, Any]) -> bool:
    mapped_ip = article_mapped_ip(row)
    mapped_core = article_mapped_human_core(row)
    return mapped_ip != "待补映射IP" and mapped_core != "待补人性内核"


def article_mapping_strength(row: dict[str, Any]) -> str:
    mapped_ip = article_mapped_ip(row)
    mapped_core = article_mapped_human_core(row)
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("notes"), row.get("article_route_reason"))
    if mapped_ip == "待补映射IP" or mapped_core == "待补人性内核":
        return "weak"
    if any(term in text for term in ["戒网瘾", "非法拘禁", "猝死", "差评", "求职", "离婚", "家暴", "原生家庭", "反转", "真相"]):
        return "strong"
    if any(term in text for term in ["古偶", "行业现状", "平台", "机制", "困境", "为什么越来越难爆", "影视寒冬", "为什么会吵"]):
        return "medium"
    if any(term in text for term in ["梅西", "Starlink", "SpaceX", "纳指", "AI", "财经", "篮球", "世界杯", "体育"]):
        return "weak"
    return "medium"


def article_has_entertainment_anchor(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("video_anchor_hint")).lower()
    source = str(row.get("source_name") or row.get("source") or "").lower()
    if source in {"guduo", "骨朵热度指数", "weibo_hotspot", "微博热点", "maoyan", "猫眼热榜"}:
        return False
    return any(term.lower() in text for term in ARTICLE_ENTERTAINMENT_ANCHOR_TERMS)


def article_semantic_anchor_floor(row: dict[str, Any]) -> int:
    title = compact_text(row.get("title") or "", limit=200)
    text = merged_text(title, row.get("summary"), row.get("content"), row.get("article_route_reason"))
    if "《" in text and "》" in text:
        return int(ANCHOR_CONFIG.get("floor_with_title_mark", 12))
    if re.search(r"[\u4e00-\u9fff]{2,4}[、/][\u4e00-\u9fff]{2,4}", title):
        return int(ANCHOR_CONFIG.get("floor_with_person", 12))
    if re.search(r"[\u4e00-\u9fff]{2,4}(演员|导演|艺人|编剧)", text):
        return int(ANCHOR_CONFIG.get("floor_with_person", 12))
    if any(term in text for term in ["影视行业", "古偶", "平台", "综艺市场", "票房"]):
        return int(ANCHOR_CONFIG.get("industry_floor", 8))
    return 0


def article_is_anchor_bound_industry_topic(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"))
    return article_semantic_anchor_floor(row) >= 12 and any(term in text for term in ["行业", "现状", "平台", "市场", "古偶", "求职", "影视寒冬"])


def article_mainline_gate(row: dict[str, Any], date: str) -> tuple[bool, int, int, int]:
    dims = article_base_dimension_scores(row, date)
    anchor = dims["anchor"]
    conflict = dims["conflict"]
    analysis = dims["analysis"]
    return (
        anchor >= int(MAINLINE_GATES.get("anchor", 12))
        and conflict >= int(MAINLINE_GATES.get("conflict", 10))
        and analysis >= int(MAINLINE_GATES.get("analysis", 8))
    ), anchor, conflict, analysis


def article_is_soft_topic(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"))
    return any(term in text for term in ARTICLE_SOFT_TOPIC_TERMS)


def article_text(row: dict[str, Any]) -> str:
    return merged_text(
        row.get("title"),
        row.get("content"),
        row.get("content_text"),
        row.get("summary"),
        row.get("notes"),
        row.get("article_route_reason"),
    )


def article_is_reference_only(row: dict[str, Any]) -> bool:
    return str(row.get("routing_tier") or "").lower() == "reference_only" or row.get("fit_article_group") is False


def article_has_commentary_signal(row: dict[str, Any]) -> bool:
    text = article_text(row)
    return any(term in text for term in ARTICLE_COMMENTARY_SIGNAL_TERMS)


def article_has_hard_excluded_topic(row: dict[str, Any]) -> bool:
    text = article_text(row)
    source_bucket = str(row.get("source_bucket") or "").lower()
    source = str(row.get("source_name") or row.get("source") or "").lower()
    if source_bucket in {"tencent_video", "dumou"} and not article_has_commentary_signal(row):
        return True
    if source in {"tencent_video", "tencent", "腾讯视频", "dumou"} and not article_has_commentary_signal(row):
        return True
    pure_info_terms = ["票房", "片单", "演员动态", "行业新闻", "公司动态", "平台战略", "排播", "官宣", "开机", "杀青"]
    if any(term in text for term in pure_info_terms) and not article_has_resonance_core(row):
        return True
    return any(term in text for term in ARTICLE_HARD_EXCLUDE_TERMS)


def article_is_bad_page(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("raw_text"))
    if any(term in text for term in ARTICLE_BAD_PAGE_TERMS):
        return True
    source = str(row.get("source_name") or row.get("source") or "").lower()
    if source in {"guduo", "骨朵热度指数", "weibo_hotspot", "微博热点", "maoyan", "猫眼热榜"}:
        return False
    if source in {"腾讯视频", "tencent", "tencent_video"}:
        return True
    natural_text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", text)
    return len(natural_text) < 18


def story_has_video_mother_signal(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("story_route_reason"), row.get("hook_type"))
    return any(term in text for term in VIDEO_STORY_SIGNAL_TERMS)


def story_is_soft_view(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("story_route_reason"))
    return any(term in text for term in VIDEO_SOFT_VIEW_TERMS)


def story_structure_hit_count(row: dict[str, Any]) -> int:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("story_route_reason"), row.get("hook_type"))
    checks = [
        any(term in text for term in ["我", "他", "她", "夫妻", "新郎", "新娘", "父亲", "母亲", "男友", "女友", "兄弟", "姐妹"]),
        any(term in text for term in ["婚礼", "那天", "后来", "因为", "刚", "当时", "突然", "结果", "直到"]),
        any(term in text for term in ["欠债", "悔婚", "出轨", "骗", "反转", "真相", "广播", "翻脸", "抓住", "离婚", "复仇", "秘密"]),
        any(term in text for term in ["婚礼现场", "村里", "家里", "学校", "医院", "灵堂", "饭桌", "车站", "直播间", "公司"]),
        any(term in text for term in ["反转", "原来", "没想到", "直到", "结果", "最后", "竟然"]),
        any(term in text for term in ["后果", "结局", "最后", "离开", "报警", "悔婚", "分手", "去世", "翻盘"]),
    ]
    return sum(1 for hit in checks if hit)


def story_is_convertible_mother(row: dict[str, Any]) -> bool:
    source = str(row.get("source") or row.get("source_name") or "").lower()
    if emotion_router_weight(row) < 0:
        return False
    if source not in {"zhihu", "xhs", "xhs_note", "netease_renjian", "douban_group", "toutiao", "wechat", "douyin", "bilibili", "reddit"}:
        return False
    if story_is_soft_view(row):
        return False
    return story_has_video_mother_signal(row) and story_structure_hit_count(row) >= 3 and story_capability_check(row)


def story_base_capability_scores(row: dict[str, Any]) -> dict[str, int]:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("story_route_reason"), row.get("article_route_reason"))
    return {
        "story": 95 if story_has_video_mother_signal(row) else 30,
        "relationship": 90 if any(term in text for term in ["夫妻", "父亲", "母亲", "丈夫", "妻子", "前任", "家人", "恋人"]) else 30,
        "conflict": 90 if any(term in text for term in ["争吵", "翻脸", "悔婚", "出轨", "离婚", "反转", "真相", "冲突"]) else 35,
        "secret": 90 if any(term in text for term in ["秘密", "真相", "隐瞒", "不知道", "直到", "才知道"]) else 25,
        "twist": 90 if any(term in text for term in ["反转", "没想到", "结果", "原来", "竟然"]) else 25,
    }


def story_capability_check(row: dict[str, Any]) -> bool:
    scores = story_base_capability_scores(row)
    return (
        scores.get("relationship", 0) >= 60
        and scores.get("conflict", 0) >= 60
        and scores.get("secret", 0) >= 60
        and scores.get("twist", 0) >= 60
    )


def story_capability_missing(row: dict[str, Any]) -> list[str]:
    scores = story_base_capability_scores(row)
    missing: list[str] = []
    for key in ["relationship", "conflict", "secret", "twist"]:
        if scores.get(key, 0) < 60:
            missing.append(key)
    return missing


def story_comic_adaptation_score(row: dict[str, Any]) -> int:
    if emotion_router_weight(row) < 0:
        return 20
    if not story_has_video_mother_signal(row):
        return 20
    if story_structure_hit_count(row) < 3:
        return 35
    missing = story_capability_missing(row)
    if missing:
        return 45 if len(missing) <= 1 else 30
    return 90


def story_source_priority(row: dict[str, Any]) -> int:
    source = str(row.get("source_name") or row.get("source") or "").lower()
    source_type = str(row.get("source_type") or row.get("content_type") or "").lower()
    if source in {"zhihu", "xhs", "xhs_note", "douban_group", "wechat"}:
        return 0
    if source in {"weibo", "微博", "weibo_media"} and source_type in {"platform_post", "post_detail", "article", "long_text"}:
        return 1
    if source in {"netease_renjian", "reddit"}:
        return 2
    if source in {"toutiao", "douyin", "bilibili"}:
        return 4
    return 8


def emotion_router_bucket(row: dict[str, Any]) -> str:
    source = str(row.get("source_name") or row.get("source") or "").lower()
    source_type = str(row.get("source_type") or row.get("content_type") or "").lower()
    url_type = str(row.get("url_type") or "").lower()
    if source in EMOTION_ROUTER_BLOCKED_SOURCES:
        return "blocked_discovery"
    if source in {"weibo", "微博"} and (source_type in {"topic", "search", "hot_search"} or url_type in {"topic", "search"}):
        return "blocked_discovery"
    if source in {"netease_renjian", "网易人间"}:
        return "story_core"
    if source in {"douban_group", "豆瓣小组"}:
        return "relationship_forum"
    if source in {"zhihu", "知乎"}:
        return "zhihu_story"
    if source in {"weibo", "微博", "weibo_media"}:
        return "weibo_post"
    if source in {"xhs", "xhs_note", "小红书", "rednote"}:
        return "xiaohongshu_post"
    return "general"


def emotion_router_weight(row: dict[str, Any]) -> int:
    bucket = emotion_router_bucket(row)
    if bucket == "story_core":
        return 100
    if bucket == "relationship_forum":
        return 95
    if bucket == "zhihu_story":
        return 90
    if bucket == "weibo_post":
        return 85
    if bucket == "xiaohongshu_post":
        return 80
    if bucket == "blocked_discovery":
        return -100
    return 60


def emotion_router_capabilities(row: dict[str, Any]) -> list[str]:
    bucket = emotion_router_bucket(row)
    if bucket == "story_core":
        return ["story", "relationship", "conflict", "secret", "twist", "comic_adaptation"]
    if bucket == "relationship_forum":
        return ["relationship", "conflict", "secret", "twist", "comic_adaptation"]
    if bucket == "zhihu_story":
        return ["story", "conflict", "secret", "twist", "comic_adaptation"]
    if bucket == "weibo_post":
        return ["story", "relationship", "conflict", "comic_adaptation"]
    if bucket == "xiaohongshu_post":
        return ["story", "relationship", "emotion", "comic_adaptation"]
    return []


def capability_scores(row: dict[str, Any], kind: str) -> dict[str, int]:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("story_route_reason"), row.get("article_route_reason"))
    if kind == "article":
        return {
            "emotion": 90 if article_has_resonance_core(row) else 35,
            "hot_opinion": 85 if any(term in text for term in ["争议", "吵", "骂", "翻车", "反转"]) else 40,
            "title_generation": 90 if len(compact_text(row.get("title") or "", limit=40)) <= 28 else 60,
            "wechat_article": 95 if row.get("source") in {"wechat", "微信公众号", "weixin"} else 70,
            "industry_analysis": 90 if article_is_industry_source(row) else 30,
            "trend": 80 if article_is_discovery_source(row) or article_has_today_hook(row) else 30,
            "data": 75 if any(term in text for term in ["数据", "票房", "热度", "收视", "排名", "增长"]) else 30,
            "event_discovery": 95 if article_is_discovery_source(row) else 20,
        }
    return {
        **story_base_capability_scores(row),
        "comic_adaptation": story_comic_adaptation_score(row),
    }


def candidate_profile(row: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == "article":
        router = article_router_bucket(row)
        weight = article_router_weight(row)
        capabilities = article_router_capabilities(row)
        scores = capability_scores(row, "article")
        topic_score = article_potential_score(row)
        evidence_capability_keys = ["wechat_article", "data", "trend", "industry_analysis"]
        evidence_score = max((scores.get(key, 0) for key in evidence_capability_keys if key in scores), default=0)
        if not compact_text(row.get("content") or ""):
            evidence_score = min(evidence_score, 59)
        write_readiness = (
            "write_ready_candidate" if evidence_score >= 75 and topic_score >= 70
            else "needs_evidence_backfill" if topic_score >= 75
            else "topic_hot_candidate" if topic_score >= 65
            else "topic_watch_candidate"
        )
        gate = "pass"
        reason = "clear opinion angle with rewriteable structure"
        if article_is_discovery_source(row):
            gate = "discovery_only"
            reason = "event discovery source; not a direct article production candidate"
        return {
            "router": router,
            "weight": weight,
            "capability": capabilities,
            "scores": {key: scores[key] for key in capabilities if key in scores},
            "final_score": article_daily_score(row),
            "topic_score": topic_score,
            "evidence_score": evidence_score,
            "write_readiness": write_readiness,
            "gate": gate,
            "reason": reason,
        }
    router = emotion_router_bucket(row)
    weight = emotion_router_weight(row)
    capabilities = emotion_router_capabilities(row)
    scores = capability_scores(row, "story")
    missing = story_capability_missing(row)
    gate = "pass"
    reason = "story structure is convertible for comic adaptation"
    if weight < 0:
        gate = "blocked_discovery"
        reason = "discovery-only source; excluded from emotion story seed pool"
    elif missing:
        gate = "blocked_story_seed"
        reason = f"missing {'/'.join(missing)}; emotional hook may be strong but story reversal is incomplete"
    return {
        "router": router,
        "weight": weight,
        "capability": capabilities,
        "scores": {key: scores[key] for key in capabilities if key in scores},
        "final_score": story_editorial_score(row),
        "gate": gate,
        "reason": reason,
    }


def video_candidate_profile(row: dict[str, Any]) -> dict[str, Any]:
    gate = "pass"
    reason = "video candidate is usable for script hook evaluation"
    if video_is_noise_candidate(row):
        gate = "noise_candidate"
        reason = "片单/频道入口/预告索引噪音"
    return {
        "router": "video_hook",
        "weight": 70,
        "capability": ["hook", "anchor", "retention"] if not video_is_noise_candidate(row) else [],
        "scores": {},
        "final_score": video_daily_score(row),
        "gate": gate,
        "reason": reason,
    }


def media_candidate_profile(row: dict[str, Any]) -> dict[str, Any]:
    gate = "pass"
    reason = "media anchor candidate kept for narrative review"
    if video_is_noise_candidate(row):
        gate = "noise_candidate"
        reason = "片单/频道入口/预告索引噪音"
    return {
        "router": "media_anchor",
        "weight": 60,
        "capability": ["anchor", "heat", "background"] if gate == "pass" else [],
        "scores": {},
        "final_score": media_editorial_score(row),
        "gate": gate,
        "reason": reason,
    }


def export_candidate_profile(row: dict[str, Any], domain: str) -> dict[str, Any]:
    if domain == "article":
        return candidate_profile(row, "article")
    if domain == "story":
        return candidate_profile(row, "story")
    if domain == "video":
        return video_candidate_profile(row)
    if domain == "media":
        return media_candidate_profile(row)
    return empty_candidate_profile(f"unsupported candidate profile domain: {domain}", gate="unsupported_domain")


def format_candidate_profile(profile: dict[str, Any]) -> list[str]:
    capability_text = ", ".join(f"{item}=true" for item in profile.get("capability", [])) or "none"
    score_text = ", ".join(f"{key}={value}" for key, value in profile.get("scores", {}).items()) or "none"
    return [
        "- Candidate Profile",
        f"  - Router: {profile.get('router', 'unknown')}",
        f"  - Capability: {capability_text}",
        f"  - Scores: {score_text}",
        f"  - Final Score: {profile.get('final_score', 0)}",
        f"  - Topic Score: {profile.get('topic_score', 0)}",
        f"  - Evidence Score: {profile.get('evidence_score', 0)}",
        f"  - Write Readiness: {profile.get('write_readiness', 'unknown')}",
        f"  - Gate: {profile.get('gate', 'unknown')}",
        f"  - Reason: {profile.get('reason', '') or 'n/a'}",
    ]


def empty_candidate_profile(reason: str, gate: str = "no_candidate") -> dict[str, Any]:
    return {
        "router": "none",
        "weight": 0,
        "capability": [],
        "scores": {},
        "final_score": 0,
        "topic_score": 0,
        "evidence_score": 0,
        "write_readiness": "no_candidate",
        "gate": gate,
        "reason": reason,
    }


def story_editorial_score(row: dict[str, Any]) -> int:
    score = 45
    router_weight = emotion_router_weight(row)
    if router_weight < 0:
        return 0
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("story_route_reason"), row.get("hook_type"))
    title = compact_text(row.get("title") or "", limit=120)

    if story_is_convertible_mother(row):
        score += 20
    elif story_has_video_mother_signal(row):
        score += 10

    structure_hits = story_structure_hit_count(row)
    score += min(18, structure_hits * 3)

    if story_has_script_anchor(row):
        score += 8
    if story_is_soft_view(row):
        score -= 12

    if any(term in text for term in ["反转", "真相", "争议", "离婚", "复仇", "悔婚", "高考", "毕业", "家暴", "认亲", "失踪"]):
        score += 6
    if any(term in title for term in ["故事", "经历", "真实", "婚礼", "离婚", "高考", "父亲", "母亲"]):
        score += 4

    if str(row.get("story_kind") or "") == "complete_story":
        score += 6
    if row.get("content"):
        score += 3

    score += max(0, min(12, (router_weight - 60) // 5))

    return max(0, min(score, 100))


def story_score_bucket_name(score: int) -> str:
    if score >= 90:
        return "A池"
    if score >= 75:
        return "B池"
    if score >= 60:
        return "C池"
    return "观察位"


def sort_story_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -emotion_router_weight(row),
            -story_editorial_score(row),
            -story_structure_hit_count(row),
            story_source_priority(row),
            str(row.get("publish_time") or row.get("rank_date") or ""),
            compact_text(row.get("title") or ""),
        ),
    )


def summarize_video_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- 状态：今日未产出视频候选。"

    ranked_rows = sort_video_rows(rows)
    strong_rows = [row for row in ranked_rows if video_daily_score(row) >= 75]
    backup_rows = [row for row in ranked_rows if 70 <= video_daily_score(row) < 75]
    watch_rows = [row for row in ranked_rows if 65 <= video_daily_score(row) < 70]
    lines = [f"- 候选总数：{len(rows)}｜75+：{len(strong_rows)}｜70-74：{len(backup_rows)}｜65-69：{len(watch_rows)}"]
    for label, bucket_rows in (("强候选", strong_rows), ("备选", backup_rows), ("观察位", watch_rows)):
        for index, row in enumerate(bucket_rows[:3], start=1):
            title = row.get("title") or "无标题"
            source = row.get("source_name") or row.get("source") or "未知来源"
            meta = row.get("publish_time") or row.get("channel") or row.get("rank_date") or "信息缺失"
            lines.append(f"- {label} {index}. [{source}] {title}｜{meta}｜{video_daily_score(row)}分")
    return "\n".join(lines)


def summarize_story_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- 状态：今日未产出故事母本候选。"

    ranked_rows = sort_story_rows(rows)
    convertible_rows = [row for row in ranked_rows if story_is_convertible_mother(row)]
    whitelist_rows = [row for row in convertible_rows if story_is_script_whitelist_candidate(row)]
    ready_rows = [row for row in convertible_rows if row not in whitelist_rows and story_script_gap_reason(row) == "可压剧本，待人工拍板"]
    lines = [
        f"- 候选总数：{len(rows)}｜可转母本：{len(convertible_rows)}｜直进剧本白名单：{len(whitelist_rows)}｜待人工拍板：{len(ready_rows)}"
    ]
    for label, bucket_rows in (("直进白名单", whitelist_rows), ("可压剧本", ready_rows), ("母本候选", convertible_rows)):
        for index, row in enumerate(bucket_rows[:3], start=1):
            title = row.get("title") or "无标题"
            source = row.get("source_name") or row.get("source") or "未知来源"
            meta = row.get("publish_time") or row.get("rank_date") or row.get("channel") or "信息缺失"
            lines.append(
                f"- {label} {index}. [{source}] {title}｜{meta}｜母本分 {story_editorial_score(row)}｜剧本就绪分 {story_script_ready_score(row)}"
            )
    return "\n".join(lines)


def video_daily_score(row: dict[str, Any]) -> int:
    score = 45
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("video_anchor_hint"))
    if any(term in text for term in VIDEO_STORY_SIGNAL_TERMS):
        score += 20
    if any(term in text for term in VIDEO_SOFT_VIEW_TERMS):
        score -= 10
    if row.get("video_anchor_hint"):
        score += 10
    if row.get("content"):
        score += 5
    score += min(12, (metric_int(row.get("like_count")) // 50000) * 2)
    return max(0, min(score, 100))


def sort_video_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -video_daily_score(row),
            -metric_int(row.get("like_count")),
            -metric_int(row.get("comment_count")),
            str(row.get("publish_time") or row.get("rank_date") or ""),
            compact_text(row.get("title") or ""),
        ),
    )


def metric_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return 0
    if text.endswith("+"):
        text = text[:-1]
    text = text.replace(",", "")
    if text.endswith("w"):
        try:
            return int(float(text[:-1]) * 10000)
        except ValueError:
            return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def article_engagement_bonus(row: dict[str, Any]) -> int:
    like_count = metric_int(row.get("like_count") or row.get("liked_count") or row.get("voteup_count") or row.get("digg_count"))
    comment_count = metric_int(row.get("comment_count") or row.get("hot_comment_count"))
    view_count = metric_int(row.get("view_count") or row.get("read_count") or row.get("play_count") or row.get("hot_score"))
    collect_count = metric_int(row.get("collect_count") or row.get("collected_count") or row.get("favorite_count"))
    share_count = metric_int(row.get("share_count"))

    bonus = 0

    if like_count >= 5000:
        bonus += 10
    elif like_count >= 2000:
        bonus += 8
    elif like_count >= 1000:
        bonus += 6
    elif like_count >= 300:
        bonus += 3

    if comment_count >= 1000:
        bonus += 10
    elif comment_count >= 300:
        bonus += 8
    elif comment_count >= 100:
        bonus += 6
    elif comment_count >= 30:
        bonus += 3

    if view_count >= 1000000:
        bonus += 10
    elif view_count >= 100000:
        bonus += 8
    elif view_count >= 10000:
        bonus += 6
    elif view_count >= 1000:
        bonus += 3

    if collect_count >= 3000:
        bonus += 4
    elif collect_count >= 1000:
        bonus += 3
    elif collect_count >= 300:
        bonus += 2

    if share_count >= 1000:
        bonus += 4
    elif share_count >= 300:
        bonus += 3
    elif share_count >= 100:
        bonus += 2

    return min(28, bonus)


def article_generate_title_candidates(row: dict[str, Any]) -> list[str]:
    title = compact_text(row.get("title") or "无标题", limit=26)
    candidates: list[str] = []
    for _, builder in ARTICLE_TITLE_FORMULAS.items():
        value = compact_text(builder(title), limit=30)
        if value and value not in candidates:
            candidates.append(value)
    if title not in candidates:
        candidates.insert(0, title)
    return candidates[:5]


def article_base_dimension_scores(row: dict[str, Any], date: str) -> dict[str, int]:
    text = article_text(row)
    title = compact_text(row.get("title") or "", limit=200)
    publish_time = str(row.get("publish_time") or row.get("rank_date") or "")

    anchor = article_semantic_anchor_floor(row)
    if article_has_entertainment_anchor(row) or anchor >= 12:
        if any(term in text for term in ["演员", "角色", "导演", "编剧", "电影", "剧", "综艺", "动画"]) or ("《" in text and "》" in text):
            anchor = max(anchor, 18)
        elif article_is_industry_source(row) or article_is_anchor_bound_industry_topic(row) or any(term in text for term in ["行业", "平台", "国剧", "票房", "短剧"]):
            anchor = max(anchor, 14)
        else:
            anchor = max(anchor, 10)
    heat = 5
    if publish_time.startswith(date):
        heat = 20
    elif publish_time.startswith(date[:7]):
        heat = 15
    elif article_has_today_hook(row):
        heat = 10

    conflict = 0
    if any(term in text for term in CONFLICT_CONFIG.get("strong", [])):
        conflict = 16
    elif any(term in text for term in CONFLICT_CONFIG.get("mid", [])):
        conflict = 11
    elif article_is_anchor_bound_industry_topic(row) and any(term in text for term in CONFLICT_CONFIG.get("industry_conflict", [])):
        conflict = 10
    elif any(term in text for term in CONFLICT_CONFIG.get("reverse", [])):
        conflict = 8
    else:
        conflict_hits = sum(1 for term in ARTICLE_SCORE_KEYWORDS["conflict"] if term in text)
        conflict = min(20, conflict_hits * 4)
    if conflict == 0 and article_has_commentary_signal(row):
        conflict = 10

    analysis_hits = sum(1 for term in ARTICLE_SCORE_KEYWORDS["analysis"] if term in text)
    analysis = min(15, analysis_hits * 3)
    if any(term in text for term in ANALYSIS_QUESTION_TERMS) or title.endswith("？") or title.endswith("?"):
        analysis = max(analysis, 10)
    if analysis == 0 and (article_is_industry_source(row) or article_is_anchor_bound_industry_topic(row)):
        analysis = 10

    title_candidates = article_generate_title_candidates(row)
    title_potential = 3
    if any(any(term in candidate for term in ARTICLE_SCORE_KEYWORDS["suspense"] + ARTICLE_SCORE_KEYWORDS["conflict"]) for candidate in title_candidates):
        title_potential = 12
    if any(char.isdigit() for char in title) or len(title) <= 28:
        title_potential += 2
    title_potential = min(15, title_potential)

    material = 3
    if article_is_industry_source(row):
        material = 8
    elif any(term in text for term in ["演员", "角色", "综艺", "电影", "剧", "动画", "平台"]):
        material = 6
    if article_has_today_hook(row):
        material = min(10, material + 2)

    return {
        "anchor": anchor,
        "heat": heat,
        "conflict": conflict,
        "analysis": analysis,
        "title": title_potential,
        "material": material,
    }


def article_base_score(row: dict[str, Any], date: str) -> int:
    if article_is_bad_page(row):
        return 0
    dims = article_base_dimension_scores(row, date)
    return max(0, min(100, sum(dims.values())))


def article_potential_signal_scores(row: dict[str, Any]) -> dict[str, int]:
    text = article_text(row)
    title = compact_text(row.get("title") or "", limit=200)
    signals = {
        "反差": 9 if any(term in text for term in ["逆袭", "翻车", "打脸", "没想到", "竟然", "当众求职", "档期很空", "无戏可拍", "影视寒冬"]) else 4 if article_has_commentary_signal(row) else 0,
        "情绪强度": 9 if any(term in text for term in ARTICLE_SCORE_KEYWORDS["emotion"]) else 4,
        "站队": 9 if any(term in text for term in ["争议", "吵", "骂", "对立", "分裂"]) else 3,
        "悬念": 9 if any(term in title for term in ARTICLE_SCORE_KEYWORDS["suspense"]) else 3,
        "代入感": 8 if any(term in text for term in ["观众", "我们", "普通人", "你", "我"]) else 3,
        "关系冲突": 9 if any(term in text for term in ARTICLE_SCORE_KEYWORDS["relationship"]) else 2,
        "发泄口": 8 if any(term in text for term in ARTICLE_SCORE_KEYWORDS["vent"]) else 2,
        "评论可吵": 9 if any(term in text for term in ["争议", "站队", "骂", "为什么", "是否"]) else 3,
    }
    return signals


def article_potential_score(row: dict[str, Any]) -> int:
    signals = article_potential_signal_scores(row)
    return max(0, min(100, round(sum(signals.values()) / 80 * 100)))


def article_semantic_signal_scores(row: dict[str, Any]) -> dict[str, int]:
    backend = get_semantic_backend_name()
    handler = SEMANTIC_BACKEND_HANDLERS.get(backend, _semantic_backend_ruleish_scores)
    return handler(row)


def article_semantic_score(row: dict[str, Any]) -> int:
    semantic = article_semantic_signal_scores(row)
    base = semantic["anchor"] + semantic["conflict"] + semantic["analysis"] + semantic["emotion"] + semantic["reverse"] + semantic["industry_reversal"]
    if article_has_today_hook(row):
        base += int(SEMANTIC_RULES_CONFIG.get("today_hook_bonus", 4))
    return max(0, min(100, base))


def article_daily_score(row: dict[str, Any]) -> int:
    date = str(row.get("rank_date") or row.get("publish_time") or datetime.now().strftime("%F"))[:10]
    return article_base_score(row, date)


def article_score_bucket_name(score: int) -> str:
    if score >= int(POOL_THRESHOLDS.get("S", 85)):
        return "S池"
    if score >= int(POOL_THRESHOLDS.get("A", 70)):
        return "A池"
    if score >= int(POOL_THRESHOLDS.get("B", 55)):
        return "B池"
    return "C池"


def article_pool_decision(row: dict[str, Any], date: str) -> tuple[str, str]:
    production_score = article_production_score(row, date)
    potential = article_potential_score(row)
    dims = article_base_dimension_scores(row, date)
    semantic_score = article_semantic_score(row)
    semantic_pool_floors = SEMANTIC_RULES_CONFIG.get("pool_floor", {}) if isinstance(SEMANTIC_RULES_CONFIG.get("pool_floor", {}), dict) else {}
    semantic_s_floor = int(semantic_pool_floors.get("s", 52))
    semantic_a_floor = int(semantic_pool_floors.get("a", 34))
    semantic_a_fallback_floor = int(semantic_pool_floors.get("a_fallback", 24))
    semantic_b_floor = int(semantic_pool_floors.get("b", 16))
    passes_mainline, anchor, conflict, analysis = article_mainline_gate(row, date)
    resonance_level = article_resonance_level(row)
    resonance_count = article_resonance_count(row)
    mapping_strength = article_mapping_strength(row)
    if not article_has_resonance_core(row) and production_score < int(POOL_THRESHOLDS.get("B", 55)) and semantic_score < semantic_b_floor and potential < 75:
        return "C池", "无共鸣内核且分数不足，压池"
    if article_has_hard_excluded_topic(row) and production_score < int(POOL_THRESHOLDS.get("A", 70)):
        return "C池", "纯资讯/行业/片单/票房/演员动态，生产分不足，压池"
    if mapping_strength == "weak":
        text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("notes"), row.get("article_route_reason"))
        weak_mapping_score_override = (article_has_entertainment_anchor(row) or article_is_reference_only(row)) and (
            production_score >= int(POOL_THRESHOLDS.get("A", 70)) or semantic_score >= semantic_a_fallback_floor or potential >= 75
        )
        if weak_mapping_score_override:
            pass
        elif article_resonance_count(row) >= 1 and any(term in text for term in [
            "医疗", "税务", "飞刀费", "公对公", "行业乱象", "整治",
            "AI 应届生", "豆包味", "全程依赖", "面试", "职场焦虑", "求职",
            "范小勤", "这幅字", "写字",
            "新能源汽车", "换回了燃油车", "燃油车", "车主",
        ]):
            return "B池", "弱映射但现实/人性共鸣明确，放宽进B"
        else:
            return "C池", "影视映射弱或缺失，分数不足，压池"
    if mapping_strength == "medium":
        if resonance_count >= 2:
            return "B池", "中映射 + 中共鸣"
        return "C池", "中映射但共鸣不足，压池"
    if resonance_level == "deep" and resonance_count >= 3 and (semantic_score >= semantic_b_floor or potential >= 40):
        return "S池", f"深度共鸣{resonance_count}核 + 强映射"
    if resonance_level == "mid" and resonance_count >= 1 and (semantic_score >= semantic_b_floor or potential >= 30):
        return "A池", f"中度共鸣{resonance_count}核 + 强映射"
    if production_score >= 85 or semantic_score >= semantic_s_floor or potential >= 88:
        return "S池", f"共鸣内核强 + 生产{production_score} + 潜力{potential} + 语义{semantic_score}"
    if passes_mainline or semantic_score >= semantic_a_floor or potential >= 80:
        return "A池", f"共鸣内核成立（冲突{conflict}/分析{analysis}）+ 语义{semantic_score}"
    if resonance_count >= 1 and (70 <= production_score <= 84 or semantic_score >= semantic_a_fallback_floor):
        return "A池", "共鸣内核进池"
    if resonance_count == 1 or 55 <= production_score <= 69 or semantic_score >= semantic_b_floor:
        return "B池", "共鸣内核弱进池"
    return "C池", "共鸣内核不足，压池"


def article_admission(row: dict[str, Any], date: str) -> dict[str, Any]:
    production_score = article_production_score(row, date)
    potential_score = article_potential_score(row)
    semantic_score = article_semantic_score(row)
    pool_name, pool_reason = article_pool_decision(row, date)
    passes_mainline, anchor, conflict, analysis = article_mainline_gate(row, date)
    resonance_count = article_resonance_count(row)
    resonance_level = article_resonance_level(row)
    risk_reason = ""
    if article_hard_block_reason(row):
        risk_reason = article_hard_block_reason(row)
    elif article_is_reference_only(row):
        risk_reason = "参考层来源，需补平台/评论/热度证据"
    elif article_has_hard_excluded_topic(row):
        risk_reason = "纯资讯/行业/片单/票房/演员动态风险，需转成观点/人物/冲突角度"
    elif not article_has_resonance_core(row) and not passes_mainline:
        risk_reason = "缺少共鸣内核，需补角度或人群代入"
    score_floor = int(POOL_THRESHOLDS.get("B", 55))
    score_eligible = production_score >= score_floor or potential_score >= 75 or semantic_score >= 24
    hook_eligible = (
        article_is_today_hook_candidate(row)
        and (article_has_resonance_core(row) or passes_mainline)
        and (article_has_entertainment_anchor(row) or not article_has_hard_excluded_topic(row) or production_score >= int(POOL_THRESHOLDS.get("A", 70)) or potential_score >= 75)
    )
    eligible = pool_name != "C池" and (score_eligible or hook_eligible) and (article_has_resonance_core(row) or passes_mainline or semantic_score >= 24 or potential_score >= 75)
    return {
        "pool": pool_name,
        "reason": pool_reason,
        "production_score": production_score,
        "potential_score": potential_score,
        "semantic_score": semantic_score,
        "passes_mainline": passes_mainline,
        "anchor": anchor,
        "conflict": conflict,
        "analysis": analysis,
        "risk_reason": risk_reason,
        "blocked_reason": risk_reason,
        "eligible": eligible,
        "recommended_write_type": article_recommended_write_type(row),
        "mapped_ip": article_mapped_ip(row),
        "mapped_human_core": article_mapped_human_core(row),
        "resonance_count": resonance_count,
        "resonance_level": resonance_level,
    }


def sort_article_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -article_router_weight(row),
            -article_daily_score(row),
            -article_potential_score(row),
            article_source_priority(row),
            str(row.get("publish_time") or row.get("rank_date") or ""),
            compact_text(row.get("title") or ""),
        ),
    )


def sort_article_production_rows(rows: list[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -article_router_weight(row),
            -article_production_score(row, date),
            -article_potential_score(row),
            article_source_priority(row),
            str(row.get("publish_time") or row.get("rank_date") or ""),
            compact_text(row.get("title") or ""),
        ),
    )


def article_bucket_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "S池": 0,
        "A池": 0,
        "B池": 0,
        "C池": 0,
        "主稿候选": 0,
        "备稿候选": 0,
        "观察位": 0,
        "不入列": 0,
    }
    for row in rows:
        bucket = article_score_bucket_name(article_production_score(row, str(row.get("rank_date") or datetime.now().strftime("%F"))[:10]))
        counts[bucket] += 1
        if bucket == "S池":
            counts["主稿候选"] += 1
        elif bucket == "A池":
            counts["备稿候选"] += 1
        elif bucket == "B池":
            counts["观察位"] += 1
        else:
            counts["不入列"] += 1
    return counts


def article_parse_publish_datetime(row: dict[str, Any]) -> datetime | None:
    value = str(row.get("publish_time") or row.get("rank_date") or "").strip()
    if not value:
        return None
    if re.fullmatch(r"\d{10}|\d{13}", value):
        timestamp = int(value) / (1000 if len(value) == 13 else 1)
        return datetime.fromtimestamp(timestamp)
    value = value.replace("Z", "+00:00")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        value = f"{value}T00:00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def article_freshness_gate(row: dict[str, Any], date: str) -> tuple[bool, str]:
    parsed = article_parse_publish_datetime(row)
    if parsed is None:
        return False, "缺发布时间，需补证据后再进白名单"
    try:
        run_day = datetime.fromisoformat(f"{date}T23:59:59")
    except ValueError:
        run_day = datetime.now()
    if parsed.tzinfo is not None and run_day.tzinfo is None:
        run_day = run_day.replace(tzinfo=parsed.tzinfo)
    elif parsed.tzinfo is None and run_day.tzinfo is not None:
        parsed = parsed.replace(tzinfo=run_day.tzinfo)
    age_hours = (run_day - parsed).total_seconds() / 3600
    if age_hours <= 72:
        return True, "72小时内"
    if age_hours > 24 * 7:
        return False, "超过7天且未标明今日新钩子"
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"))
    if any(term in text for term in ["今日", "最新", "官宣", "定档", "开播", "热度", "票房", "财报", "上线"]):
        return True, "超过72小时但疑似有新钩子，需人工复核"
    return False, "超过72小时且缺少明确新钩子"


def article_freshness_penalty(row: dict[str, Any], date: str) -> tuple[int, str]:
    ok, reason = article_freshness_gate(row, date)
    if ok:
        return 0, reason
    if "超过7天" in reason:
        if article_has_today_hook(row) or article_has_entertainment_anchor(row):
            return 6, f"{reason}｜有今日钩子/文娱锚点，降级放宽"
        return 10, reason
    if "超过72小时" in reason:
        if article_has_today_hook(row) or article_has_entertainment_anchor(row):
            return 3, f"{reason}｜有今日钩子/文娱锚点，降级放宽"
        return 6, reason
    if "缺发布时间" in reason:
        return 8, reason
    return 10, reason


def article_hard_block_reason(row: dict[str, Any]) -> str:
    if article_is_discovery_source(row):
        return "热点发现层，只作选题线索"
    if article_is_bad_page(row):
        return "正文不可用或页面噪音"
    if article_daily_score(row) < 60 and not article_has_resonance_core(row):
        return "基础分低于60"
    return ""


def article_publish_meta(row: dict[str, Any]) -> str:
    publish_time = compact_text(row.get("publish_time") or row.get("rank_date") or "", limit=40)
    channel = compact_text(row.get("channel") or "", limit=20)
    if publish_time and channel:
        return f"{publish_time}｜{channel}"
    if publish_time:
        return publish_time
    if channel:
        return channel
    return "信息缺失"


def article_production_score(row: dict[str, Any], date: str) -> int:
    base = article_base_score(row, date)
    potential = article_potential_score(row)
    penalty, _ = article_freshness_penalty(row, date)
    score = round(base * 0.65 + potential * 0.35) - penalty
    if row.get("cross_day_duplicate_hit"):
        score -= 6
    return max(0, min(100, score))


def article_reason_today(row: dict[str, Any]) -> str:
    score = article_daily_score(row)
    source = str(row.get("source_name") or row.get("source") or "未知来源")
    title = compact_text(row.get("title") or "无标题", limit=80)
    return f"来源 {source}，当前分数 {score}，题目《{title}》具备当天可执行性，适合进入文章组进一步收紧。"


def article_related_titles(row: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("hook_type"), row.get("topic"))
    signal_map = {
        "高考": "《最好的我们》",
        "父亲": "《漫长的季节》",
        "母亲": "《都挺好》",
        "家庭": "《都挺好》",
        "职场": "《年会不能停！》",
        "婚姻": "《春潮》",
        "原生家庭": "《狗十三》",
        "失业": "《年会不能停！》",
        "误会": "《隐秘的角落》",
        "真相": "《隐秘的角落》",
        "争议": "《漫长的季节》",
        "共鸣": "《漫长的季节》",
        "遗憾": "《狗十三》",
        "动画": "《长安三万里》",
        "综艺": "《一年一度喜剧大赛》",
        "电影": "《年会不能停！》",
        "剧": "《漫长的季节》",
    }
    for field in ("related_titles", "related_title", "film_title", "drama_title", "work_title", "title"):
        value = row.get(field)
        if isinstance(value, list):
            titles.extend(compact_text(item, limit=60) for item in value if str(item).strip())
        elif value:
            text = compact_text(value, limit=60)
            if text:
                titles.append(text)
    deduped: list[str] = []
    for title in titles:
        if title not in deduped:
            deduped.append(title)
    for keyword, mapped_title in signal_map.items():
        if keyword in text and mapped_title not in deduped:
            deduped.append(mapped_title)
    return deduped[:3]


def article_related_characters(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("hook_type"), row.get("topic"))
    signal_map = {
        "高考": "考生 / 家长 / 班主任",
        "父亲": "父亲 / 子女",
        "母亲": "母亲 / 子女",
        "家庭": "父母 / 子女 / 伴侣",
        "职场": "员工 / 主管 / HR",
        "婚姻": "夫妻 / 前任 / 家庭成员",
        "原生家庭": "父母 / 子女 / 旧关系",
        "失业": "求职者 / 家庭支撑者",
        "误会": "当事人 / 旁观者 / 调解者",
        "真相": "受害者 / 目击者 / 叙述者",
        "争议": "当事人 / 评论者 / 围观者",
        "共鸣": "普通人 / 相似经历者",
    }
    for field in ("related_characters", "characters", "人物", "人物关系", "relationship", "relationship_anchor"):
        value = row.get(field)
        if isinstance(value, list):
            values.extend(compact_text(item, limit=40) for item in value if str(item).strip())
        elif value:
            text = compact_text(value, limit=40)
            if text:
                values.append(text)
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    for keyword, mapped_value in signal_map.items():
        if keyword in text and mapped_value not in deduped:
            deduped.append(mapped_value)
    return deduped[:3]


def article_write_angle(row: dict[str, Any]) -> str:
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("hook_type"), row.get("topic"))
    if any(term in text for term in ["争议", "撕", "吵", "反转", "塌房", "回怼", "分手", "离婚"]):
        return "写今天为什么会吵起来，以及谁在推动情绪升级，不先写作品简介。"
    if any(term in text for term in ["情绪", "共鸣", "治愈", "崩溃", "心酸", "看哭"]):
        return "先写情绪命中点，再回到人物/关系锚点，最后补具体作品或事件。"
    if any(term in text for term in ["社会议题", "职场", "婚恋", "教育", "租房", "育儿", "性别"]):
        return "写议题如何落到具体人物关系和当事人处境，避免抽象说理。"
    if any(term in text for term in ["高考", "父亲", "母亲", "家庭", "原生家庭", "失业", "误会", "真相"]):
        return "先补情绪源头和关系链，再落到作品映射与可验证细节。"
    return "先补今天的触发点，再补人物关系或作品锚点，最后给出可验证的写法。"


def article_today_hook_source_weight(row: dict[str, Any]) -> int:
    source = str(row.get("source_name") or row.get("source") or row.get("hotboard_source") or "").lower()
    source_type = str(row.get("source_type") or row.get("content_type") or "").lower()
    url_type = str(row.get("url_type") or "").lower()
    if source in {"hotboard", "tophub_today", "微博热点", "weibo_hotspot", "微博热搜", "hotlist_web"}:
        return 0
    if source in {"weibo", "微博"} and (source_type in {"topic", "search", "hot_search"} or url_type in {"topic", "search"}):
        return 0
    if source in {"知乎", "zhihu"}:
        return 1
    if source in {"豆瓣", "douban", "豆瓣小组", "douban_group", "douban-group", "douban group"}:
        return 2
    if source in {"小红书", "xhs", "rednote"}:
        return 3
    if source in {"weibo", "微博", "weibo_media"} and source_type in {"platform_post", "post_detail", "article", "long_text"}:
        return 3
    if source in {"reddit"}:
        return 4
    if source in {"hupu", "虎扑", "nga"}:
        return 5
    if source in {"bilibili_comments", "bilibili-comment", "douyin_comments", "douyin-comment"}:
        return 6
    if source in {"微信公众号", "wechat", "weixin", "netease_renjian", "网易人间"}:
        return 7
    return 9


def article_today_hook_label(row: dict[str, Any]) -> str:
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("hook_type"), row.get("topic"))
    if row.get("hotboard_source"):
        if any(term in text for term in ["争议", "约谈", "曝光", "翻车", "争论", "骂", "投诉", "处罚", "离婚", "失业", "高考", "原生家庭", "误会"]):
            return "今日争议"
        if any(term in text for term in ["故事", "人物", "反转", "真相", "遗书", "父亲", "母亲", "家庭", "婚姻", "孩子", "成长"]):
            return "今日高共鸣故事"
        return "今日情绪"
    if any(term in text for term in ["争议", "撕", "吵", "塌房", "回怼", "反转"]):
        return "今日争议"
    if any(term in text for term in ["情绪", "共鸣", "治愈", "崩溃", "心酸", "看哭"]):
        return "今日情绪"
    if any(term in text for term in ["社会议题", "职场", "婚恋", "教育", "租房", "育儿", "性别"]):
        return "今日社会议题"
    return "今日高共鸣故事"


def article_today_hook_score(row: dict[str, Any]) -> int:
    score = 0
    score += 40 - min(article_today_hook_source_weight(row) * 5, 20)
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("hook_type"), row.get("topic"))
    if any(term in text for term in ["今日", "最新", "刚刚", "当下", "刚出", "热榜"]):
        score += 20
    if any(term in text for term in ["争议", "情绪", "共鸣", "社会议题", "故事", "反转", "吵"]):
        score += 20
    if article_has_today_hook(row):
        score += 20
    if any(term in text for term in ["二跳", "正文", "原文", "长文", "帖子", "回答"]):
        score += 10
    return max(0, min(score, 100))


def article_today_hook_missing(row: dict[str, Any]) -> str:
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("hook_type"), row.get("topic"))
    missing: list[str] = []
    if not any(term in text for term in ["二跳", "正文", "原文", "长文", "帖子", "回答"]):
        missing.append("缺二跳正文入口")
    if not article_related_characters(row):
        missing.append("缺人物锚点")
    if not article_related_titles(row):
        missing.append("缺作品锚点")
    if not any(term in text for term in ["今日", "最新", "刚刚", "当下", "热榜"]):
        missing.append("缺今天写它的理由")
    return "／".join(missing) if missing else "可直接补写"


def article_today_hook_next_fetch_hint(row: dict[str, Any]) -> str:
    source = str(row.get("source_name") or row.get("source") or row.get("hotboard_source") or "未知来源")
    url = str(row.get("url") or row.get("source_url") or "")
    title = compact_text(row.get("title") or "无标题", limit=80)
    source_lower = source.lower()
    if row.get("body_fetch_status") == "local_hit":
        return compact_text(row.get("next_fetch_hint") or "已命中本地二跳正文，可直接补摘要/人物关系/作品映射。", limit=120)
    if "知乎" in source or source_lower == "zhihu":
        return f"抓知乎问题页正文与高赞回答：{title}｜{url}"
    if "哔哩" in source or source_lower == "bilibili":
        return f"抓B站视频简介与评论二跳：{title}｜{url}"
    if "微信公众号" in source or source_lower in {"wechat", "weixin"}:
        return f"保留 article_vault 待抓状态：{title}｜{url}"
    if "豆瓣" in source or source_lower == "douban":
        return f"抓豆瓣讨论/影评正文：{title}｜{url}"
    if "微博" in source or source_lower == "weibo":
        return f"抓微博话题/长文二跳：{title}｜{url}"
    return f"人工确认二跳入口：{title}｜{url}"


def load_local_zhihu_body_index() -> dict[str, dict[str, Any]]:
    path = ROOT / "tmp" / "mediacrawler" / "zhihu" / "raw" / "zhihu_content_raw_real_01.jsonl"
    if not path.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            content_url = str(row.get("content_url") or "").strip()
            question_id = str(row.get("question_id") or "").strip()
            title = compact_text(row.get("title") or "", limit=120)
            if content_url:
                index[content_url] = row
            if question_id:
                index[f"question:{question_id}"] = row
            if title:
                index[f"title:{title}"] = row
    except Exception:
        return {}
    return index


def load_local_zhihu_backfill_index(date: str | None = None) -> dict[str, dict[str, Any]]:
    dates_to_try = [date] if date else []
    dates_to_try.extend(["2026-06-15"])
    paths = [
        HANDOVER / "01-DAILY-RUNS" / candidate / "media-intel-aios" / "zhihu-question-backfill.jsonl"
        for candidate in dates_to_try
        if candidate
    ]
    if not paths:
        paths = [HANDOVER / "01-DAILY-RUNS" / "2026-06-15" / "media-intel-aios" / "zhihu-question-backfill.jsonl"]
    path = next((item for item in paths if item.exists()), paths[0])
    if not path.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            question_id = str(row.get("question_id") or "").strip()
            title = compact_text(row.get("title") or row.get("candidate_title") or "", limit=120)
            if url:
                index[url] = row
            if question_id:
                index[f"question:{question_id}"] = row
            if title:
                index[f"title:{title}"] = row
    except Exception:
        return {}
    return index


def summarize_zhihu_backfill_status(date: str | None = None) -> dict[str, Any] | None:
    dates_to_try = [date] if date else []
    dates_to_try.extend(["2026-06-15"])
    paths = [
        HANDOVER / "01-DAILY-RUNS" / candidate / "media-intel-aios" / "zhihu-question-backfill.jsonl"
        for candidate in dates_to_try
        if candidate
    ]
    if not paths:
        paths = [HANDOVER / "01-DAILY-RUNS" / "2026-06-15" / "media-intel-aios" / "zhihu-question-backfill.jsonl"]
    path = next((item for item in paths if item.exists()), paths[0])
    if not path.exists():
        return None
    rows = load_jsonl(path)
    if not rows:
        return None
    cookie_modes = {str(row.get("cookie_mode") or "unknown") for row in rows}
    blocked_count = sum(1 for row in rows if str(row.get("body_fetch_status") or "") == "blocked")
    success_count = sum(1 for row in rows if str(row.get("body_fetch_status") or "") == "local_hit")
    return {
        "path": str(path),
        "rows": len(rows),
        "cookie_modes": sorted(cookie_modes),
        "blocked_count": blocked_count,
        "success_count": success_count,
    }


def zhihu_backfill_hint(row: dict[str, Any]) -> str:
    error_text = str(row.get("fetch_error") or "")
    explicit_hint = str(row.get("next_fetch_hint") or "").strip()
    if explicit_hint:
        return explicit_hint
    if "403" in error_text:
        return "知乎问题页返回 403，需提供 ZHIHU_COOKIE / ZHIHU_COOKIE_FILE 或浏览器态会话"
    if error_text:
        return f"知乎问题页抓取失败：{compact_text(error_text, limit=80)}"
    return "知乎问题页二跳正文待补"


def enrich_today_hook_row_with_local_body(row: dict[str, Any], zhihu_index: dict[str, dict[str, Any]], zhihu_backfill_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not zhihu_index and not zhihu_backfill_index:
        return row
    source = str(row.get("source_name") or row.get("source") or row.get("hotboard_source") or "")
    if "知乎" not in source and source.lower() != "zhihu":
        return row
    url = str(row.get("url") or row.get("source_url") or "").strip()
    title = compact_text(row.get("title") or row.get("candidate_title") or "", limit=120)
    question_match = re.search(r"question/(\d+)", url)

    matched = None
    if url and url in zhihu_index:
        matched = zhihu_index[url]
    elif question_match and f"question:{question_match.group(1)}" in zhihu_index:
        matched = zhihu_index[f"question:{question_match.group(1)}"]
    elif title and f"title:{title}" in zhihu_index:
        matched = zhihu_index[f"title:{title}"]

    backfill_matched = None
    if url and url in zhihu_backfill_index:
        backfill_matched = zhihu_backfill_index[url]
    elif question_match and f"question:{question_match.group(1)}" in zhihu_backfill_index:
        backfill_matched = zhihu_backfill_index[f"question:{question_match.group(1)}"]
    elif title and f"title:{title}" in zhihu_backfill_index:
        backfill_matched = zhihu_backfill_index[f"title:{title}"]

    if matched is None and backfill_matched is None:
        return row

    enriched = dict(row)

    if backfill_matched and backfill_matched.get("fetch_error") and matched is None:
        enriched["body_fetch_status"] = backfill_matched.get("body_fetch_status") or ("blocked" if "403" in str(backfill_matched.get("fetch_error") or "") else "pending")
        enriched["next_fetch_hint"] = zhihu_backfill_hint(backfill_matched)
        enriched["local_body_excerpt"] = ""
        enriched["local_body_url"] = backfill_matched.get("url") or url
        enriched["body_fetch_error"] = compact_text(backfill_matched.get("fetch_error") or "", limit=160)
        return enriched

    matched = matched or backfill_matched
    fetch_error = compact_text(matched.get("fetch_error") or "", limit=160)
    if fetch_error:
        enriched["body_fetch_status"] = matched.get("body_fetch_status") or ("blocked" if "403" in fetch_error else "fetch_error")
        enriched["next_fetch_hint"] = zhihu_backfill_hint(matched)
        enriched["local_body_excerpt"] = ""
        enriched["local_body_url"] = matched.get("content_url") or matched.get("url") or url
        enriched["body_fetch_error"] = fetch_error
        return enriched

    body_text = compact_text(matched.get("content_text") or matched.get("desc") or matched.get("title") or "", limit=220)
    enriched["content"] = merged_text(row.get("content"), body_text)
    enriched["summary"] = merged_text(row.get("summary"), matched.get("desc"), body_text)
    enriched["publish_time"] = row.get("publish_time") or matched.get("created_time") or matched.get("updated_time") or row.get("publish_time")
    enriched["body_fetch_status"] = "local_hit"
    enriched["next_fetch_hint"] = f"已命中本地知乎二跳正文：{body_text}"
    enriched["local_body_excerpt"] = body_text
    enriched["local_body_url"] = matched.get("content_url") or matched.get("url") or url
    return enriched




def article_is_today_hook_candidate(row: dict[str, Any]) -> bool:
    source = str(row.get("source_name") or row.get("source") or row.get("hotboard_source") or "").lower()
    if source not in ARTICLE_TODAY_HOOK_SOURCES:
        return False
    story_score = 0
    if any(row.get(key) for key in ("story_route_reason", "hook_type", "emotion_trigger", "script_ready_score")):
        story_score = int(row.get("script_ready_score") or row.get("story_editorial_score") or 0)
    ok, freshness_reason = article_freshness_gate(row, str(row.get("rank_date") or row.get("publish_time") or "2026-06-15")[:10])
    if not ok:
        return False
    if article_has_resonance_core(row) and article_today_hook_source_weight(row) <= 4:
        return True
    if article_daily_score(row) < 65 and story_score < 75 and not row.get("hotboard_source"):
        return False
    if row.get("hotboard_source"):
        title_text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("topic"))
        return any(term in title_text for term in ["电影", "剧", "综艺", "演员", "角色", "动画", "青春", "高考", "父亲", "母亲", "误会", "真相", "失业", "婚姻", "校园", "情绪", "争议", "故事"])
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("hook_type"), row.get("topic"), row.get("story_route_reason"))
    return any(term in text for term in ["今日", "最新", "刚刚", "当下", "争议", "情绪", "共鸣", "社会议题", "故事", "热榜", "回答", "帖子", "真相", "遗书", "高考", "父亲", "母亲", "失业", "彩礼", "离婚", "原生家庭", "戒网瘾", "非法拘禁", "猝死", "马拉松", "后背发凉", "成年人"])


def article_is_today_hook_allowed(row: dict[str, Any], date: str) -> bool:
    admission = article_admission(row, date)
    return article_is_today_hook_candidate(row) and admission["eligible"]


def article_is_discovery_allowed(row: dict[str, Any], date: str) -> bool:
    if not article_is_discovery_source(row):
        return False
    if article_is_reference_only(row) or article_has_hard_excluded_topic(row):
        return False
    return article_admission(row, date)["production_score"] >= int(POOL_THRESHOLDS.get("B", 55)) or article_has_today_hook(row)



def article_angle(row: dict[str, Any]) -> str:
    title = compact_text(row.get("title") or "无标题", limit=80)
    if any(keyword in title for keyword in ["婚姻", "离婚", "夫妻", "前任", "感情"]):
        return "优先走关系冲突 + 情绪代入 + 结果判断，不写空泛议论文。"
    if any(keyword in title for keyword in ["电影", "剧", "综艺", "演员", "角色"]):
        return "优先走作品/人物锚点 + 反差判断 + 真实讨论热度，不写泛泛剧情复述。"
    return "优先走具体人物/事件锚点 + 明确冲突 + 可验证结果，避免抽象空话。"


def article_risk(row: dict[str, Any]) -> str:
    title = compact_text(row.get("title") or "无标题", limit=80)
    if any(keyword in title for keyword in ["真实故事", "知乎", "小红书"]):
        return "注意真实性、时间线和人物关系核查；不确定信息降级表述。"
    return "注意标题数字、因果链和情绪判断是否可核，避免把社会热点硬写成文娱主稿。"


def article_has_today_hook(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("summary"), row.get("content"), row.get("rank_date"), row.get("hook_type")).lower()
    if any(term in text for term in ["今日", "最新", "官宣", "定档", "开播", "热度", "票房", "财报", "上线", "复盘", "回归", "爆款"]):
        return True
    return False


def article_is_writeable_hotspot(row: dict[str, Any]) -> bool:
    return article_is_discovery_source(row) and article_daily_score(row) >= 75 and article_has_entertainment_anchor(row) and article_has_today_hook(row)



def article_conclusion(row: dict[str, Any]) -> str:
    score = article_daily_score(row)
    if score >= 75:
        return "建议主稿"
    if score >= 70:
        return "建议备稿"
    return "暂不建议推进"


ARTICLE_WRITER_READY_STATUSES = {"main_article_ready", "write_ready_candidate"}


def article_writer_readiness(row: dict[str, Any], date: str) -> str:
    admission = article_admission(row, date)
    if not admission["eligible"]:
        return "needs_evidence_backfill" if admission["potential_score"] >= 75 else "topic_watch_candidate"
    if admission["pool"] == "S池":
        return "main_article_ready"
    if admission["pool"] == "A池":
        return "write_ready_candidate"
    if admission["pool"] == "B池":
        return "needs_evidence_backfill"
    return "topic_watch_candidate"


def article_is_whitelist_eligible(row: dict[str, Any], date: str) -> bool:
    admission = article_admission(row, date)
    if not admission["eligible"]:
        return False
    return article_writer_readiness(row, date) in ARTICLE_WRITER_READY_STATUSES

def build_article_structured_review(rows: list[dict[str, Any]], date: str) -> str:
    ranked_rows = sort_article_production_rows(rows, date)
    picked = [row for row in ranked_rows if article_is_whitelist_eligible(row, date)][:3]
    if not picked:
        blocked = [row for row in ranked_rows if article_admission(row, date)["blocked_reason"] or article_admission(row, date)["production_score"] >= 60][:3]
        today_hooks = [row for row in ranked_rows if article_is_today_hook_allowed(row, date)][:5]
        lines = ["## 文章组结构化复评", "- 今日无可直接进白名单的文章候选。"]
        if not today_hooks and not blocked:
            lines.extend(format_candidate_profile(empty_candidate_profile("no article candidate passed the minimum review threshold")))
        if today_hooks:
            lines.append("- 但存在今日钩子候选，可作为文章组补写入口，注意它不等于主稿白名单。")
            for index, row in enumerate(today_hooks, start=1):
                profile = candidate_profile(row, "article")
                lines.extend([
                    f"### 今日钩子候选 {index}",
                    f"- 题目：{compact_text(row.get('title') or '无标题', limit=100)}",
                    f"- 今日钩子：{article_today_hook_label(row)}",
                ])
                lines.extend(format_candidate_profile(profile))
                lines.extend([
                    f"- 对应影视作品：{', '.join(article_related_titles(row)) or '待补'}",
                    f"- 对应人物/关系：{', '.join(article_related_characters(row)) or '待补'}",
                    f"- 可写角度：{article_write_angle(row)}",
                    f"- 原文来源：{row.get('source_name') or row.get('source') or '未知来源'}｜{article_publish_meta(row)}",
                    f"- 缺什么补什么：{article_today_hook_missing(row)}",
                    f"- 发布时间：{article_publish_meta(row)}",
                    f"- 为什么值得写：{article_reason_today(row)}",
                    f"- 写作角度：{article_angle(row)}",
                    f"- 风险：{article_risk(row)}",
                    f"- 结论：{article_conclusion(row)}，但仍不直接进主稿白名单。",
                ])
        for index, row in enumerate(blocked, start=1):
            hard_reason = article_hard_block_reason(row)
            _, freshness_reason = article_freshness_penalty(row, date)
            reason = hard_reason or f"生产分不足：{article_production_score(row, date)}｜时效={freshness_reason}"
            profile = {**candidate_profile(row, "article"), "gate": "degraded_candidate", "reason": reason}
            lines.extend([
                f"### 降级候选 {index}",
                f"- 题目：{compact_text(row.get('title') or '无标题', limit=80)}",
                f"- 发布时间：{article_publish_meta(row)}",
            ])
            lines.extend(format_candidate_profile(profile))
        return "\n".join(lines)

    lines = ["## 文章组结构化复评"]
    for index, row in enumerate(picked, start=1):
        profile = candidate_profile(row, "article")
        lines.extend([
            f"### 文章候选 {index}",
            f"- 题目：{compact_text(row.get('title') or '无标题', limit=100)}",
            f"- 发布时间：{article_publish_meta(row)}",
        ])
        lines.extend(format_candidate_profile(profile))
        lines.extend([
            f"- 生产分：{article_production_score(row, date)}｜原始分：{article_daily_score(row)}｜时效：{article_freshness_penalty(row, date)[1]}",
            f"- 为什么今天值得写：{article_reason_today(row)}",
            f"- 写作角度：{article_angle(row)}",
            f"- 风险：{article_risk(row)}",
            f"- 结论：{article_conclusion(row)}",
        ])
    return "\n".join(lines)


def video_hook(row: dict[str, Any]) -> str:
    title = compact_text(row.get("title") or "无标题", limit=80)
    if video_is_noise_candidate(row):
        return "标题像片单/频道入口/预告索引，先不生成剧本钩子。"
    if any(keyword in title for keyword in ["离婚", "背叛", "秘密", "真相", "逆袭", "复仇"]):
        return f"所有人都以为事情已经定了，直到《{title}》把真相翻出来。"
    return f"没人想到，《{title}》背后真正能抓人的不是题材，而是人物关系突然翻面。"


def video_is_noise_candidate(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("video_anchor_hint"), row.get("content"))
    return any(term in text for term in VIDEO_NOISE_TITLE_TERMS)


def video_progression(row: dict[str, Any]) -> str:
    return "前 3 秒抛出冲突，中段连续抬高关系压力，结尾用反转或判断句卡评论区。"


def video_retention(row: dict[str, Any]) -> str:
    return "结尾必须留下‘如果是你会不会这样选’这类判断口，避免平叙收尾。"


def video_anchor(row: dict[str, Any]) -> str:
    anchor = compact_text(row.get("video_anchor_hint") or "", limit=80)
    return anchor or "无明确作品锚点，当前仅可视为弱候选"


def video_shot_plan(row: dict[str, Any]) -> str:
    return "可拆为：开场冲突镜头 / 关系升级镜头 / 反转揭晓镜头 / 评论引导收口镜头。"


def video_conclusion(row: dict[str, Any]) -> str:
    if video_is_noise_candidate(row):
        return "素材索引噪音，放弃"
    score = video_daily_score(row)
    if score >= 75 and row.get("video_anchor_hint"):
        return "建议立项"
    if score >= 70:
        return "建议改钩子后复评"
    return "暂不建议推进"


def build_video_structured_review(video_rows: list[dict[str, Any]], story_rows: list[dict[str, Any]], media_rows: list[dict[str, Any]]) -> str:
    ranked_video_rows = sort_video_rows(video_rows)[:3]
    ranked_story_rows = sort_story_rows(story_rows)[:3]
    ranked_media_rows = sort_media_rows(media_rows)[:3]
    if not ranked_video_rows and not ranked_story_rows and not ranked_media_rows:
        return "## 视频组结构化复评\n- 今日无可用视频候选。\n- 结论：补素材"

    story_count = sum(1 for row in story_rows if story_is_convertible_mother(row))
    script_story_count = sum(1 for row in story_rows if story_is_script_whitelist_candidate(row))
    media_count = sum(1 for row in media_rows if media_editorial_score(row) >= 75)

    lines = [
        "## 视频组结构化复评",
        f"- 热点发现层：{'有' if video_rows else '无'}",
        f"- 故事母本层：{'有' if story_count else '无'}",
        f"- 作品锚点层：{'有' if any(row.get('video_anchor_hint') for row in ranked_video_rows) else '无'}",
        f"- 人工策略层：{'有' if ranked_video_rows or ranked_story_rows or ranked_media_rows else '无'}",
        f"- 正式剧本/执行稿：{'有正式候选' if any(video_daily_score(row) >= 75 for row in ranked_video_rows) or script_story_count else '今日无正式剧本'}",
    ]
    for index, row in enumerate(ranked_video_rows, start=1):
        profile = export_candidate_profile(row, "video")
        lines.extend([
            f"### 视频候选 {index}",
            f"- 题目：{compact_text(row.get('title') or '无标题', limit=100)}",
        ])
        lines.extend(format_candidate_profile(profile))
        lines.extend([
            f"- 3秒钩子：{video_hook(row)}",
            f"- 连续递进：{video_progression(row)}",
            f"- 结尾停留：{video_retention(row)}",
            f"- 作品锚点：{video_anchor(row)}",
            f"- 拆镜头：{video_shot_plan(row)}",
            f"- 结论：{video_conclusion(row)}",
        ])
    for index, row in enumerate(ranked_story_rows, start=1):
        profile = export_candidate_profile(row, "story")
        lines.extend([
            f"### 故事源候选 {index}",
            f"- 题目：{compact_text(row.get('title') or '无标题', limit=100)}",
        ])
        lines.extend(format_candidate_profile(profile))
        lines.extend([
            f"- 来源：{row.get('source') or row.get('source_name') or '未知来源'}",
            f"- 结构命中：{story_structure_hit_count(row)}",
            f"- 剧本缺口：{story_script_gap_reason(row)}",
        ])
    for index, row in enumerate(ranked_media_rows, start=1):
        profile = export_candidate_profile(row, "media")
        lines.extend([
            f"### 噪声/素材候选 {index}",
            f"- 题目：{compact_text(row.get('title') or '无标题', limit=100)}",
        ])
        lines.extend(format_candidate_profile(profile))
        lines.extend([
            f"- 来源：{row.get('source') or row.get('source_name') or '未知来源'}",
            f"- 用途：仅作作品锚点/背景参考，不进母本主池",
        ])
    if story_count == 0 and media_count == 0:
        lines.append("- 补素材建议：当前缺真实叙事母本，先补故事源再谈正式剧本。")
    return "\n".join(lines)


def media_source_priority(row: dict[str, Any]) -> int:
    source = str(row.get("source") or "").lower()
    fetch_mode = str(row.get("fetch_mode") or "").lower()
    sample_path = str(row.get("sample_path") or "")

    if source == "bilibili" and fetch_mode == "live_url" and "bilibili.com/video" in sample_path:
        return 0
    if fetch_mode == "live_url":
        return 5
    if source in {"bilibili", "douyin"}:
        return 10
    return 20


def media_metric_priority(row: dict[str, Any]) -> int:
    like_count = int(row.get("like_count") or 0)
    comment_count = int(row.get("comment_count") or 0)
    share_count = int(row.get("share_count") or 0)
    return -(like_count * 3 + comment_count * 2 + share_count)


def media_editorial_score(row: dict[str, Any]) -> int:
    score = 50
    title = compact_text(row.get("title") or "")
    content = compact_text(row.get("content") or "", limit=120)
    merged = f"{title} {content}"
    like_count = int(row.get("like_count") or 0)
    comment_count = int(row.get("comment_count") or 0)
    share_count = int(row.get("share_count") or 0)

    if row.get("source") == "bilibili" and row.get("fetch_mode") == "live_url":
        score += 8
    if like_count >= 300000:
        score += 10
    elif like_count >= 100000:
        score += 6
    if comment_count >= 10000:
        score += 6
    elif comment_count >= 3000:
        score += 3
    if share_count >= 10000:
        score += 5
    elif share_count >= 3000:
        score += 2

    strong_hook_keywords = ["高考", "毕业", "动画", "原创", "反转", "锐评", "喜剧", "悬疑", "故事", "纪录", "电影", "三国", "AI"]
    if any(keyword in merged for keyword in strong_hook_keywords):
        score += 6

    discussion_keywords = ["为什么", "还能", "这才叫", "别", "是否", "原来", "锐评"]
    if any(keyword in merged for keyword in discussion_keywords):
        score += 4

    if len(title) >= 18:
        score += 2

    return max(0, min(score, 100))


def media_score_bucket_name(score: int) -> str:
    if score >= 75:
        return "强关注"
    if score >= 68:
        return "可跟进"
    return "观察位"


def sort_media_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("cross_day_adjusted_score", media_editorial_score(row))),
            media_source_priority(row),
            media_metric_priority(row),
            str(row.get("publish_time") or ""),
            compact_text(row.get("title") or ""),
        ),
    )


def compact_text(value: str, limit: int = 42) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def slugify_reference_text(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", compact_text(str(value).lower(), limit=80))
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"


def build_candidate_reference_id(row: dict[str, Any], kind: str, date: str, index: int) -> str:
    source = slugify_reference_text(row.get("source") or row.get("source_name") or "unknown")
    title = slugify_reference_text(row.get("title") or row.get("name") or "untitled")
    return f"candidate-{kind}/{date}/{source}/{index:02d}-{title}"


def build_candidate_reference_hints(row: dict[str, Any], kind: str, date: str) -> list[str]:
    source = str(row.get("source") or row.get("source_name") or "").strip()
    title = compact_text(row.get("title") or "无标题", limit=32)
    hints: list[str] = []
    if kind == "article":
        if source:
            hints.append(f"{source} 文章参考项候选，待回填 reference_library")
        hints.append(f"可按标题《{title}》补行业/平台参考")
    elif kind == "video":
        if source:
            hints.append(f"{source} 视频参考项候选，待回填 reference_library")
        hints.append(f"可按标题《{title}》补爆款短视频/剧本参考")
    else:
        if source:
            hints.append(f"{source} 母本参考项候选，待回填 reference_library")
        hints.append(f"可按标题《{title}》补短剧母本原文参考")
    hints.append(f"候选落点：{date}")
    return hints


def build_reference_hints(row: dict[str, Any], kind: str, date: str | None = None) -> tuple[list[str], list[str]]:
    resolved_date = date or str(row.get("rank_date") or row.get("publish_time") or datetime.now().strftime("%F"))[:10]
    reference_ids = [build_candidate_reference_id(row, kind, resolved_date, 1)]
    reference_hints = build_candidate_reference_hints(row, kind, resolved_date)
    return reference_ids, reference_hints


def build_reference_export_rows(date: str, article_rows: list[dict[str, Any]], video_rows: list[dict[str, Any]], story_rows: list[dict[str, Any]], media_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    export_rows: list[dict[str, Any]] = []
    selected_articles = [row for row in sort_article_rows(article_rows) if article_daily_score(row) >= 75 and article_is_reference_worthy(row)][:5]
    selected_videos = [row for row in sort_video_rows(video_rows) if video_daily_score(row) >= 75][:5]
    selected_media = [row for row in sort_media_rows(media_rows) if media_editorial_score(row) >= 75][:5]
    selected_stories = [row for row in sort_story_rows(story_rows) if story_is_convertible_mother(row) and story_editorial_score(row) >= 70][:10]

    for kind, rows, score_fn, target_library in (
        ("article", selected_articles, article_daily_score, "article-reference-library"),
        ("video", selected_videos, video_daily_score, "video-reference-library"),
        ("story", selected_stories, lambda row: 80 if str(row.get("story_kind") or "") == "complete_story" else 70, "story-reference-library"),
        ("media", selected_media, media_editorial_score, "story-reference-library"),
    ):
        for index, row in enumerate(rows, start=1):
            export_rows.append(
                {
                    "kind": kind,
                    "title": row.get("title") or "无标题",
                    "source": row.get("source") or row.get("source_name") or "未知来源",
                    "publish_time": row.get("publish_time") or row.get("rank_date") or row.get("channel") or "",
                    "score": score_fn(row),
                    "reference_ids": [build_candidate_reference_id(row, kind, date, index)],
                    "reference_hints": build_candidate_reference_hints(row, kind, date),
                    "target_library": target_library,
                }
            )
    return export_rows


def article_is_reference_worthy(row: dict[str, Any]) -> bool:
    title = compact_text(row.get("title") or "", limit=200)
    is_relationship_topic = any(term in title for term in ARTICLE_RELATIONSHIP_TERMS)
    has_entertainment_anchor = article_has_entertainment_anchor(row)
    if article_is_bad_page(row):
        return False
    if article_is_soft_topic(row) and not has_entertainment_anchor:
        return False
    if is_relationship_topic and not has_entertainment_anchor:
        return False
    return has_entertainment_anchor


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_source_status(decisions: list[SourceDecision]) -> str:
    if not decisions:
        return "- 无新增来源。"
    lines = []
    for decision in decisions:
        suffix = f"｜输出：{', '.join(decision.outputs)}" if decision.outputs else ""
        lines.append(f"- [{decision.category}] {decision.name}: {source_status_label(decision)}｜{decision.reason}{suffix}")
    return "\n".join(lines)


def run_zhihu_question_backfill(output_root: Path) -> StepResult:
    dispatch_path = output_root / "today-hook-dispatch.jsonl"
    backfill_path = output_root / "zhihu-question-backfill.jsonl"
    if not dispatch_path.exists():
        return StepResult(name="zhihu_question_backfill", status="SKIPPED", error=f"missing {dispatch_path.name}")
    command = [
        sys.executable,
        str(SCRIPTS / "zhihu_question_backfill.py"),
        "--dispatch",
        str(dispatch_path),
        "--output",
        str(backfill_path),
    ]
    return run_json_command("zhihu_question_backfill", command, cwd=ROOT)


def source_status_label(decision: SourceDecision) -> str:
    if decision.status != "CONNECTED":
        return decision.status
    reason = decision.reason.lower()
    if "本地" in decision.reason or "样本" in decision.reason or "sample" in reason:
        return "SAMPLE_CONNECTED"
    if "live" in reason or "真实 raw" in decision.reason or "单帖真实" in decision.reason:
        return "LIVE_CONNECTED"
    return "MIRROR_CONNECTED"


def build_director_review(
    date: str,
    article_rows: list[dict[str, Any]],
    video_rows: list[dict[str, Any]],
    story_rows: list[dict[str, Any]],
    media_rows: list[dict[str, Any]],
    results: list[StepResult],
    decisions: list[SourceDecision],
) -> str:
    show_media_lane = os.getenv("RUOYU_SHOW_MEDIA_LANE", "0") == "1"
    generated_at = datetime.now().strftime("%F %T")
    zhihu_backfill_status = summarize_zhihu_backfill_status(date)
    status_lines = []
    for result in results:
        if isinstance(result, dict):
            status = str(result.get("status") or "INFO")
            name = str(result.get("step") or "custom_step")
            message = str(result.get("message") or "")
            if status == "PASS":
                status_lines.append(f"- {name}: OK｜{message}" if message else f"- {name}: OK")
            else:
                status_lines.append(f"- {name}: {status}｜{message}" if message else f"- {name}: {status}")
            continue
        if result.status == "OK":
            status_lines.append(f"- {result.name}: OK")
        else:
            status_lines.append(f"- {result.name}: ERROR｜{result.error}")
    if zhihu_backfill_status:
        cookie_modes = zhihu_backfill_status.get("cookie_modes") or []
        if "provided" in cookie_modes:
            cookie_label = "已使用 cookie"
        elif "none" in cookie_modes:
            cookie_label = "未使用 cookie"
        else:
            cookie_label = "状态未知"
        status_lines.append(
            f"- zhihu_backfill_summary: {cookie_label}｜rows {zhihu_backfill_status['rows']}｜"
            f"blocked {zhihu_backfill_status['blocked_count']}｜local_hit {zhihu_backfill_status['success_count']}"
        )

    media_section = f"\n## 媒体源候选汇总\n{summarize_media_rows(media_rows)}" if show_media_lane else ""
    media_task_line = "\n- 媒体源：只把可与评论/后续联动的父内容保留进后续链路。" if show_media_lane else ""

    return f"""# {date} AIOS 日度总编排复评包

生成时间：{generated_at}

## 编排状态
{chr(10).join(status_lines)}

## 来源接入状态
{build_source_status(decisions)}

## 文章组候选汇总
{summarize_article_rows(article_rows)}

{build_article_structured_review(article_rows, date)}

## 视频组候选汇总
{summarize_video_rows(video_rows)}

{build_video_structured_review(video_rows, story_rows, media_rows)}

## 故事源候选汇总
{summarize_story_rows(story_rows)}

{media_section}

## 总监任务
- 文章组：从今日文章候选里收紧到主稿/备稿/放弃，并写入 `article-approved-latest.md` 对应口径。
- 视频组：从今日视频候选里收紧到剧本白名单/备选/放弃，并写入 `video-approved-latest.md` 对应口径。
- 故事源：优先复核真实叙事样本，标出可继续深挖的母本。
- 非母本候选：只把能服务故事判断或后续联动的内容保留进后续链路。{media_task_line}
- 若候选不足，明确写“来源不足/需补源”，不要拿旧系统结果冒充新系统结论。
"""


def build_feedback(
    date: str,
    article_rows: list[dict[str, Any]],
    video_rows: list[dict[str, Any]],
    story_rows: list[dict[str, Any]],
    media_rows: list[dict[str, Any]],
    decisions: list[SourceDecision],
    needs_retry: bool,
    retry_targets: list[str],
    retry_reason: str,
    dedupe_summary: str,
    cross_day_hits: dict[str, int],
) -> str:
    show_media_lane = os.getenv("RUOYU_SHOW_MEDIA_LANE", "0") == "1"
    zhihu_backfill_status = summarize_zhihu_backfill_status(date)
    eligible_article_rows = [row for row in article_rows if article_is_whitelist_eligible(row, date)]
    article_counts = article_bucket_counts(eligible_article_rows)
    convertible_story_count = sum(1 for row in story_rows if story_is_convertible_mother(row))
    source_counts = {
        "live": sum(1 for decision in decisions if source_status_label(decision) == "LIVE_CONNECTED"),
        "sample": sum(1 for decision in decisions if source_status_label(decision) == "SAMPLE_CONNECTED"),
        "mirror": sum(1 for decision in decisions if source_status_label(decision) == "MIRROR_CONNECTED"),
        "skipped": sum(1 for decision in decisions if decision.status == "SKIPPED"),
    }
    total_scored = max(1, len(article_rows) + len(story_rows) + (len(media_rows) if show_media_lane else 0))
    total_cross_day = sum(cross_day_hits.values())
    cross_day_risk = "高风险：跨天命中率超过70%，需补今日新源" if total_cross_day / total_scored > 0.7 else "可接受"
    zhihu_cookie_label = "未运行"
    if zhihu_backfill_status:
        cookie_modes = zhihu_backfill_status.get("cookie_modes") or []
        if "provided" in cookie_modes:
            zhihu_cookie_label = "已使用 cookie"
        elif "none" in cookie_modes:
            zhihu_cookie_label = "未使用 cookie"
        else:
            zhihu_cookie_label = "状态未知"
    zhihu_backfill_line = "- 知乎 backfill：未运行"
    zhihu_backfill_followup = ""
    if zhihu_backfill_status:
        zhihu_backfill_judgement = "未判定"
        if zhihu_backfill_status["success_count"] > 0:
            zhihu_backfill_judgement = "已打通"
        elif zhihu_backfill_status["blocked_count"] > 0 and "provided" in (zhihu_backfill_status.get("cookie_modes") or []):
            zhihu_backfill_judgement = "cookie 已提供但仍被拦截"
        elif zhihu_backfill_status["blocked_count"] > 0:
            zhihu_backfill_judgement = "未打通"
        elif zhihu_backfill_status["rows"] > 0:
            zhihu_backfill_judgement = "已运行但未命中正文"
        zhihu_backfill_line = (
            f"- 知乎 backfill：{zhihu_backfill_judgement}｜{zhihu_cookie_label}｜rows {zhihu_backfill_status['rows']}｜"
            f"blocked {zhihu_backfill_status['blocked_count']}｜local_hit {zhihu_backfill_status['success_count']}"
        )
        if "provided" in (zhihu_backfill_status.get("cookie_modes") or []) and zhihu_backfill_status["blocked_count"] > 0 and zhihu_backfill_status["success_count"] == 0:
            zhihu_backfill_followup = "- 知乎 backfill 提示：cookie 已提供但仍被拦截，需浏览器态会话"
        elif "provided" in (zhihu_backfill_status.get("cookie_modes") or []) and zhihu_backfill_status["success_count"] > 0:
            zhihu_backfill_followup = "- 知乎 backfill 提示：cookie 生效，已命中部分知乎二跳正文"
    video_summary_lines = [
        f"- 视频组候选：{len(video_rows)} 条",
        f"- 故事源候选：{len(story_rows)} 条",
    ]
    if show_media_lane:
        video_summary_lines.append(f"- 媒体源候选：{len(media_rows)} 条")
    video_summary_lines.append(f"- 漫剧高分母本池：{convertible_story_count} 条")
    dedupe_display = dedupe_summary if show_media_lane else re.sub(r"；?跨天命中提示：.*media \d+", "", dedupe_summary)

    return f"""# {date} Content Factory Daily Feedback

> 这是 `OpenClaw Content Factory v1` 的日度反馈草案。来源为 `[本地镜像]` 本地跑批产物，不等同于 `[在线猎手]` / `[在线总监]` 实时反馈。

## 采集层
- [本地镜像] `media-intel-aios` 今日总编排已运行。
- 来源接入：LIVE {source_counts['live']}｜SAMPLE {source_counts['sample']}｜MIRROR {source_counts['mirror']}｜SKIPPED {source_counts['skipped']}
{zhihu_backfill_line}
{zhihu_backfill_followup}

## 候选/评分层
- 文章组候选：{len(article_rows)} 条
- 文章分层：主稿候选 {article_counts['主稿候选']} 条｜备稿候选 {article_counts['备稿候选']} 条｜观察位 {article_counts['观察位']} 条｜不入列 {article_counts['不入列']} 条
{chr(10).join(video_summary_lines)}
- 去重摘要：{dedupe_display}
- 跨天风险：{cross_day_risk}
- 重爬标记：{'需要重爬' if needs_retry else '无需重爬'}
- 重爬原因：{retry_reason}
- 重爬优先平台：{' / '.join(retry_targets) if retry_targets else '无'}

## 总监复评层
- 见 `director-review-latest.md`

## 正式产出层
- 文章白名单仍以 `article-approved-latest.md` 为准
- 视频白名单仍以 `video-approved-latest.md` 为准
- 文章成品目标：正式主稿 1 篇 + 备稿 1-2 篇，宁缺毋滥
- 漫剧母本目标：75+ 且故事/作品锚点、结构通过复核才优先进剧本；发布时间只作核验提示，不作硬拦截
- 留存阈值：75+ 才进入生产池
"""


def article_is_discovery_source(row: dict[str, Any]) -> bool:
    source = str(row.get("source_name") or row.get("source") or "").lower()
    source_type = str(row.get("source_type") or row.get("content_type") or "").lower()
    url_type = str(row.get("url_type") or "").lower()
    if source in {"weibo", "微博", "weibo_media"} and source_type in {"platform_post", "post_detail", "article", "long_text"}:
        return False
    if source in {"weibo", "微博"} and (source_type in {"topic", "search", "hot_search"} or url_type in {"topic", "search"}):
        return True
    return source in ARTICLE_DISCOVERY_SOURCES | {"腾讯视频", "tencent", "tencent_video", "weibo_hotspot", "微博热点", "微博热搜", "hotboard", "tophub_today", "hotlist_web"}


def build_today_hook_dispatch(date: str, article_rows: list[dict[str, Any]], story_rows: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]]]:
    generated_at = datetime.now().strftime("%F %T")
    zhihu_index = load_local_zhihu_body_index()
    zhihu_backfill_index = load_local_zhihu_backfill_index(date)
    zhihu_backfill_status = summarize_zhihu_backfill_status(date)
    merged_rows = list(article_rows)
    if story_rows:
        merged_rows.extend(story_rows)
    candidates = [
        row for row in sort_article_rows(merged_rows)
        if article_is_today_hook_candidate(row) and article_is_whitelist_eligible(row, date)
    ]
    ranked_candidates = sorted(
        candidates,
        key=lambda row: (
            -article_today_hook_score(row),
            article_today_hook_source_weight(row),
            -article_daily_score(row),
        ),
    )
    deduped_candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for row in ranked_candidates:
        row = enrich_today_hook_row_with_local_body(row, zhihu_index, zhihu_backfill_index)
        if not row.get("title") and row.get("candidate_title"):
            row = {**row, "title": row.get("candidate_title")}
        key = (str(row.get("source") or row.get("source_name") or ""), compact_text(row.get("candidate_title") or row.get("title") or "无标题", limit=120))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_candidates.append(row)
    ranked_candidates = deduped_candidates[:10]

    export_rows: list[dict[str, Any]] = []
    if not ranked_candidates:
        zhihu_summary_lines: list[str] = []
        if zhihu_backfill_status:
            zhihu_summary_lines = [
                "## 知乎回填摘要",
                f"- rows：{zhihu_backfill_status['rows']}｜blocked {zhihu_backfill_status['blocked_count']}｜local_hit {zhihu_backfill_status['success_count']}",
                "",
            ]
        body = f"""# {date} today-hook-dispatch

生成时间：{generated_at}

{chr(10).join(zhihu_summary_lines)}

## 今日钩子候选
- 无

## 说明
- 当前输入里缺足够明确的“今天写它的理由”或缺二跳正文。
- 下一步优先补：豆瓣小组 / 小红书 / 知乎 / 热榜 / 微信公众号 的高共鸣正文。
"""
        return body, export_rows

    lines = [f"# {date} today-hook-dispatch", "", f"生成时间：{generated_at}"]
    if zhihu_backfill_status:
        lines.extend([
            "",
            "## 知乎回填摘要",
            f"- rows：{zhihu_backfill_status['rows']}｜blocked {zhihu_backfill_status['blocked_count']}｜local_hit {zhihu_backfill_status['success_count']}",
        ])
    lines.extend(["", "## 今日钩子候选"])
    for index, row in enumerate(ranked_candidates, start=1):
        profile = candidate_profile(row, "article")
        title = compact_text(row.get("title") or "无标题", limit=100)
        source = row.get("source_name") or row.get("source") or "未知来源"
        hook_label = article_today_hook_label(row)
        related_titles = article_related_titles(row)
        related_characters = article_related_characters(row)
        angle = article_write_angle(row)
        missing = article_today_hook_missing(row)
        publish_meta = article_publish_meta(row)
        score = article_today_hook_score(row)
        source_platform = row.get("source_platform_label") or row.get("source_platform") or row.get("source_platform_key") or source
        rank = row.get("rank")
        hot_score = row.get("hot_score")
        url = row.get("url") or row.get("source_url")
        url_type = row.get("url_type") or "unknown"
        lines.extend([
            f"### 今日钩子候选 {index}",
            f"- 今日钩子：{hook_label}",
            f"- 候选题目：{title}",
        ])
        lines.extend(format_candidate_profile(profile))
        lines.extend([
            f"- 对应影视作品：{', '.join(related_titles) or '待补'}",
            f"- 对应人物/关系：{', '.join(related_characters) or '待补'}",
            f"- 可写角度：{angle}",
            f"- 原文来源：{source}｜{publish_meta}",
            f"- 热榜信息：平台={source_platform}｜rank={rank if rank is not None else '待补'}｜hot_score={hot_score if hot_score is not None else '待补'}",
            f"- 二跳URL：{url or '待补'}｜url_type={url_type}",
            f"- 二跳/正文状态：{row.get('body_fetch_status') or 'pending'}",
            f"- 本地二跳摘要：{row.get('local_body_excerpt') or '待补'}",
            f"- next_fetch_hint：{row.get('next_fetch_hint') or article_today_hook_next_fetch_hint(row)}",
            f"- 缺什么补什么：{missing}",
            f"- today_hook_score：{score}",
        ])
        export_rows.append({
            "candidate_profile": profile,
            "today_hook": hook_label,
            "candidate_title": title,
            "related_titles": related_titles,
            "related_characters": related_characters,
            "write_angle": angle,
            "source": source,
            "source_platform": source_platform,
            "rank": rank,
            "hot_score": hot_score,
            "url": url,
            "url_type": url_type,
            "publish_meta": publish_meta,
            "body_fetch_status": row.get("body_fetch_status") or "pending",
            "local_body_excerpt": row.get("local_body_excerpt") or "",
            "local_body_url": row.get("local_body_url") or "",
            "next_fetch_hint": row.get("next_fetch_hint") or article_today_hook_next_fetch_hint(row),
            "today_hook_score": score,
            "missing": missing,
        })
    return "\n".join(lines) + "\n", export_rows


def build_article_approved(date: str, article_rows: list[dict[str, Any]]) -> str:
    generated_at = datetime.now().strftime("%F %T")
    ranked_rows = sort_article_production_rows(article_rows, date)
    buckets = {"S池": [], "A池": [], "B池": [], "C池": []}
    blocked_rows: list[tuple[dict[str, Any], str]] = []

    for row in ranked_rows:
        admission = article_admission(row, date)
        hard_reason = admission["blocked_reason"]
        if hard_reason:
            if admission["production_score"] >= int(POOL_THRESHOLDS.get("B", 55)):
                blocked_rows.append((row, hard_reason))
            continue
        bucket, bucket_reason = admission["pool"], admission["reason"]
        row = {**row, "article_pool_reason": bucket_reason}
        if bucket == "S池" and len(buckets["S池"]) >= 5:
            bucket = "A池"
        buckets[bucket].append(row)

    def article_incubation_angle(row: dict[str, Any], admission: dict[str, Any]) -> str:
        text = article_text(row)
        if article_has_entertainment_anchor(row) and any(term in text for term in ["平台", "行业", "变化", "规则", "流量"]):
            return "结构性角度：从平台/行业变化切入，解释为什么这类内容会被放大。"
        if any(term in text for term in ["婚姻", "夫妻", "婆媳", "亲密关系", "家庭"]):
            return "关系角度：从关系分工或情绪代偿切入，别直接复述原话题。"
        if any(term in text for term in ["争议", "翻车", "热搜", "回应", "评论区"]):
            return "冲突角度：拆谁在争、为什么争、争议背后的叙事错位。"
        if admission["semantic_score"] < 10:
            return "案例角度：先补一个具体人物/作品/事件锚点，再决定是否下笔。"
        return "反常识角度：不要顺着原题说，先找最容易被忽略的判断差。"

    def article_incubation_evidence(row: dict[str, Any], blocked_reason: str | None = None) -> str:
        if blocked_reason and "缺发布时间" in blocked_reason:
            return "补发布时间或原始出处，避免新鲜度误判。"
        if blocked_reason and "72小时" in blocked_reason:
            return "补今天的新钩子：新数据、新回应、新案例或新冲突。"
        if not article_has_entertainment_anchor(row):
            return "补作品/角色/演员/平台锚点，避免只剩泛情绪。"
        if not article_has_today_hook(row):
            return "补今天为什么写它的理由，例如热度变化、评论区新冲突或行业新动作。"
        return "补二跳正文、评论区高赞观点或可核验数据，增强成稿确定性。"

    def article_incubation_status(admission: dict[str, Any], blocked_reason: str | None = None) -> str:
        if blocked_reason:
            if admission["potential_score"] >= 75:
                return "needs_evidence_backfill｜爆款选题潜力成立，缺证据，不交 writer"
            return "topic_hot_candidate｜选题可留存观察，暂不进主稿"
        if admission["pool"] == "S池":
            return "main_article_ready｜证据和选题均成熟，可进主稿候选"
        if admission["pool"] == "A池":
            return "write_ready_candidate｜接近备稿，需最后证据复核"
        if admission["pool"] == "B池":
            return "needs_evidence_backfill｜可孵化，先补角度或证据"
        return "topic_watch_candidate｜仅观察，不建议直接写"

    def article_angle_title(row: dict[str, Any], angle_label: str) -> str:
        base_title = compact_text(row.get("title") or "无标题", limit=28)
        if angle_label == "反常识角度":
            return f"{base_title}，真正的问题可能不在表面情绪"
        if angle_label == "结构性角度":
            return f"从{base_title}往后看，这类内容为什么总会反复出现？"
        return f"别急着下结论，先用一个具体案例重看：{base_title}"

    def article_angle_reason(row: dict[str, Any], angle_label: str, admission: dict[str, Any], blocked_reason: str | None = None) -> str:
        if angle_label == "反常识角度":
            return "原题有情绪但结论偏直给，换成反常识切口更容易拉出判断差。"
        if angle_label == "结构性角度":
            if article_has_entertainment_anchor(row):
                return "候选已有作品/平台/人物锚点，适合延展成平台、行业或人群判断。"
            return "原题锚点弱，结构性角度能帮它摆脱单点情绪复述。"
        if blocked_reason:
            return "当前不适合直接写结论文，但可先补一个具体案例，让文章落地。"
        return "候选已有基础情绪，案例切口能补足可读性和成稿完整度。"

    def article_angle_evidence(row: dict[str, Any], angle_label: str, blocked_reason: str | None = None) -> str:
        if angle_label == "结构性角度":
            if article_has_entertainment_anchor(row):
                return "补平台规则、行业变化或同类案例对照。"
            return "补作品/角色/演员/平台锚点，否则结构分析会发空。"
        if angle_label == "案例切入角度":
            return "补一个真实人物、作品、事件或评论区案例，别只复述观点。"
        if blocked_reason and "72小时" in blocked_reason:
            return "补今天的新回应、新数据或新争议，增强动手理由。"
        return "补评论区高赞观点、热度变化或反方声音，让切口更锋利。"

    def article_angle_scores(row: dict[str, Any], angle_label: str, admission: dict[str, Any], blocked_reason: str | None = None) -> dict[str, int]:
        text = article_text(row)
        evidence_anchor = 25 if article_has_entertainment_anchor(row) else 10
        fresh_hook = 20 if article_has_today_hook(row) else 8
        conflict = 18 if any(term in text for term in ["争议", "冲突", "回应", "翻车", "对立", "离婚"]) else 8
        audience_relevance = 16 if any(term in text for term in ["婚姻", "家庭", "演员", "角色", "平台", "行业"]) else 10
        originality = 12 if angle_label == "反常识角度" else 10 if angle_label == "结构性角度" else 8
        writeability = 12 if admission["production_score"] >= 18 else 8
        if blocked_reason and "参考层来源" in blocked_reason:
            evidence_anchor = max(evidence_anchor - 6, 0)
        if blocked_reason and "基础分低于60" in blocked_reason:
            writeability = max(writeability - 2, 0)
        if angle_label == "结构性角度" and article_has_entertainment_anchor(row):
            writeability += 4
        if angle_label == "案例切入角度" and not article_has_entertainment_anchor(row):
            writeability += 2
        return {
            "evidence_anchor": evidence_anchor,
            "fresh_hook": fresh_hook,
            "conflict": conflict,
            "audience_relevance": audience_relevance,
            "originality": originality,
            "writeability": writeability,
        }

    def article_angle_pool(rows: list[tuple[dict[str, Any], dict[str, Any], str | None]]) -> list[dict[str, Any]]:
        pool: list[dict[str, Any]] = []
        angle_labels = ["反常识角度", "结构性角度", "案例切入角度"]
        for row, admission, blocked_reason in rows[:5]:
            angles: list[dict[str, Any]] = []
            for label in angle_labels:
                score_breakdown = article_angle_scores(row, label, admission, blocked_reason)
                articleability = sum(score_breakdown.values())
                recommendation = "是" if articleability >= 75 else "否"
                if 65 <= articleability < 75:
                    recommendation = "可观察"
                angles.append(
                    {
                        "label": label,
                        "title": article_angle_title(row, label),
                        "articleability": articleability,
                        "reason": article_angle_reason(row, label, admission, blocked_reason),
                        "evidence": article_angle_evidence(row, label, blocked_reason),
                        "recommended_for_second_review": recommendation,
                        "score_breakdown": score_breakdown,
                    }
                )
            pool.append(
                {
                    "row": row,
                    "admission": admission,
                    "blocked_reason": blocked_reason,
                    "angles": sorted(angles, key=lambda item: item["articleability"], reverse=True),
                }
            )
        return pool

    def build_article_incubation_rows() -> list[tuple[dict[str, Any], dict[str, Any], str | None]]:
        incubation: list[tuple[dict[str, Any], dict[str, Any], str | None]] = []
        seen_keys: set[str] = set()

        def row_key(row: dict[str, Any]) -> str:
            return str(row.get("id") or row.get("url") or row.get("title") or id(row))

        for row in ranked_rows:
            admission = article_admission(row, date)
            blocked_reason = admission["blocked_reason"]
            key = row_key(row)
            if key in seen_keys:
                continue
            if blocked_reason:
                if admission["production_score"] >= 12:
                    incubation.append((row, admission, blocked_reason))
                    seen_keys.add(key)
                continue
            if admission["pool"] in {"A池", "B池"}:
                incubation.append((row, admission, None))
                seen_keys.add(key)
            elif admission["pool"] == "C池" and admission["production_score"] >= 18 and admission["potential_score"] >= 28:
                incubation.append((row, admission, None))
                seen_keys.add(key)
            if len(incubation) >= 5:
                break
        return incubation[:5]

    incubation_rows = build_article_incubation_rows()
    incubation_angle_pool = article_angle_pool(incubation_rows)

    def build_article_angle_shortlist(angle_pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        shortlist: list[dict[str, Any]] = []
        for item in angle_pool:
            recommended_angles = [
                angle for angle in item.get("angles", [])
                if angle.get("recommended_for_second_review") == "是" and int(angle.get("articleability") or 0) >= 75
            ]
            if not recommended_angles:
                continue
            best_angle = max(recommended_angles, key=lambda angle: int(angle.get("articleability") or 0))
            shortlist.append(
                {
                    "row": item["row"],
                    "admission": item["admission"],
                    "blocked_reason": item["blocked_reason"],
                    "angle": best_angle,
                }
            )
        shortlist.sort(key=lambda item: int(item["angle"].get("articleability") or 0), reverse=True)
        return shortlist[:5]

    angle_shortlist = build_article_angle_shortlist(incubation_angle_pool)

    def top_titles(rows: list[dict[str, Any]]) -> list[str]:
        seen: list[str] = []
        for row in rows:
            for title in article_generate_title_candidates(row):
                if title not in seen:
                    seen.append(title)
                if len(seen) >= 5:
                    return seen[:5]
        return seen[:5]

    def best_write_style(row: dict[str, Any]) -> str:
        text = article_text(row)
        if any(term in text for term in ["争议", "翻车", "打脸", "塌房", "反转"]):
            return "争议型"
        if any(term in text for term in ["逆袭", "爆", "反超", "压过"]):
            return "逆袭型"
        if article_is_industry_source(row) or any(term in text for term in ["行业", "平台", "机制", "变化"]):
            return "行业型"
        if any(term in text for term in ["演员", "角色", "人物", "关系"]):
            return "人物型"
        return "事件型"

    def format_rows(rows: list[dict[str, Any]], include_potential: bool = True) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no approved article candidate in this bucket"), ensure_ascii=False)
        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            title = row.get("title") or "无标题"
            source = row.get("source_name") or row.get("source") or "未知来源"
            meta = row.get("publish_time") or row.get("rank_date") or row.get("channel") or "信息缺失"
            base_score = article_daily_score(row)
            admission = article_admission(row, date)
            production_score = admission["production_score"]
            potential_score = admission["potential_score"]
            semantic_score = admission["semantic_score"]
            dims = article_base_dimension_scores(row, date)
            signals = article_potential_signal_scores(row)
            reference_ids, reference_hints = build_reference_hints(row, "article")
            write_style = best_write_style(row)
            pool_name, pool_reason = admission["pool"], admission["reason"]
            profile = candidate_profile(row, "article")
            lines.append(f"- {index}. [{source}] {title}｜{meta}｜基础分{base_score}｜生产分{production_score}｜潜力分{potential_score}｜语义分{semantic_score}｜分池={pool_name}｜进池依据={row.get('article_pool_reason') or pool_reason}｜reference_ids={reference_ids}｜candidate_profile={json.dumps(profile, ensure_ascii=False)}")
            lines.append(f"  - 维度：锚点{dims['anchor']} 热度{dims['heat']} 冲突{dims['conflict']} 分析{dims['analysis']} 标题{dims['title']} 素材{dims['material']}")
            if include_potential:
                lines.append(f"  - 信号：" + " ".join(f"{k}{v}" for k, v in signals.items()))
                lines.append(f"  - 推荐写法：{write_style}")
                lines.append(f"  - 推荐标题：" + "｜".join(top_titles([row])))
            lines.append(f"  - reference_hints={reference_hints}")
        return "\n".join(lines)

    def format_blocked_rows(rows: list[tuple[dict[str, Any], str]]) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no blocked article candidate to export", gate="empty_blocked_bucket"), ensure_ascii=False)
        lines: list[str] = []
        for index, (row, reason) in enumerate(rows[:8], start=1):
            title = row.get("title") or "无标题"
            source = row.get("source_name") or row.get("source") or "未知来源"
            meta = row.get("publish_time") or row.get("rank_date") or row.get("channel") or "信息缺失"
            profile = {**candidate_profile(row, "article"), "gate": "degraded_candidate", "reason": reason}
            lines.append(f"- {index}. [{source}] {title}｜{meta}｜降级原因：{reason}｜candidate_profile={json.dumps(profile, ensure_ascii=False)}")
        return "\n".join(lines)

    def format_incubation_rows(rows: list[tuple[dict[str, Any], dict[str, Any], str | None]]) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no incubation article candidate in this bucket", gate="empty_incubation_bucket"), ensure_ascii=False)
        lines: list[str] = []
        for index, (row, admission, blocked_reason) in enumerate(rows, start=1):
            title = row.get("title") or "无标题"
            source = row.get("source_name") or row.get("source") or "未知来源"
            base_profile = candidate_profile(row, "article")
            profile = base_profile if not blocked_reason else {**base_profile, "gate": base_profile.get("write_readiness") or "needs_evidence_backfill", "reason": blocked_reason}
            lines.extend([
                f"### {index}. {title}",
                f"- 来源：[{source}]",
                f"- 当前状态：{article_incubation_status(admission, blocked_reason)}",
                f"- 分层评分：topic_score={profile.get('topic_score')}｜evidence_score={profile.get('evidence_score')}｜write_readiness={profile.get('write_readiness')}",
                f"- 失败原因：{blocked_reason or admission['reason']}",
                f"- 可尝试角度：{article_incubation_angle(row, admission)}",
                f"- 补充证据：{article_incubation_evidence(row, blocked_reason)}",
                f"- 人工建议：{'可人工改角度后二审' if admission['pool'] in {'A池', 'B池'} else '可观察，不建议直接写'}",
                f"- candidate_profile={json.dumps(profile, ensure_ascii=False)}",
            ])
        return "\n".join(lines)

    def format_angle_pool(angle_pool: list[dict[str, Any]]) -> str:
        if not angle_pool:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no article angle candidate in this bucket", gate="empty_angle_pool"), ensure_ascii=False)
        lines: list[str] = []
        for index, item in enumerate(angle_pool, start=1):
            row = item["row"]
            admission = item["admission"]
            blocked_reason = item["blocked_reason"]
            base_profile = candidate_profile(row, "article")
            profile = base_profile if not blocked_reason else {**base_profile, "gate": base_profile.get("write_readiness") or "needs_evidence_backfill", "reason": blocked_reason}
            best_angle_score = item["angles"][0]["articleability"] if item["angles"] else 0
            second_review = "是" if best_angle_score >= 75 else "否"
            if 65 <= best_angle_score < 75:
                second_review = "可观察"
            lines.extend([
                f"### {index}. {row.get('title') or '无标题'}",
                f"- 来源候选：{row.get('source_name') or row.get('source') or '未知来源'}",
                f"- 当前状态：{profile.get('gate')}",
                f"- 分层评分：topic_score={profile.get('topic_score')}｜evidence_score={profile.get('evidence_score')}｜write_readiness={profile.get('write_readiness')}",
                f"- 原始失败原因：{blocked_reason or admission['reason']}",
                f"- 推荐二审：{second_review}",
            ])
            for angle in item["angles"][:3]:
                breakdown = angle["score_breakdown"]
                lines.extend([
                    f"#### {angle['label']}",
                    f"- 标题草案：{angle['title']}",
                    f"- articleability：{angle['articleability']}",
                    f"- 成稿理由：{angle['reason']}",
                    f"- 需要补证据：{angle['evidence']}",
                    f"- 二审建议：{angle['recommended_for_second_review']}",
                    f"- 评分拆解：evidence_anchor={breakdown['evidence_anchor']} fresh_hook={breakdown['fresh_hook']} conflict={breakdown['conflict']} audience_relevance={breakdown['audience_relevance']} originality={breakdown['originality']} writeability={breakdown['writeability']}",
                ])
        return "\n".join(lines)

    def format_angle_shortlist(shortlist: list[dict[str, Any]]) -> str:
        if not shortlist:
            return "- 今日暂无推荐二审角度"
        lines = ["> 仅来自孵化池，不改变主稿/备稿 gate；用于人工二审。", ""]
        for index, item in enumerate(shortlist, start=1):
            row = item["row"]
            angle = item["angle"]
            blocked_reason = item["blocked_reason"]
            admission = item["admission"]
            lines.extend([
                f"### {index}. {row.get('title') or '无标题'}",
                f"- 推荐角度：{angle['label']}",
                f"- 标题草案：{angle['title']}",
                f"- articleability：{angle['articleability']}",
                f"- 推荐原因：{angle['reason']}",
                f"- 需要补证据：{angle['evidence']}",
                f"- 原始失败原因：{blocked_reason or admission['reason']}",
                f"- 建议动作：人工二审 / 补证据后可写",
                "",
            ])
        return "\n".join(lines).rstrip()

    return f"""# {date} article-approved-latest

生成时间：{generated_at}

> 说明：这是基于 `run_daily_pipeline.py` 自动生成的文章白名单草案；采用“topic_score（爆款选题潜力）+ evidence_score（证据成熟度）+ write_readiness（成稿就绪度）”三层口径。S/A/B/C 只做归池，不做一次性删题；高潜但证据不足进入补证据队列，补齐后再交 writer，主稿仍严出。

## S池（基础/生产双高）
{format_rows(buckets['S池'])}

## A池（主力供给）
{format_rows(buckets['A池'])}

## B池（可养题）
{format_rows(buckets['B池'])}

## C池（归档）
{format_rows(buckets['C池'])}

## 今日钩子候选（可补写）
{format_rows([row for row in sort_article_rows(article_rows) if article_is_today_hook_allowed(row, date)][:5], include_potential=False)}

## 热点发现层（不直接进主稿）
{format_rows([row for row in sort_article_rows(article_rows) if article_is_discovery_allowed(row, date)][:5], include_potential=False)}

## 硬闸门/生产分降级（不进白名单）
{format_blocked_rows(blocked_rows)}

## 今日文章角度短名单
{format_angle_shortlist(angle_shortlist)}

## 今日文章补证据队列（高潜不等于可写）
{format_incubation_rows(incubation_rows)}

## 今日文章角度池
{format_angle_pool(incubation_angle_pool)}
"""


def build_video_approved(
    date: str,
    video_rows: list[dict[str, Any]],
    media_rows: list[dict[str, Any]],
    story_rows: list[dict[str, Any]],
) -> str:
    generated_at = datetime.now().strftime("%F %T")
    ranked_video_rows = sort_video_rows(video_rows)
    clean_video_rows = [row for row in ranked_video_rows if not video_is_noise_candidate(row)]
    noise_video_rows = [row for row in ranked_video_rows if video_is_noise_candidate(row)]
    strong_videos = [row for row in clean_video_rows if video_daily_score(row) >= 75]
    backup_videos = [row for row in clean_video_rows if 70 <= video_daily_score(row) < 75]
    watch_videos = [row for row in clean_video_rows if 65 <= video_daily_score(row) < 70]

    ranked_media_rows = sort_media_rows(media_rows)
    convertible_media_rows = [row for row in ranked_media_rows if media_editorial_score(row) >= 75]
    ranked_story_rows = sort_story_rows(story_rows)
    blocked_story_rows = [
        row
        for row in ranked_story_rows
        if export_candidate_profile(row, "story").get("gate") in {"blocked_story_seed", "blocked_discovery"}
    ]
    convertible_story_rows = [row for row in ranked_story_rows if story_is_convertible_mother(row)]
    script_whitelist_story_rows = [row for row in convertible_story_rows if story_is_script_whitelist_candidate(row)]
    script_ready_story_rows = [row for row in convertible_story_rows if row not in script_whitelist_story_rows and story_script_gap_reason(row) == "可压剧本，待人工拍板"]

    def build_reference_hints(row: dict[str, Any], kind: str) -> tuple[list[str], list[str]]:
        source = str(row.get("source") or row.get("source_name") or "").lower()
        title = compact_text(row.get("title") or "无标题")
        reference_ids = [build_candidate_reference_id(row, kind, date, 1)]
        reference_hints: list[str] = []
        if kind == "media":
            if source:
                reference_hints.append(f"article-references/{date}/ 候选 {source} 锚点参考项")
            reference_hints.append(f"候选 reference_id，仅供回填参考：{reference_ids[0]}")
            reference_hints.append(f"可按标题《{title[:24]}》补作品锚点/热度/背景参考")
        else:
            if source:
                reference_hints.append(f"story-references/{date}/ 候选 {source} 故事参考项")
            reference_hints.append(f"候选 reference_id，仅供回填参考：{reference_ids[0]}")
            reference_hints.append(f"可按标题《{title[:24]}》补短剧母本原文参考")
        return reference_ids, reference_hints

    def format_video_rows(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no approved video candidate in this bucket"), ensure_ascii=False)
        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            title = compact_text(row.get("title") or "无标题")
            source = row.get("source") or row.get("source_name") or "未知来源"
            meta = row.get("publish_time") or row.get("channel") or row.get("rank_date") or "信息缺失"
            score = video_daily_score(row)
            reference_ids, reference_hints = build_reference_hints(row, "story")
            profile = export_candidate_profile(row, "video")
            lines.append(f"- {index}. [{source}] {title}｜{meta}｜{score}分｜reference_ids={reference_ids}｜reference_hints={reference_hints}｜candidate_profile={json.dumps(profile, ensure_ascii=False)}")
        return "\n".join(lines)

    def format_media_rows(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no approved media candidate in this bucket"), ensure_ascii=False)
        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            title = compact_text(row.get("title") or "无标题")
            source = row.get("source") or "未知来源"
            score = media_editorial_score(row)
            fetch_mode = row.get("fetch_mode") or "unknown"
            reference_ids, reference_hints = build_reference_hints(row, "media")
            profile = export_candidate_profile(row, "media")
            lines.append(f"- {index}. [{source}] {title}｜{fetch_mode}｜{score}分｜仅作作品锚点/背景复核｜reference_ids={reference_ids}｜reference_hints={reference_hints}｜candidate_profile={json.dumps(profile, ensure_ascii=False)}")
        return "\n".join(lines)

    def format_story_rows(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no approved story candidate in this bucket"), ensure_ascii=False)
        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            title = compact_text(row.get("title") or "无标题")
            source = row.get("source") or "未知来源"
            reason = row.get("story_route_reason") or "story_route"
            reference_ids, reference_hints = build_reference_hints(row, "story")
            score = story_editorial_score(row)
            ready_score = story_script_ready_score(row)
            bucket = story_score_bucket_name(score)
            block_reason = story_script_gap_reason(row)
            verify_note = "｜核验提示：发布时间可后补，不作入池拦截" if not row.get("publish_time") else ""
            status_note = "已进正式剧本候选" if story_is_script_whitelist_candidate(row) else f"未进剧本原因：{block_reason}"
            profile = export_candidate_profile(row, "story")
            lines.append(f"- {index}. [{source}] {title}｜{reason}｜母本分{score}｜剧本就绪分{ready_score}｜{bucket}｜可进入漫剧母本池｜{status_note}{verify_note}｜reference_ids={reference_ids}｜reference_hints={reference_hints}｜candidate_profile={json.dumps(profile, ensure_ascii=False)}")
        return "\n".join(lines)

    def format_script_whitelist_story_rows(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no script-whitelist story candidate in this bucket"), ensure_ascii=False)
        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            title = compact_text(row.get("title") or "无标题")
            source = row.get("source") or row.get("source_name") or "未知来源"
            reason = row.get("story_route_reason") or "story_route"
            score = story_editorial_score(row)
            ready_score = story_script_ready_score(row)
            reference_ids, reference_hints = build_reference_hints(row, "story")
            profile = export_candidate_profile(row, "story")
            lines.append(f"- {index}. [{source}] {title}｜{reason}｜母本分{score}｜剧本就绪分{ready_score}｜已满足结构/锚点/75+要求｜reference_ids={reference_ids}｜reference_hints={reference_hints}｜candidate_profile={json.dumps(profile, ensure_ascii=False)}")
        return "\n".join(lines)

    def format_blocked_story_rows(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("blocked_story_bucket", gate="empty_blocked_story_bucket"), ensure_ascii=False)
        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            title = compact_text(row.get("title") or "无标题")
            source = row.get("source") or row.get("source_name") or "未知来源"
            reason = row.get("story_route_reason") or "story_route"
            score = story_editorial_score(row)
            ready_score = story_script_ready_score(row)
            reference_ids, reference_hints = build_reference_hints(row, "story")
            profile = export_candidate_profile(row, "story")
            lines.append(f"- {index}. [{source}] {title}｜{reason}｜母本分{score}｜剧本就绪分{ready_score}｜不进主池｜reference_ids={reference_ids}｜reference_hints={reference_hints}｜candidate_profile={json.dumps(profile, ensure_ascii=False)}")
        return "\n".join(lines)

    def format_noise_rows(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "- 无｜candidate_profile=" + json.dumps(empty_candidate_profile("no noise video candidate in this bucket", gate="empty_noise_bucket"), ensure_ascii=False)
        return "\n".join(
            f"- {index}. [{row.get('source') or row.get('source_name') or '未知来源'}] {compact_text(row.get('title') or '无标题')}｜降级原因：片单/频道入口/预告索引噪音｜candidate_profile={json.dumps(export_candidate_profile(row, 'video'), ensure_ascii=False)}"
            for index, row in enumerate(rows[:8], start=1)
        )

    return f"""# {date} video-approved-latest

生成时间：{generated_at}

> 说明：这是基于 `run_daily_pipeline.py` 自动生成的视频白名单草案；正式剧本候选同时接受高分视频候选与已满足结构条件的高分故事母本，不再把完整母本长期卡在“待人工拍板”。

## 剧本白名单候选（75+）
{format_video_rows(strong_videos)}

## 故事母本直进剧本白名单（75+）
{format_script_whitelist_story_rows(script_whitelist_story_rows)}

## 可压剧本母本（75+，待人工拍板）
{format_story_rows(script_ready_story_rows)}

## 备选（70-74）
{format_video_rows(backup_videos)}

## 观察位（65-69）
{format_video_rows(watch_videos)}

## 可复核叙事母本（media 75+）
{format_media_rows(convertible_media_rows)}

## 已转完整故事母本（可继续压剧本）
{format_story_rows(convertible_story_rows)}

## 阻断候选（不进主池）
{format_blocked_story_rows(blocked_story_rows)}

## 噪音视频候选（不生成钩子）
{format_noise_rows(noise_video_rows)}
"""


def story_has_script_anchor(row: dict[str, Any]) -> bool:
    text = merged_text(row.get("title"), row.get("content"), row.get("summary"), row.get("story_route_reason"))
    return any(term in text for term in ["电影", "剧", "动画", "小说", "校园", "青春", "高考", "毕业", "民间故事", "真实故事", "真实经历", "情感", "男友", "女友", "兄弟", "婚礼", "逆袭"])


def story_structure_threshold(row: dict[str, Any]) -> int:
    return 3 if story_editorial_score(row) >= 90 else 4


def story_script_gap_reason(row: dict[str, Any]) -> str:
    reasons: list[str] = []
    if story_editorial_score(row) < 75:
        reasons.append("分数未达75+剧本线")
    if story_structure_hit_count(row) < story_structure_threshold(row):
        reasons.append("角色/冲突/转折结构不足")
    if not story_has_script_anchor(row):
        reasons.append("故事/作品锚点需补")
    return "；".join(reasons) if reasons else "可压剧本，待人工拍板"


def story_script_ready_score(row: dict[str, Any]) -> int:
    score = story_editorial_score(row)
    score += min(10, story_structure_hit_count(row) * 2)
    if story_has_script_anchor(row):
        score += 5
    if str(row.get("story_kind") or "") == "complete_story":
        score += 5
    if row.get("content"):
        score += 5
    return max(0, min(100, score))


def story_is_script_whitelist_candidate(row: dict[str, Any]) -> bool:
    return (
        story_is_convertible_mother(row)
        and story_editorial_score(row) >= 75
        and story_structure_hit_count(row) >= story_structure_threshold(row)
        and story_has_script_anchor(row)
    )


def collect_vocus_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "sources" / "vocus_fetch.json"
    article_output = output_root / "article-leads" / "vocus_article_leads.jsonl"
    story_output = output_root / "story-leads" / "vocus_story_leads.jsonl"
    results = [run_json_command("vocus_fetch", [sys.executable, str(SCRIPTS / "vocus_fetch.py"), "--sample-json", str(sample_path), "--output", str(fetch_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("vocus", "article_vault", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("vocus_collect", [sys.executable, str(SCRIPTS / "vocus_collect.py"), "--input", str(fetch_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("vocus", "article_vault", "CONNECTED", "已用通过 validate 的本地真实样本接入", [str(article_output), str(story_output)])


def collect_xhs_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    normalized_output = output_root / "sources" / "xhs_note_normalized.jsonl"
    article_output = output_root / "article-leads" / "xhs_article_leads.jsonl"
    story_output = output_root / "story-leads" / "xhs_story_leads.jsonl"
    results = [run_json_command("mediacrawler_xhs_note_normalize", [sys.executable, str(SCRIPTS / "mediacrawler_xhs_note_normalize.py"), "--input", str(sample_path), "--output", str(normalized_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("xhs_note", "article_story_vault", "SKIPPED", "normalize 失败", [])
    results.append(run_json_command("xhs_note_collect", [sys.executable, str(SCRIPTS / "xhs_note_collect.py"), "--input", str(normalized_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("xhs_note", "article_story_vault", "CONNECTED", "已用 MediaCrawler 真实样本接入 article/story 双路", [str(normalized_output), str(article_output), str(story_output)])


def collect_netease_renjian_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "sources" / "netease_renjian_fetch.json"
    story_output = output_root / "story-leads" / "netease_renjian_story_leads.jsonl"
    results = [run_json_command("netease_renjian_fetch", [sys.executable, str(SCRIPTS / "netease_renjian_fetch.py"), "--sample-html", str(sample_path), "--output", str(fetch_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], SourceDecision("netease_renjian", "story_vault", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("netease_renjian_collect", [sys.executable, str(SCRIPTS / "netease_renjian_collect.py"), "--input", str(fetch_output), "--output", str(story_output)], cwd=ROOT))
    story_rows = load_jsonl(story_output)
    return results, story_rows, SourceDecision("netease_renjian", "story_vault", "CONNECTED", "已用通过 validate 的真实故事 HTML 样本接入", [str(story_output)])


def collect_zhihu_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "sources" / "zhihu_fetch.json"
    article_output = output_root / "article-leads" / "zhihu_article_leads.jsonl"
    story_output = output_root / "story-leads" / "zhihu_story_leads.jsonl"
    results = [run_json_command("zhihu_fetch", [sys.executable, str(SCRIPTS / "zhihu_fetch.py"), "--sample-html", str(sample_path), "--output", str(fetch_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("zhihu", "article_story_vault", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("zhihu_collect", [sys.executable, str(SCRIPTS / "zhihu_collect.py"), "--input", str(fetch_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("zhihu", "article_story_vault", "CONNECTED", "已用通过 validate 的知乎本地样本接入 article/story 双路", [str(article_output), str(story_output)])


def collect_zhihu_mediacrawler_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    normalized_output = output_root / "sources" / "zhihu_fetch.json"
    article_output = output_root / "article-leads" / "zhihu_article_leads.jsonl"
    story_output = output_root / "story-leads" / "zhihu_story_leads.jsonl"
    results = [
        run_json_command(
            "mediacrawler_zhihu_content_normalize",
            [sys.executable, str(SCRIPTS / "mediacrawler_zhihu_content_normalize.py"), "--input", str(sample_path), "--output", str(normalized_output)],
            cwd=ROOT,
        )
    ]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("zhihu", "article_story_vault", "SKIPPED", "mediacrawler normalize 失败", [])
    results.append(run_json_command("zhihu_collect", [sys.executable, str(SCRIPTS / "zhihu_collect.py"), "--input", str(normalized_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("zhihu", "article_story_vault", "CONNECTED", "已用 MediaCrawler 知乎内容样本接入 article/story 双路", [str(article_output), str(story_output)])


def collect_tieba_mediacrawler_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    normalized_output = output_root / "sources" / "tieba_fetch.json"
    article_output = output_root / "article-leads" / "tieba_article_leads.jsonl"
    story_output = output_root / "story-leads" / "tieba_story_leads.jsonl"
    results = [
        run_json_command(
            "mediacrawler_tieba_note_normalize",
            [sys.executable, str(SCRIPTS / "mediacrawler_tieba_note_normalize.py"), "--input", str(sample_path), "--output", str(normalized_output)],
            cwd=ROOT,
        )
    ]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("tieba", "article_story_vault", "SKIPPED", "mediacrawler normalize 失败", [])
    results.append(run_json_command("tieba_collect", [sys.executable, str(SCRIPTS / "tieba_collect.py"), "--input", str(normalized_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("tieba", "article_story_vault", "CONNECTED", "已用 MediaCrawler 贴吧帖子样本接入 article/story 双路", [str(article_output), str(story_output)])


def collect_douban_group_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "sources" / "douban_group_fetch.json"
    article_output = output_root / "article-leads" / "douban_group_article_leads.jsonl"
    story_output = output_root / "story-leads" / "douban_group_story_leads.jsonl"
    results = [run_json_command("douban_group_fetch", [sys.executable, str(SCRIPTS / "douban_group_fetch.py"), "--sample-html", str(sample_path), "--output", str(fetch_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("douban_group", "article_story_vault", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("douban_group_collect", [sys.executable, str(SCRIPTS / "douban_group_collect.py"), "--input", str(fetch_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("douban_group", "article_story_vault", "CONNECTED", "已用通过 validate 的豆瓣小组本地样本接入 article/story 双路", [str(article_output), str(story_output)])


def collect_douban_group_topic(output_root: Path, topic_url: str | None, input_html: Path | None, cookie: str | None, use_browser: bool = False) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    raw_output = ROOT / "tmp/mediacrawler/douban-group/raw/douban_group_topic_raw_real_01.json"
    fetch_output = output_root / "sources" / "douban_group_fetch.json"
    article_output = output_root / "article-leads" / "douban_group_article_leads.jsonl"
    story_output = output_root / "story-leads" / "douban_group_story_leads.jsonl"
    results: list[StepResult] = []
    raw_source = raw_output

    if input_html and input_html.suffix.lower() in {".json", ".jsonl"}:
        raw_source = input_html
    else:
        fetch_script = "douban_group_topic_browser_fetch.py" if use_browser and topic_url and not input_html else "douban_group_topic_fetch.py"
        command = [sys.executable, str(SCRIPTS / fetch_script), "--output", str(raw_output)]
        if input_html:
            command.extend(["--input-html", str(input_html)])
        elif topic_url:
            command.extend(["--topic-url", topic_url])
            if cookie:
                command.extend(["--cookie", cookie])
        results.append(run_json_command("douban_group_topic_fetch", command, cwd=ROOT))
        if results[-1].status != "OK":
            return results, [], [], SourceDecision("douban_group", "article_story_vault", "SKIPPED", "真实单帖抓取失败（优先检查登录态/运行入口）", [str(raw_output)])

    fetch_output.parent.mkdir(parents=True, exist_ok=True)
    fetch_output.write_text(raw_source.read_text(encoding="utf-8"), encoding="utf-8")
    results.append(run_json_command("douban_group_collect", [sys.executable, str(SCRIPTS / "douban_group_collect.py"), "--input", str(fetch_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("douban_group", "article_story_vault", "CONNECTED", "已用单帖真实 raw 接入 article/story 双路", [str(raw_source), str(article_output), str(story_output)])


def collect_douban_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "sources" / "douban_fetch.json"
    article_output = output_root / "article-leads" / "douban_article_leads.jsonl"
    story_output = output_root / "story-leads" / "douban_story_leads.jsonl"
    results = [run_json_command("douban_fetch", [sys.executable, str(SCRIPTS / "douban_fetch.py"), "--sample-html", str(sample_path), "--output", str(fetch_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("douban", "article_vault", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("douban_collect", [sys.executable, str(SCRIPTS / "douban_collect.py"), "--input", str(fetch_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("douban", "article_vault", "CONNECTED", "已用通过 validate 的豆瓣影评本地样本接入 article 主链", [str(article_output)])


def collect_toutiao_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "sources" / "toutiao_fetch.json"
    article_output = output_root / "article-leads" / "toutiao_article_leads.jsonl"
    story_output = output_root / "story-leads" / "toutiao_story_leads.jsonl"
    results = [run_json_command("toutiao_fetch", [sys.executable, str(SCRIPTS / "toutiao_fetch.py"), "--sample-html", str(sample_path), "--output", str(fetch_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("toutiao", "article_story_vault", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("toutiao_collect", [sys.executable, str(SCRIPTS / "toutiao_collect.py"), "--input", str(fetch_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("toutiao", "article_story_vault", "CONNECTED", "已用通过 validate 的今日头条本地样本接入 article/story 双路", [str(article_output)] + ([str(story_output)] if story_rows else []))


def collect_reddit_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "sources" / "reddit_story_fetch.json"
    story_output = output_root / "story-leads" / "reddit_story_leads.jsonl"
    results = [run_json_command("reddit_story_fetch", [sys.executable, str(SCRIPTS / "reddit_story_fetch.py"), "--sample-json", str(sample_path), "--output", str(fetch_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], SourceDecision("reddit", "story_vault", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("reddit_story_collect", [sys.executable, str(SCRIPTS / "reddit_story_collect.py"), "--sample-json", str(sample_path), "--output", str(story_output)], cwd=ROOT))
    story_rows = load_jsonl(story_output)
    return results, story_rows, SourceDecision("reddit", "story_vault", "CONNECTED", "已用通过 validate 的 Reddit 匿名故事样本接入 story 主链", [str(story_output)])


def collect_wechat_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "sources" / "wechat_fetch.json"
    article_output = output_root / "article-leads" / "wechat_article_leads.jsonl"
    story_output = output_root / "story-leads" / "wechat_story_leads.jsonl"
    results = [run_json_command("wechat_fetch", [sys.executable, str(SCRIPTS / "wechat_fetch.py"), "--sample-html", str(sample_path), "--output", str(fetch_output)], cwd=ROOT)]
    if results[-1].status != "OK":
        return results, [], [], SourceDecision("wechat", "article_story_vault", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("wechat_collect", [sys.executable, str(SCRIPTS / "wechat_collect.py"), "--input", str(fetch_output), "--article-output", str(article_output), "--story-output", str(story_output)], cwd=ROOT))
    article_rows = load_jsonl(article_output)
    story_rows = load_jsonl(story_output)
    return results, article_rows, story_rows, SourceDecision("wechat", "article_story_vault", "CONNECTED", "已用通过 validate 的微信公众号本地样本接入 article/story 双路", [str(article_output), str(story_output)])


def collect_hotboard_sample(output_root: Path, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], SourceDecision]:
    output = output_root / "hotboard" / "hotboard_dispatch.jsonl"
    results = [run_json_command("hotboard_collect", [sys.executable, str(SCRIPTS / "hotboard_collect.py"), "--sample-json", str(sample_path), "--hotboard-source", "hotlist_web", "--output", str(output)], cwd=ROOT)]
    rows = load_jsonl(output)
    status = "CONNECTED" if results[-1].status == "OK" and rows else "SKIPPED"
    reason = "仅接本地样本 dispatch，二跳正文抓取仍待补" if status == "CONNECTED" else "collect 失败或无样本输出"
    return results, rows, SourceDecision("hotboard_hotlist_web", "hotboard", status, reason, [str(output)] if rows else [])


def collect_tophub_live(output_root: Path) -> tuple[list[StepResult], list[dict[str, Any]], SourceDecision]:
    fetch_output = output_root / "hotboard" / "tophub_fetch.json"
    whitelist_output = output_root / "hotboard" / "tophub_whitelist.json"
    dispatch_output = output_root / "hotboard" / "tophub_dispatch.jsonl"
    results = [
        run_json_command(
            "tophub_fetch",
            [sys.executable, str(SCRIPTS / "tophub_fetch.py"), "--hotboard-source", "tophub_today", "--output", str(fetch_output)],
            cwd=ROOT,
        )
    ]
    if results[-1].status != "OK":
        return results, [], SourceDecision("tophub_today", "hotboard", "SKIPPED", "fetch 失败", [])
    results.append(run_json_command("tophub_whitelist", [sys.executable, str(SCRIPTS / "tophub_platform_whitelist.py"), "--input", str(fetch_output), "--output", str(whitelist_output)], cwd=ROOT))
    if results[-1].status != "OK":
        return results, [], SourceDecision("tophub_today", "hotboard", "SKIPPED", "平台白名单过滤失败", [str(fetch_output)])
    results.append(run_json_command("hotboard_collect_tophub", [sys.executable, str(SCRIPTS / "hotboard_collect.py"), "--sample-json", str(whitelist_output), "--hotboard-source", "tophub_today", "--output", str(dispatch_output)], cwd=ROOT))
    rows = load_jsonl(dispatch_output)
    status = "CONNECTED" if results[-1].status == "OK" and rows else "SKIPPED"
    reason = "已按平台白名单过滤 TopHub 首页热点条目，作为旧 hotboard 远程源替代" if status == "CONNECTED" else "collect 失败或无样本输出"
    return results, rows, SourceDecision("tophub_today", "hotboard", status, reason, [str(fetch_output), str(whitelist_output), str(dispatch_output)] if rows else [str(fetch_output), str(whitelist_output)])


def collect_tophub_bilibili_live(output_root: Path, whitelist_path: Path | None = None, limit: int = 10) -> tuple[list[StepResult], list[dict[str, Any]], SourceDecision]:
    whitelist_output = whitelist_path or (output_root / "hotboard" / "tophub_whitelist.json")
    output = output_root / "media-leads" / "tophub_bilibili_live.jsonl"
    if not whitelist_output.exists():
        return [], [], SourceDecision("tophub_bilibili_live", "media_vault", "SKIPPED", "缺少 tophub whitelist 产物", [])
    results = [
        run_json_command(
            "tophub_bilibili_live_collect",
            [sys.executable, str(SCRIPTS / "tophub_bilibili_live_collect.py"), "--input", str(whitelist_output), "--output", str(output), "--limit", str(limit)],
            cwd=ROOT,
        )
    ]
    rows = load_jsonl(output)
    status = "CONNECTED" if results[-1].status == "OK" and rows else "SKIPPED"
    reason = "已从 TopHub 白名单中的 B站条目继续执行 live media fetch" if status == "CONNECTED" else "未抓到可用 B站 live media 记录"
    return results, rows, SourceDecision("tophub_bilibili_live", "media_vault", status, reason, [str(output)] if rows else [])


def collect_media_sample(output_root: Path, source_name: str, script_name: str, sample_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], SourceDecision]:
    output = output_root / "media-leads" / f"{source_name}_media.jsonl"
    step_name = script_name.removesuffix(".py")
    results = [run_json_command(step_name, [sys.executable, str(SCRIPTS / script_name), "--input", str(sample_path), "--output", str(output)], cwd=ROOT)]
    rows = load_jsonl(output)
    status = "CONNECTED" if results[-1].status == "OK" and rows else "SKIPPED"
    reason = "已用项目侧 MediaCrawler 真实父内容样本接入最小 media 链路" if status == "CONNECTED" else "normalize 失败或无输出"
    return results, rows, SourceDecision(source_name, "media_vault", status, reason, [str(output)] if rows else [])


def collect_media_story_routes(output_root: Path, source_name: str, media_path: Path) -> tuple[list[StepResult], list[dict[str, Any]], SourceDecision]:
    story_output = output_root / "story-leads" / f"{source_name}_story_leads.jsonl"
    results = [
        run_json_command(
            f"{source_name}_media_story_collect",
            [sys.executable, str(SCRIPTS / "media_story_collect.py"), "--input", str(media_path), "--story-output", str(story_output)],
            cwd=ROOT,
        )
    ]
    rows = load_jsonl(story_output)
    status = "CONNECTED" if results[-1].status == "OK" and rows else "SKIPPED"
    reason = "已从 media 父内容分流出 story 母本" if status == "CONNECTED" else "media 内容未命中 story 路由"
    return results, rows, SourceDecision(f"{source_name}_story_route", "story_vault", status, reason, [str(story_output)] if rows else [])


def classify_story_pool(output_root: Path, source_name: str, story_path: Path) -> tuple[list[StepResult], SourceDecision]:
    complete_output = output_root / "story-pool" / f"{source_name}_complete_story.jsonl"
    seed_output = output_root / "story-pool" / f"{source_name}_story_seed.jsonl"
    seed_outline_output = output_root / "story-pool" / f"{source_name}_story_seed_outline.jsonl"
    seed_script_output = output_root / "story-pool" / f"{source_name}_story_seed_script.jsonl"
    results = [
        run_json_command(
            f"{source_name}_story_seed_classify",
            [
                sys.executable,
                str(SCRIPTS / "story_seed_classify.py"),
                "--input", str(story_path),
                "--complete-output", str(complete_output),
                "--seed-output", str(seed_output),
                "--seed-outline-output", str(seed_outline_output),
            ],
            cwd=ROOT,
        )
    ]
    if seed_outline_output.exists() and seed_outline_output.stat().st_size > 0:
        results.append(
            run_json_command(
                f"{source_name}_story_seed_to_script",
                [
                    sys.executable,
                    str(SCRIPTS / "story_seed_to_script.py"),
                    "--input", str(seed_outline_output),
                    "--output", str(seed_script_output),
                ],
                cwd=ROOT,
            )
        )
    outputs = [str(path) for path in (complete_output, seed_output, seed_outline_output, seed_script_output) if path.exists() and path.stat().st_size > 0]
    status = "CONNECTED" if outputs else "SKIPPED"
    reason = "已完成完整故事/故事种子二次分流，并为故事种子补最小剧本草案" if outputs else "story 二次分流未产出结果"
    return results, SourceDecision(f"{source_name}_story_pool", "story_pool", status, reason, outputs)


def main() -> int:
    parser = argparse.ArgumentParser(description="media-intel-aios 日度总编排入口")
    parser.add_argument("--date", default=datetime.now().strftime("%F"), help="运行日期 YYYY-MM-DD")
    parser.add_argument(
        "--lane",
        choices=("all", "article", "video"),
        default="all",
        help="从抓取任务入口拆分 lane：article 只运行文章组抓取，video 只运行视频/故事组抓取，all 保持旧总入口",
    )
    parser.add_argument("--run-dumou", action="store_true", help="运行毒眸链路")
    parser.add_argument("--run-news-fallback", action="store_true", help="运行新闻 fallback 正文补位链路")
    parser.add_argument("--run-guduo", action="store_true", help="运行骨朵链路")
    parser.add_argument("--run-tencent", action="store_true", help="运行腾讯片单链路")
    parser.add_argument("--run-vocus", action="store_true", help="运行 Vocus 本地样本链路")
    parser.add_argument("--run-xiniu", action="store_true", help="运行犀牛娱乐本地样本链路")
    parser.add_argument("--run-xhs", action="store_true", help="运行小红书正文 MediaCrawler 本地样本链路")
    parser.add_argument("--run-netease-renjian", action="store_true", help="运行网易人间本地样本链路")
    parser.add_argument("--run-zhihu", action="store_true", help="运行知乎本地样本链路")
    parser.add_argument("--run-tieba", action="store_true", help="运行贴吧 MediaCrawler 本地样本链路")
    parser.add_argument("--run-douban", action="store_true", help="运行豆瓣影评本地样本链路")
    parser.add_argument("--run-douban-group", action="store_true", help="运行豆瓣小组本地样本链路")
    parser.add_argument("--run-toutiao", action="store_true", help="运行今日头条本地样本链路")
    parser.add_argument("--run-reddit", action="store_true", help="运行 Reddit 本地样本故事链路")
    parser.add_argument("--run-wechat", action="store_true", help="运行微信公众号本地样本链路")
    parser.add_argument("--dailyhot-article", default="", help="DailyHot 原始 API URL；留空时自动运行 dailyhot_inject.py 并摄入其 JSONL 产物")
    parser.add_argument("--run-hotboard", action="store_true", help="运行 Hotboard 本地样本 dispatch 链路")
    parser.add_argument("--run-tophub", action="store_true", help="运行 TopHub 首页热点链路")
    parser.add_argument("--run-tophub-bilibili-live", action="store_true", help="运行 TopHub 白名单中的 B站 live media 子链路")
    parser.add_argument("--run-media-bilibili", action="store_true", help="运行 B站 MediaCrawler 父内容本地样本链路")
    parser.add_argument("--run-media-douyin", action="store_true", help="运行抖音 MediaCrawler 父内容本地样本链路")
    parser.add_argument("--run-media-weibo", action="store_true", help="运行微博 MediaCrawler 父内容本地样本链路")
    parser.add_argument("--run-media-kuaishou", action="store_true", help="运行快手 MediaCrawler 父内容本地样本链路")
    parser.add_argument("--dumou-list-html", help="毒眸列表页本地 HTML")
    parser.add_argument("--dumou-profile-url", help="毒眸作者页 URL")
    parser.add_argument("--dumou-samples-dir", help="毒眸文章样本目录")
    parser.add_argument("--news-fallback-input", help="新闻 fallback JSONL 输入")
    parser.add_argument("--guduo-date", help="骨朵榜单日期 YYYY-MM-DD")
    parser.add_argument("--guduo-offline-dir", help="骨朵离线样本目录")
    parser.add_argument("--tencent-sample-html", help="腾讯片单 HTML 样本")
    parser.add_argument("--tencent-url", help="腾讯片单 URL")
    parser.add_argument("--vocus-sample-json", help="Vocus 本地样本 JSON/HTML")
    parser.add_argument("--xiniu-sample-html", help="犀牛娱乐本地 HTML 样本")
    parser.add_argument("--xhs-raw-input", help="小红书正文 MediaCrawler 原始 JSONL")
    parser.add_argument("--netease-renjian-sample-html", help="网易人间本地 HTML 样本")
    parser.add_argument("--zhihu-sample-html", help="知乎本地 HTML 样本")
    parser.add_argument("--zhihu-mediacrawler-input", help="知乎 MediaCrawler 原始 JSON/JSONL")
    parser.add_argument("--tieba-mediacrawler-input", help="贴吧 MediaCrawler 原始 JSON/JSONL")
    parser.add_argument("--douban-sample-html", help="豆瓣影评本地 HTML 样本")
    parser.add_argument("--douban-group-sample-html", help="豆瓣小组本地 HTML 样本")
    parser.add_argument("--douban-group-topic-url", help="豆瓣小组单帖 URL，优先于样本 HTML")
    parser.add_argument("--douban-group-browser", action="store_true", help="豆瓣小组单帖优先走浏览器态抓取")
    parser.add_argument("--douban-group-cookie", help="豆瓣小组抓取 Cookie")
    parser.add_argument("--toutiao-sample-html", help="今日头条本地 HTML 样本")
    parser.add_argument("--reddit-sample-json", help="Reddit 本地 JSON 样本")
    parser.add_argument("--wechat-sample-html", help="微信公众号本地 HTML 样本")
    parser.add_argument("--hotboard-sample-json", help="Hotboard 本地 JSON 样本")
    parser.add_argument("--media-bilibili-input", help="B站 MediaCrawler 父内容原始 JSONL")
    parser.add_argument("--media-douyin-input", help="抖音 MediaCrawler 父内容原始 JSONL")
    parser.add_argument("--media-weibo-input", help="微博 MediaCrawler 父内容原始 JSON/JSONL")
    parser.add_argument("--media-kuaishou-input", help="快手 MediaCrawler 父内容原始 JSONL")
    parser.add_argument(
        "--cross-day-policy",
        choices=("penalize", "block", "hint"),
        default="penalize",
        help="跨天命中策略：默认 penalize；可选 block 或退回 hint",
    )
    parser.add_argument(
        "--cross-day-penalty",
        type=int,
        default=20,
        help="跨天命中默认降权分值，仅在 penalize 模式生效",
    )
    parser.add_argument("--output-root", help="输出根目录，默认 handover-hotspot/01-DAILY-RUNS/<date>/media-intel-aios")
    args = parser.parse_args()

    article_lane_flags = {
        "run_dumou",
        "run_news_fallback",
        "run_guduo",
        "run_vocus",
        "run_xiniu",
        "run_douban",
        "run_hotboard",
        "run_tophub",
    }
    video_lane_flags = {
        "run_tencent",
        "run_xhs",
        "run_netease_renjian",
        "run_zhihu",
        "run_tieba",
        "run_douban_group",
        "run_toutiao",
        "run_reddit",
        "run_wechat",
        "run_tophub_bilibili_live",
        "run_media_bilibili",
        "run_media_douyin",
        "run_media_weibo",
        "run_media_kuaishou",
    }
    if args.lane == "article":
        for flag in video_lane_flags:
            setattr(args, flag, False)
    elif args.lane == "video":
        for flag in article_lane_flags:
            setattr(args, flag, False)
        args.dailyhot_article = "__DISABLED_FOR_VIDEO_LANE__"

    any_source_requested = any(
        [
            args.run_dumou,
            args.run_news_fallback,
            args.run_guduo,
            args.run_tencent,
            args.run_vocus,
            args.run_xiniu,
            args.run_xhs,
            args.run_zhihu,
            args.run_tieba,
            args.run_douban,
            args.run_douban_group,
            args.run_toutiao,
            args.run_reddit,
            args.run_wechat,
            args.run_hotboard,
            args.run_tophub,
            args.run_tophub_bilibili_live,
            args.run_media_bilibili,
            args.run_media_douyin,
            args.run_media_weibo,
            args.run_media_kuaishou,
            args.run_netease_renjian,
        ]
    )
    if not any_source_requested:
        if args.lane == "all":
            args.run_xhs = True
            args.run_zhihu = True
            args.run_douban = True
        elif args.lane == "article":
            args.run_douban = True
    elif args.lane == "article":
        for flag in video_lane_flags:
            setattr(args, flag, False)
    elif args.lane == "video":
        for flag in article_lane_flags:
            setattr(args, flag, False)

    date = args.date
    default_output_name = "media-intel-aios" if args.lane == "all" else f"media-intel-aios-{args.lane}-lane"
    output_root = Path(args.output_root) if args.output_root else HANDOVER / "01-DAILY-RUNS" / date / default_output_name
    output_root.mkdir(parents=True, exist_ok=True)

    results: list[StepResult] = []
    decisions: list[SourceDecision] = []

    article_rows: list[dict[str, Any]] = []
    video_rows: list[dict[str, Any]] = []
    story_rows: list[dict[str, Any]] = []
    media_rows: list[dict[str, Any]] = []
    emotion_rows: list[dict[str, Any]] = []

    def add_article_rows(rows: list[dict[str, Any]]) -> None:
        if args.lane != "video":
            article_rows.extend(rows)

    def add_video_rows(rows: list[dict[str, Any]]) -> None:
        if args.lane != "article":
            video_rows.extend(rows)

    def add_story_rows(rows: list[dict[str, Any]]) -> None:
        if args.lane != "article":
            story_rows.extend(rows)

    def add_media_rows(rows: list[dict[str, Any]]) -> None:
        if args.lane != "article":
            media_rows.extend(rows)

    def add_emotion_rows(rows: list[dict[str, Any]]) -> None:
        if args.lane != "video":
            emotion_rows.extend(rows)

    if args.run_dumou:
        dumou_collected = output_root / "dumou_collected.jsonl"
        dumou_articles = output_root / "article-leads" / "dumou_article_leads.jsonl"
        dumou_videos = output_root / "video-leads" / "dumou_video_leads.jsonl"

        collect_cmd = [sys.executable, str(SCRIPTS / "dumou_collect.py"), "--output", str(dumou_collected)]
        if args.dumou_list_html:
            collect_cmd.extend(["--list-html", args.dumou_list_html])
        elif args.dumou_profile_url:
            collect_cmd.extend(["--profile-url", args.dumou_profile_url])
        else:
            collect_cmd.extend(["--profile-url", "https://mp.sohu.com/profile?xpt=MTAyNDU2NzE0MDM5MDU2Mzg0MEBzb2h1LmNvbQ=="])
        if args.dumou_samples_dir:
            collect_cmd.extend(["--samples-dir", args.dumou_samples_dir])

        results.append(run_json_command("dumou_collect", collect_cmd, cwd=ROOT))

        if dumou_collected.exists():
            route_cmd = [
                sys.executable,
                str(SCRIPTS / "route_dumou_leads.py"),
                "--input",
                str(dumou_collected),
                "--article-output",
                str(dumou_articles),
                "--video-output",
                str(dumou_videos),
            ]
            results.append(run_json_command("route_dumou_leads", route_cmd, cwd=ROOT))
            add_article_rows(load_jsonl(dumou_articles))
            add_video_rows(load_jsonl(dumou_videos))
        else:
            results.append(StepResult(name="route_dumou_leads", status="ERROR", error="missing dumou_collected.jsonl"))

    if args.run_news_fallback:
        fallback_input = Path(args.news_fallback_input) if args.news_fallback_input else ROOT / "news" / "fallback" / "2026-06-11" / "news_fallback_sources.jsonl"
        fallback_articles = output_root / "article-leads" / "news_fallback_article_leads.jsonl"
        if fallback_input.exists():
            route_cmd = [
                sys.executable,
                str(SCRIPTS / "route_news_fallback_leads.py"),
                "--input",
                str(fallback_input),
                "--article-output",
                str(fallback_articles),
            ]
            results.append(run_json_command("route_news_fallback_leads", route_cmd, cwd=ROOT))
            add_article_rows(load_jsonl(fallback_articles))
        else:
            results.append(StepResult(name="route_news_fallback_leads", status="ERROR", error=f"missing {fallback_input.name}"))

    if args.run_guduo:
        guduo_collected = output_root / "guduo_collected.jsonl"
        guduo_articles = output_root / "article-leads" / "guduo_article_leads.jsonl"
        guduo_videos = output_root / "video-leads" / "guduo_video_leads.jsonl"
        collect_cmd = [
            sys.executable,
            str(SCRIPTS / "guduo_collect.py"),
            "--date",
            args.guduo_date or date,
            "--output",
            str(guduo_collected),
        ]
        if args.guduo_offline_dir:
            collect_cmd.extend(["--offline-dir", args.guduo_offline_dir])
        results.append(run_json_command("guduo_collect", collect_cmd, cwd=ROOT))
        if guduo_collected.exists():
            route_cmd = [
                sys.executable,
                str(SCRIPTS / "route_guduo_leads.py"),
                "--input",
                str(guduo_collected),
                "--article-output",
                str(guduo_articles),
                "--video-output",
                str(guduo_videos),
            ]
            results.append(run_json_command("route_guduo_leads", route_cmd, cwd=ROOT))
            add_article_rows(load_jsonl(guduo_articles))
            add_video_rows(load_jsonl(guduo_videos))
        else:
            results.append(StepResult(name="route_guduo_leads", status="ERROR", error="missing guduo_collected.jsonl"))

    if args.run_tencent:
        tencent_collected = output_root / "tencent_platform_collected.json"
        tencent_articles = output_root / "article-leads" / "tencent_article_leads.jsonl"
        tencent_videos = output_root / "video-leads" / "tencent_video_leads.jsonl"
        collect_cmd = [
            sys.executable,
            str(SCRIPTS / "tencent_platform_collect.py"),
            "--output",
            str(tencent_collected),
        ]
        if args.tencent_sample_html:
            collect_cmd.extend(["--sample-html", args.tencent_sample_html])
        elif args.tencent_url:
            collect_cmd.extend(["--url", args.tencent_url])
        results.append(run_json_command("tencent_platform_collect", collect_cmd, cwd=ROOT))
        if tencent_collected.exists():
            route_cmd = [
                sys.executable,
                str(SCRIPTS / "route_tencent_platform_leads.py"),
                "--input",
                str(tencent_collected),
                "--article-output",
                str(tencent_articles),
                "--video-output",
                str(tencent_videos),
            ]
            results.append(run_json_command("route_tencent_platform_leads", route_cmd, cwd=ROOT))
            add_article_rows(load_jsonl(tencent_articles))
            add_video_rows(load_jsonl(tencent_videos))
        else:
            results.append(StepResult(name="route_tencent_platform_leads", status="ERROR", error="missing tencent_platform_collected.json"))

    if args.run_vocus:
        sample_path = Path(args.vocus_sample_json) if args.vocus_sample_json else ARTICLE_SAMPLES / "vocus" / "vocus_article_sample_01.json"
        if sample_path.exists():
            step_results, new_articles, new_stories, decision = collect_vocus_sample(output_root, sample_path)
            results.extend(step_results)
            add_article_rows(new_articles)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("vocus", "article_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_xiniu:
        xiniu_collected = output_root / "xiniu_collected.jsonl"
        xiniu_articles = output_root / "article-leads" / "xiniu_article_leads.jsonl"
        sample_path = Path(args.xiniu_sample_html) if args.xiniu_sample_html else ROOT / "samples" / "xiniu-yule" / "xiniu_article_sample_01.html"
        collect_cmd = [
            sys.executable,
            str(SCRIPTS / "xiniu_collect.py"),
            "--sample-html",
            str(sample_path),
            "--output",
            str(xiniu_collected),
        ]
        results.append(run_json_command("xiniu_collect", collect_cmd, cwd=ROOT))
        if xiniu_collected.exists():
            route_cmd = [
                sys.executable,
                str(SCRIPTS / "route_xiniu_leads.py"),
                "--input",
                str(xiniu_collected),
                "--article-output",
                str(xiniu_articles),
            ]
            results.append(run_json_command("route_xiniu_leads", route_cmd, cwd=ROOT))
            add_article_rows(load_jsonl(xiniu_articles))
        else:
            results.append(StepResult(name="route_xiniu_leads", status="ERROR", error="missing xiniu_collected.jsonl"))

    if args.run_xhs:
        sample_path = Path(args.xhs_raw_input) if args.xhs_raw_input else ARTICLE_SAMPLES / "xhs" / "xhs_note_raw_real_01.jsonl"
        if sample_path.exists():
            step_results, new_articles, new_stories, decision = collect_xhs_sample(output_root, sample_path)
            results.extend(step_results)
            add_article_rows(new_articles)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("xhs_note", "article_story_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_netease_renjian:
        sample_path = Path(args.netease_renjian_sample_html) if args.netease_renjian_sample_html else STORY_SAMPLES / "netease-renjian" / "renjian_story_sample_01.html"
        if sample_path.exists():
            step_results, new_stories, decision = collect_netease_renjian_sample(output_root, sample_path)
            results.extend(step_results)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("netease_renjian", "story_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_zhihu:
        mediacrawler_input = Path(args.zhihu_mediacrawler_input) if args.zhihu_mediacrawler_input else None
        if mediacrawler_input and mediacrawler_input.exists():
            step_results, new_articles, new_stories, decision = collect_zhihu_mediacrawler_sample(output_root, mediacrawler_input)
            results.extend(step_results)
            add_article_rows(new_articles)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            sample_path = Path(args.zhihu_sample_html) if args.zhihu_sample_html else ARTICLE_SAMPLES / "zhihu" / "zhihu_story_sample_02.html"
            if sample_path.exists():
                step_results, new_articles, new_stories, decision = collect_zhihu_sample(output_root, sample_path)
                results.extend(step_results)
                add_article_rows(new_articles)
                add_story_rows(new_stories)
                decisions.append(decision)
            else:
                missing = str(mediacrawler_input) if mediacrawler_input else str(sample_path)
                decisions.append(SourceDecision("zhihu", "article_story_vault", "SKIPPED", f"缺少样本：{missing}", []))

    if args.run_tieba:
        sample_path = Path(args.tieba_mediacrawler_input) if args.tieba_mediacrawler_input else ROOT / "scripts" / "tieba_mediacrawler_content_sample.jsonl"
        if sample_path.exists():
            step_results, new_articles, new_stories, decision = collect_tieba_mediacrawler_sample(output_root, sample_path)
            results.extend(step_results)
            add_article_rows(new_articles)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("tieba", "article_story_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_douban:
        sample_path = Path(args.douban_sample_html) if args.douban_sample_html else ARTICLE_SAMPLES / "douban" / "douban_review_sample_01.html"
        if sample_path.exists():
            step_results, new_articles, new_stories, decision = collect_douban_sample(output_root, sample_path)
            results.extend(step_results)
            add_article_rows(new_articles)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("douban", "article_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_douban_group:
        sample_path = Path(args.douban_group_sample_html) if args.douban_group_sample_html else STORY_SAMPLES / "douban" / "douban_group_story_sample_01.html"
        if args.douban_group_topic_url or sample_path.exists():
            step_results, new_articles, new_stories, decision = collect_douban_group_topic(
                output_root,
                args.douban_group_topic_url,
                sample_path if sample_path.exists() else None,
                args.douban_group_cookie,
                args.douban_group_browser,
            )
            results.extend(step_results)
            add_article_rows(new_articles)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("douban_group", "article_story_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_toutiao:
        sample_path = Path(args.toutiao_sample_html) if args.toutiao_sample_html else ARTICLE_SAMPLES / "toutiao" / "toutiao_story_sample_01.html"
        if sample_path.exists():
            step_results, new_articles, new_stories, decision = collect_toutiao_sample(output_root, sample_path)
            results.extend(step_results)
            add_article_rows(new_articles)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("toutiao", "article_story_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_reddit:
        sample_path = Path(args.reddit_sample_json) if args.reddit_sample_json else STORY_SAMPLES / "reddit" / "reddit_story_sample_01.json"
        if sample_path.exists():
            step_results, new_stories, decision = collect_reddit_sample(output_root, sample_path)
            results.extend(step_results)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("reddit", "story_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_wechat:
        sample_path = Path(args.wechat_sample_html) if args.wechat_sample_html else ARTICLE_SAMPLES / "wechat" / "wechat_story_sample_01.html"
        if sample_path.exists():
            step_results, new_articles, new_stories, decision = collect_wechat_sample(output_root, sample_path)
            results.extend(step_results)
            add_article_rows(new_articles)
            add_story_rows(new_stories)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("wechat", "article_story_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    dailyhot_article_rows: list[dict[str, Any]] = []
    dailyhot_output = output_root / "tmp" / "dailyhot"
    if args.lane == "video":
        decisions.append(SourceDecision("dailyhot_article", "article_vault", "SKIPPED", "video lane 不运行 article DailyHot 注入", []))
    elif getattr(args, "dailyhot_article", None):
        dailyhot_input = Path(args.dailyhot_article)
        if dailyhot_input.exists():
            raw_dailyhot_rows = load_jsonl(dailyhot_input)
            for item in raw_dailyhot_rows:
                if not isinstance(item, dict):
                    continue
                row: dict[str, Any] = {
                    "source": "dailyhot",
                    "source_name": str(item.get("source_name") or item.get("source") or "dailyhot"),
                    "vault": "article_vault",
                    "title": str((item.get("title") or item.get("name") or "")[:200]),
                    "summary": str(item.get("summary") or item.get("desc") or ""),
                    "url": str(item.get("url") or ""),
                    "publish_time": str(item.get("publish_time") or args.date),
                    "content_type": "article",
                    "content": str(item.get("summary") or item.get("desc") or item.get("content") or ""),
                    "raw_score": 55,
                    "production_score": 55,
                    "hotboard_source": str(item.get("hotboard_source") or item.get("source") or "dailyhot"),
                    "board": str(item.get("source") or "dailyhot"),
                    "rank": item.get("rank"),
                    "hot_score": item.get("hot_score", 0),
                }
                dailyhot_article_rows.append(row)
            if dailyhot_article_rows:
                add_article_rows(dailyhot_article_rows)
                decisions.append(SourceDecision("dailyhot_article", "article_vault", "CONNECTED", f"DailyHot JSONL 注入 {len(dailyhot_article_rows)} 条候选", [str(dailyhot_input)]))
            else:
                decisions.append(SourceDecision("dailyhot_article", "article_vault", "SKIPPED", "DailyHot JSONL 无文娱候选", [str(dailyhot_input)]))
        else:
            decisions.append(SourceDecision("dailyhot_article", "dailyhot", "ERROR", f"DailyHot 输入文件不存在：{dailyhot_input}", []))
    else:
        inject_cmd = [
            sys.executable,
            str(SCRIPTS / "dailyhot_inject.py"),
            "--output-dir",
            str(dailyhot_output),
            "--date",
            args.date,
        ]
        inject_result = run_json_command("dailyhot_inject", inject_cmd)
        if inject_result.status != "OK":
            decisions.append(SourceDecision("dailyhot_article", "dailyhot", "ERROR", f"DailyHot 适配失败：{inject_result.error or 'unknown error'}", []))
        else:
            detail = inject_result.detail or {}
            output_path = Path(str(detail.get("output") or dailyhot_output / f"dailyhot_{args.date}.jsonl"))
            raw_dailyhot_rows = load_jsonl(output_path)
            for item in raw_dailyhot_rows:
                if not isinstance(item, dict):
                    continue
                row: dict[str, Any] = {
                    "source": "dailyhot",
                    "source_name": str(item.get("source_name") or item.get("source") or "dailyhot"),
                    "vault": "article_vault",
                    "title": str((item.get("title") or item.get("name") or "")[:200]),
                    "summary": str(item.get("summary") or item.get("desc") or ""),
                    "url": str(item.get("url") or ""),
                    "publish_time": str(item.get("publish_time") or args.date),
                    "content_type": "article",
                    "content": str(item.get("summary") or item.get("desc") or item.get("content") or ""),
                    "raw_score": 55,
                    "production_score": 55,
                    "hotboard_source": str(item.get("hotboard_source") or item.get("source") or "dailyhot"),
                    "board": str(item.get("source") or "dailyhot"),
                    "rank": item.get("rank"),
                    "hot_score": item.get("hot_score", 0),
                }
                dailyhot_article_rows.append(row)
            if dailyhot_article_rows:
                add_article_rows(dailyhot_article_rows)
                decisions.append(SourceDecision("dailyhot_article", "article_vault", "CONNECTED", f"DailyHot 自动注入 {len(dailyhot_article_rows)} 条候选", [str(output_path)]))
            else:
                decisions.append(SourceDecision("dailyhot_article", "article_vault", "SKIPPED", "DailyHot 无文娱候选", [str(output_path)]))


    if args.run_hotboard:
        sample_path = Path(args.hotboard_sample_json) if args.hotboard_sample_json else HOTBOARD_SAMPLES / "hotlist_web_sample_01.json"
        if sample_path.exists():
            step_results, rows, decision = collect_hotboard_sample(output_root, sample_path)
            results.extend(step_results)
            add_emotion_rows(rows)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("hotboard_hotlist_web", "hotboard", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_tophub:
        step_results, rows, decision = collect_tophub_live(output_root)
        results.extend(step_results)
        add_emotion_rows(rows)
        decisions.append(decision)

    if args.run_tophub_bilibili_live:
        step_results, rows, decision = collect_tophub_bilibili_live(output_root)
        results.extend(step_results)
        add_media_rows(rows)
        decisions.append(decision)
        media_output = output_root / "media-leads" / "tophub_bilibili_live.jsonl"
        story_results, new_stories, story_decision = collect_media_story_routes(output_root, "bilibili_live", media_output)
        results.extend(story_results)
        add_story_rows(new_stories)
        decisions.append(story_decision)
        story_path = output_root / "story-leads" / "bilibili_live_story_leads.jsonl"
        pool_results, pool_decision = classify_story_pool(output_root, "bilibili_live", story_path)
        results.extend(pool_results)
        decisions.append(pool_decision)

    if args.run_media_bilibili:
        default_real_path = ROOT / "tmp" / "mediacrawler" / "bilibili" / "raw" / "bilibili_content_raw_real_latest.jsonl"
        fallback_sample_path = MEDIA_SAMPLES / "bilibili" / "bilibili_content_raw_real_01.jsonl"
        sample_path = Path(args.media_bilibili_input) if args.media_bilibili_input else (default_real_path if default_real_path.exists() else fallback_sample_path)
        if sample_path.exists():
            step_results, rows, decision = collect_media_sample(output_root, "bilibili", "mediacrawler_bilibili_content_normalize.py", sample_path)
            results.extend(step_results)
            add_media_rows(rows)
            decisions.append(decision)
            media_output = output_root / "media-leads" / "bilibili_media.jsonl"
            story_results, new_stories, story_decision = collect_media_story_routes(output_root, "bilibili", media_output)
            results.extend(story_results)
            add_story_rows(new_stories)
            decisions.append(story_decision)
            story_path = output_root / "story-leads" / "bilibili_story_leads.jsonl"
            pool_results, pool_decision = classify_story_pool(output_root, "bilibili", story_path)
            results.extend(pool_results)
            decisions.append(pool_decision)
        else:
            decisions.append(SourceDecision("bilibili", "media_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_media_douyin:
        sample_path = Path(args.media_douyin_input) if args.media_douyin_input else MEDIA_SAMPLES / "douyin" / "douyin_content_raw_real_01.jsonl"
        if sample_path.exists():
            step_results, rows, decision = collect_media_sample(output_root, "douyin", "mediacrawler_douyin_content_normalize.py", sample_path)
            results.extend(step_results)
            add_media_rows(rows)
            decisions.append(decision)
            media_output = output_root / "media-leads" / "douyin_media.jsonl"
            story_results, new_stories, story_decision = collect_media_story_routes(output_root, "douyin", media_output)
            results.extend(story_results)
            add_story_rows(new_stories)
            decisions.append(story_decision)
            story_path = output_root / "story-leads" / "douyin_story_leads.jsonl"
            pool_results, pool_decision = classify_story_pool(output_root, "douyin", story_path)
            results.extend(pool_results)
            decisions.append(pool_decision)
        else:
            decisions.append(SourceDecision("douyin", "media_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_media_weibo:
        sample_path = Path(args.media_weibo_input) if args.media_weibo_input else MEDIA_SAMPLES / "weibo" / "weibo_content_raw_sample_01.jsonl"
        if sample_path.exists():
            step_results, rows, decision = collect_media_sample(output_root, "weibo", "mediacrawler_weibo_content_normalize.py", sample_path)
            results.extend(step_results)
            add_media_rows(rows)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("weibo", "media_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    if args.run_media_kuaishou:
        sample_path = Path(args.media_kuaishou_input) if args.media_kuaishou_input else MEDIA_SAMPLES / "kuaishou" / "kuaishou_content_raw_sample_01.jsonl"
        if sample_path.exists():
            step_results, rows, decision = collect_media_sample(output_root, "kuaishou", "mediacrawler_kuaishou_content_normalize.py", sample_path)
            results.extend(step_results)
            add_media_rows(rows)
            decisions.append(decision)
        else:
            decisions.append(SourceDecision("kuaishou", "media_vault", "SKIPPED", f"缺少样本：{sample_path}", []))

    skip_candidates: list[tuple[str, str]] = []
    for name, reason in skip_candidates:
        decisions.append(SourceDecision(name, "deferred", "SKIPPED", reason, []))

    raw_article_count = len(article_rows)
    article_rows = [row for row in article_rows if not article_row_is_noise(row)]
    filtered_article_noise = raw_article_count - len(article_rows)
    article_rows = [enrich_article_row_for_scoring(row, date) for row in article_rows]
    article_rows, dropped_articles = dedupe_rows(article_rows, article_daily_score)
    story_rows, dropped_stories = dedupe_rows(story_rows, lambda row: 80 if str(row.get("story_kind") or "") == "complete_story" else 70)
    media_rows, dropped_media = dedupe_rows(media_rows, media_editorial_score)

    recent_hits = recent_topic_hits(days=3, current_date=date)
    cross_day_policy = args.cross_day_policy
    cross_day_penalty = max(0, args.cross_day_penalty)
    cross_day_blocked = {"article": 0, "story": 0, "media": 0}

    if cross_day_policy == "hint":
        cross_day_hits = {
            "article": sum(1 for row in article_rows if row_topic_key(row) in recent_hits),
            "story": sum(1 for row in story_rows if row_topic_key(row) in recent_hits),
            "media": sum(1 for row in media_rows if row_topic_key(row) in recent_hits),
        }
    else:
        article_rows, article_hit_count, article_blocked_count = apply_cross_day_policy(
            article_rows,
            recent_hits,
            mode=cross_day_policy,
            penalty=cross_day_penalty,
            score_getter=article_daily_score,
        )
        story_rows, story_hit_count, story_blocked_count = apply_cross_day_policy(
            story_rows,
            recent_hits,
            mode=cross_day_policy,
            penalty=cross_day_penalty,
            score_getter=lambda row: 80 if str(row.get("story_kind") or "") == "complete_story" else 70,
        )
        media_rows, media_hit_count, media_blocked_count = apply_cross_day_policy(
            media_rows,
            recent_hits,
            mode=cross_day_policy,
            penalty=cross_day_penalty,
            score_getter=media_editorial_score,
        )
        cross_day_hits = {
            "article": article_hit_count,
            "story": story_hit_count,
            "media": media_hit_count,
        }
        cross_day_blocked = {
            "article": article_blocked_count,
            "story": story_blocked_count,
            "media": media_blocked_count,
        }

    if filtered_article_noise:
        results.append({
            "step": "article_noise_filter",
            "status": "PASS",
            "filtered": filtered_article_noise,
            "message": f"过滤 article 噪音 {filtered_article_noise} 条（story/公告/签到/广告）",
        })

    dedupe_summary = dedupe_summary_text(
        {"article": dropped_articles, "story": dropped_stories, "media": dropped_media},
        cross_day_hits,
    )

    def refetch_article_rows(retry_request: dict[str, Any]) -> list[dict[str, Any]]:
        flags = set(retry_request.get("runnable_flags") or [])
        refetched_article_rows: list[dict[str, Any]] = []
        if "xhs" in flags and not args.run_xhs:
            sample_path = Path(args.xhs_raw_input) if args.xhs_raw_input else ARTICLE_SAMPLES / "xhs" / "xhs_note_raw_real_01.jsonl"
            if sample_path.exists():
                step_results, new_articles, new_stories, decision = collect_xhs_sample(output_root, sample_path)
                results.extend(step_results)
                add_story_rows(new_stories)
                decisions.append(decision)
                refetched_article_rows.extend(new_articles)
        if "zhihu" in flags and not args.run_zhihu:
            sample_path = Path(args.zhihu_sample_html) if args.zhihu_sample_html else ARTICLE_SAMPLES / "zhihu" / "zhihu_story_sample_02.html"
            if sample_path.exists():
                step_results, new_articles, new_stories, decision = collect_zhihu_sample(output_root, sample_path)
                results.extend(step_results)
                add_story_rows(new_stories)
                decisions.append(decision)
                refetched_article_rows.extend(new_articles)
        if "douban_group" in flags and not args.run_douban_group:
            sample_path = Path(args.douban_group_sample_html) if args.douban_group_sample_html else STORY_SAMPLES / "douban" / "douban_group_story_sample_01.html"
            if args.douban_group_topic_url or sample_path.exists():
                step_results, new_articles, new_stories, decision = collect_douban_group_topic(
                    output_root,
                    args.douban_group_topic_url,
                    sample_path if sample_path.exists() else None,
                    args.douban_group_cookie,
                    args.douban_group_browser,
                )
                results.extend(step_results)
                add_story_rows(new_stories)
                decisions.append(decision)
                refetched_article_rows.extend(new_articles)
        if "wechat" in flags and not args.run_wechat:
            sample_path = Path(args.wechat_sample_html) if args.wechat_sample_html else ARTICLE_SAMPLES / "wechat" / "wechat_story_sample_01.html"
            if sample_path.exists():
                step_results, new_articles, new_stories, decision = collect_wechat_sample(output_root, sample_path)
                results.extend(step_results)
                add_story_rows(new_stories)
                decisions.append(decision)
                refetched_article_rows.extend(new_articles)
        return refetched_article_rows

    retry_loop = run_article_retry_loop(article_rows, story_rows, media_rows, date, refetch_article_rows, lane=args.lane)
    retry_refetched_count = int(retry_loop["refetched_count"])
    if retry_refetched_count:
        article_rows = [enrich_article_row_for_scoring(row, date) for row in retry_loop["article_rows"]]
        article_rows, retry_dropped_articles = dedupe_rows(article_rows, article_daily_score)
        if retry_dropped_articles:
            dedupe_summary = dedupe_summary_text(
                {"article": dropped_articles + retry_dropped_articles, "story": dropped_stories, "media": dropped_media},
                cross_day_hits,
            )
        retry_loop = run_article_retry_loop(article_rows, story_rows, media_rows, date, lambda _request: [], lane=args.lane)
        retry_loop["refetched_count"] = retry_refetched_count
    retry_request = retry_loop["retry_request"]
    needs_retry = bool(retry_request["retry_required"])
    retry_targets = list(retry_request["targets"])
    retry_reason = str(retry_request["reason"])

    director_review = output_root / "director-review.md"
    feedback = output_root / "latest-feedback.md"
    article_approved = output_root / "article-approved-latest.md"
    video_approved = output_root / "video-approved-latest.md"
    today_hook_dispatch = output_root / "today-hook-dispatch.md"
    today_hook_dispatch_jsonl = output_root / "today-hook-dispatch.jsonl"
    today_hook_dispatch_md, today_hook_export_rows = build_today_hook_dispatch(date, article_rows, story_rows + emotion_rows)
    write_markdown(today_hook_dispatch, today_hook_dispatch_md)
    write_jsonl(today_hook_dispatch_jsonl, today_hook_export_rows)
    results.append(run_zhihu_question_backfill(output_root))
    today_hook_dispatch_md, today_hook_export_rows = build_today_hook_dispatch(date, article_rows, story_rows + emotion_rows)
    write_markdown(today_hook_dispatch, today_hook_dispatch_md)
    write_jsonl(today_hook_dispatch_jsonl, today_hook_export_rows)
    write_markdown(director_review, build_director_review(date, article_rows, video_rows, story_rows, media_rows, results, decisions))
    write_markdown(feedback, build_feedback(date, article_rows, video_rows, story_rows, media_rows, decisions, needs_retry, retry_targets, retry_reason, dedupe_summary, cross_day_hits))
    write_markdown(article_approved, build_article_approved(date, article_rows))
    if args.lane != "article":
        write_markdown(video_approved, build_video_approved(date, video_rows, media_rows, story_rows))

    reference_candidate_export = output_root / "reference-candidate-export.jsonl"
    write_jsonl(reference_candidate_export, build_reference_export_rows(date, article_rows, video_rows, story_rows, media_rows))

    QUALITY.mkdir(parents=True, exist_ok=True)
    if args.lane == "all":
        copy_latest(director_review, QUALITY / "director-review-latest.md")
        copy_latest(director_review, QUALITY / "nas-director-model-review-latest.md")
        copy_latest(feedback, QUALITY / "latest-feedback.md")
        copy_latest(feedback, QUALITY / "feedback-latest.md")
        copy_latest(article_approved, QUALITY / "article-approved-latest.md")
        copy_latest(video_approved, QUALITY / "video-approved-latest.md")
        copy_latest(today_hook_dispatch, QUALITY / "today-hook-dispatch-latest.md")
    else:
        copy_latest(director_review, QUALITY / f"{args.lane}-director-review-latest.md")
        copy_latest(feedback, QUALITY / f"{args.lane}-latest-feedback.md")
        if args.lane == "article":
            copy_latest(article_approved, QUALITY / "article-lane-approved-latest.md")
            copy_latest(today_hook_dispatch, QUALITY / "article-lane-today-hook-dispatch-latest.md")
        elif args.lane == "video":
            copy_latest(video_approved, QUALITY / "video-lane-approved-latest.md")

    summary = {
        "status": "OK",
        "date": date,
        "lane": args.lane,
        "output_root": str(output_root),
        "article_count": len(article_rows),
        "video_count": len(video_rows),
        "story_count": len(story_rows),
        "media_count": len(media_rows),
        "needs_retry": needs_retry,
        "retry_targets": retry_targets,
        "retry_reason": retry_reason,
        "retry_request": retry_request,
        "retry_refetched_count": retry_loop["refetched_count"],
        "dedupe_summary": dedupe_summary,
        "cross_day_policy": cross_day_policy,
        "cross_day_penalty": cross_day_penalty,
        "cross_day_hits": cross_day_hits,
        "cross_day_blocked": cross_day_blocked,
        "source_decisions": [
            {
                "name": decision.name,
                "category": decision.category,
                "status": decision.status,
                "reason": decision.reason,
                "outputs": decision.outputs,
            }
            for decision in decisions
        ],
        "steps": [
            {
                "name": result.get("step", getattr(result, "name", "unknown")) if isinstance(result, dict) else getattr(result, "name", "unknown"),
                "status": result.get("status", getattr(result, "status", "UNKNOWN")) if isinstance(result, dict) else getattr(result, "status", "UNKNOWN"),
                "error": result.get("error", getattr(result, "error", "")) if isinstance(result, dict) else getattr(result, "error", ""),
            }
            for result in results
        ],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
