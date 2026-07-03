#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get('MEDIA_INTEL_ROOT', Path(__file__).resolve().parents[1]))
PYTHON = Path(os.environ.get('MEDIA_INTEL_PYTHON', ROOT / '.venv/bin/python'))
ARTIFACT_ROOT = Path(
    os.environ.get(
        'MEDIA_INTEL_ARTIFACT_ROOT',
        Path.home() / '.hermes/artifacts/media-intel/article-manual',
    )
)
CRON_OUTPUT_DIR = Path(
    os.environ.get(
        'MEDIA_INTEL_CRON_OUTPUT_DIR',
        Path.home() / '.hermes/cron/output/859617906460',
    )
)

ARTICLE_FLAGS = [
    '--run-dumou',
    '--run-guduo',
    '--run-vocus',
    '--run-douban',
    '--run-hotboard',
    '--run-tophub',
    '--guduo-date', '2026-06-09',
    '--guduo-offline-dir', str(ROOT / 'samples/guduo'),
    '--vocus-sample-json', str(ROOT / 'article-vault/samples/vocus/vocus_article_sample_01.json'),
    '--douban-sample-html', str(ROOT / 'article-vault/samples/douban/douban_review_sample_01.html'),
    '--hotboard-sample-json', str(ROOT / 'hotboard/samples/hotlist_web_sample_01.json'),
]


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=600,
    )


def parse_json_output(output: str) -> dict:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for start in range(len(lines)):
        candidate = '\n'.join(lines[start:])
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError('No JSON object found in command output')


def main() -> int:
    if not ROOT.exists():
        print(f'ERROR repo missing: {ROOT}')
        return 2
    if not PYTHON.exists():
        print(f'ERROR venv python missing: {PYTHON}')
        return 2

    now = datetime.now()
    date = now.strftime('%F')
    run_id = f'manual-{now.strftime("%Y%m%d-%H%M%S")}'
    run_root = ARTIFACT_ROOT / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    blocking_failures: list[str] = []
    warnings: list[str] = []

    print(f'RUN_DIR={run_root}')
    print(f'CRON_OUTPUT_DIR={CRON_OUTPUT_DIR}')

    try:
        smoke_cmd = [
            str(PYTHON),
            str(ROOT / 'scripts/article_production_live_run.py'),
            '--output-base', str(run_root / 'production-live'),
            '--run-id', run_id,
        ]
        smoke = run(smoke_cmd)
        if smoke.returncode != 0:
            print(smoke.stdout)
            print(f'ERROR production live smoke exited {smoke.returncode}')
            return smoke.returncode or 1
        try:
            smoke_data = parse_json_output(smoke.stdout)
        except Exception as exc:
            print(smoke.stdout)
            print(f'ERROR failed to parse production smoke JSON: {exc}')
            return 1
        verification = smoke_data.get('verification') or {}
        if verification.get('status') != 'PASS':
            blocking_failures.append(f"production_live verification={verification.get('status')}")

        lane_output = run_root / 'article-lane'
        lane_cmd = [
            str(PYTHON),
            str(ROOT / 'scripts/run_daily_pipeline.py'),
            '--lane', 'article',
            '--date', date,
            '--output-root', str(lane_output),
            *ARTICLE_FLAGS,
        ]
        lane = run(lane_cmd)
        print(lane.stdout)
        if lane.returncode != 0:
            print(f'ERROR article lane exited {lane.returncode}')
            return lane.returncode or 1
        try:
            lane_data = parse_json_output(lane.stdout)
        except Exception as exc:
            print(f'ERROR failed to parse article lane JSON: {exc}')
            return 1

        errored_steps = [
            step for step in lane_data.get('steps', [])
            if str(step.get('status', '')).upper() == 'ERROR'
        ]
        if errored_steps:
            names = ', '.join(str(step.get('name')) for step in errored_steps)
            warnings.append(f'article_lane errored_steps={names}')
        if lane_data.get('needs_retry'):
            warnings.append(f"article_lane needs_retry={lane_data.get('retry_reason')}")
        if int(lane_data.get('article_count') or 0) <= 0:
            blocking_failures.append('article_lane article_count=0')

        article_html = Path(str(smoke_data.get('output_dir') or '')) / 'article.html'
        if article_html.exists():
            print(f'ARTICLE_HTML={article_html}')
        else:
            blocking_failures.append(f'production_live article.html missing: {article_html}')

        summary = {
            'date': date,
            'run_id': run_id,
            'run_dir': str(run_root),
            'cron_output_dir': str(CRON_OUTPUT_DIR),
            'article_html': str(article_html),
            'production_live': {
                'status': verification.get('status'),
                'verification_type': verification.get('verification_type'),
                'canonical_suite_green': verification.get('canonical_suite_green'),
                'output_dir': smoke_data.get('output_dir'),
            },
            'article_lane': {
                'status': lane_data.get('status'),
                'output_root': str(lane_output),
                'article_count': lane_data.get('article_count'),
                'needs_retry': lane_data.get('needs_retry'),
                'errored_steps': [step.get('name') for step in errored_steps],
            },
            'warnings': warnings,
            'blocking_failures': blocking_failures,
            'accepted_with_warnings': bool(warnings) and not blocking_failures,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception:
        if not any(run_root.iterdir()):
            run_root.rmdir()
        raise

    return 1 if blocking_failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
