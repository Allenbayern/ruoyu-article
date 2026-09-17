#!/usr/bin/env python3
"""Safely purge source-video quarantine directories after confirming compressed copies exist.

Usage (run on VM101 host, or locally with paths adjusted):
    python3 purge_quarantine.py --list                  # show quarantine runs
    python3 purge_quarantine.py --dry-run <run_id>      # what would be freed (default)
    python3 purge_quarantine.py --purge <run_id>        # actually delete (requires --yes)

Safety rules:
- Every source in the quarantine ledger must have a verified compressed copy
  in Compressed-Videos/ (sha256[:16]__stem.mp4, ffprobe duration > 0).
- Failed / unlisted videos are never touched (they stay in MobileBackup).
- Purge uses os.remove per file (recoverable only via NAS recycle bin if enabled);
  --yes is required to bypass the dry-run confirmation.
- **含 SEALED 的目录一律拒删**（2026-09-17 加）：本工具是破坏性工具，若被指向一个
  封存 run（含 `SEALED` 标记），必须先由 controller 明确点头并加 `--allow-sealed`
  与 `--ref <谁批准的>`；授权内容会写进幸存的 `PURGED.txt`，因为 run 内的账目
  会连同文件一起被删掉。
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path('/vol2/1000/Video-Optimized')
QUARANTINE = BASE / '_source-video-quarantine'
OUT = BASE / 'Compressed-Videos'
SRC = Path('/vol2/1000/Photos/MobileBackup')
SEALED_NAME = 'SEALED'


def sealed_markers(run_dir: Path) -> list[Path]:
    """目录里的封存标记（`SEALED` 及其生命周期兄弟，如 SEALED.revoked.*）。"""
    if not run_dir.is_dir():
        return []
    return sorted(
        path for path in run_dir.iterdir()
        if path.name == SEALED_NAME or path.name.startswith(SEALED_NAME + '.')
        if path.is_file()
    )


def output_path_for(src_rel: str) -> Path:
    h = hashlib.sha256(src_rel.encode('utf-8')).hexdigest()[:16]
    stem = Path(src_rel).stem
    return OUT / f'{h}__{stem}.mp4'


def list_runs():
    if not QUARANTINE.is_dir():
        print('no quarantine dir')
        return
    for d in sorted(QUARANTINE.iterdir()):
        if not d.is_dir():
            continue
        summary = d / 'summary.json'
        ledger = d / 'movement-ledger.jsonl'
        n = 0
        if ledger.is_file():
            n = sum(1 for _ in ledger.open(encoding='utf-8'))
        info = ''
        if summary.is_file():
            try:
                s = json.loads(summary.read_text(encoding='utf-8'))
                info = f" moved={s.get('moved_count')} gib={s.get('total_source_gib')}"
            except Exception:
                pass
        print(f'{d.name}  ledger_rows={n}{info}')


def check_compressed_copies(ledger_path: Path) -> tuple[int, int, list[str]]:
    """Return (ok, missing, problems). Verifies each ledger entry's compressed copy exists+readable."""
    ok = missing = 0
    problems = []
    with ledger_path.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                problems.append(f'bad ledger line: {line[:80]}')
                continue
            src = rec.get('source', '')
            # derive relative path from source (absolute on NAS)
            try:
                rel = str(Path(src).relative_to(SRC))
            except ValueError:
                rel = src
            out = output_path_for(rel)
            if not out.is_file():
                missing += 1
                problems.append(f'MISSING OUTPUT: {out} (for {src})')
                continue
            try:
                r = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'default=noprint_wrappers=1:nokey=1', str(out)],
                    capture_output=True, text=True, timeout=8)
                if r.returncode != 0 or float(r.stdout.strip() or '0') <= 0:
                    missing += 1
                    problems.append(f'UNREADABLE OUTPUT: {out}')
                    continue
            except Exception as e:
                missing += 1
                problems.append(f'FFPROBE ERROR: {out} {e}')
                continue
            ok += 1
    return ok, missing, problems


def dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob('*'):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def purge_run(run_id: str, dry_run: bool, *, allow_sealed: bool = False, ref: str = ''):
    run_dir = QUARANTINE / run_id
    ledger = run_dir / 'movement-ledger.jsonl'
    if not run_dir.is_dir():
        print(f'ERROR: no such quarantine run: {run_id}')
        sys.exit(1)
    if not ledger.is_file():
        print(f'ERROR: no movement-ledger.jsonl in {run_dir}')
        sys.exit(1)

    markers = sealed_markers(run_dir)
    if markers and not allow_sealed:
        names = ', '.join(marker.name for marker in markers)
        print(f'REFUSED: {run_dir} 含封存标记（{names}）——这是封存证据，不是可清理的隔离区。')
        print('  确需销毁请由 controller 明确点头，再运行：'
              f'--purge {run_id} --yes --allow-sealed --ref "<谁批准的>"')
        sys.exit(3)
    sealed_digests = {
        marker.name: hashlib.sha256(marker.read_bytes()).hexdigest() for marker in markers
    }

    ok, missing, problems = check_compressed_copies(ledger)
    print(f'compressed copies verified: {ok} ok, {missing} missing/unreadable')
    for p in problems[:20]:
        print(f'  - {p}')
    if problems:
        print(f'  ... and {len(problems) - min(len(problems), 20)} more' if len(problems) > 20 else '')
    if missing > 0:
        print('ABORT: missing compressed copies - not purging anything')
        sys.exit(2)

    size = dir_size(run_dir)
    print(f'run {run_id}: would free {size / 1024**3:.2f} GiB ({size:,} bytes)')
    if markers:
        print(f'  WARNING: 本次将销毁封存标记 {list(sealed_digests)}；授权与哈希写入 PURGED.txt')
    if dry_run:
        print('DRY-RUN: no files deleted. Re-run with --purge <run_id> --yes to actually purge.')
        return

    # actual purge: remove sources/, then ledger+summary (keep run dir with a marker)
    removed = 0
    for p in sorted(run_dir.rglob('*'), reverse=True):
        try:
            if p.is_file():
                p.unlink()
                removed += 1
            elif p.is_dir() and not any(run_dir.iterdir()):
                pass
        except OSError as e:
            print(f'WARN: could not remove {p}: {e}')
    # remove now-empty subdirs
    for p in sorted([d for d in run_dir.rglob('*') if d.is_dir()], key=lambda x: -len(str(x))):
        try:
            if not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass
    lines = [
        f'purged {removed} source files on {datetime.datetime.now().isoformat()}',
    ]
    if sealed_digests:
        lines += [
            f'sealed_markers_destroyed: {json.dumps(sealed_digests, ensure_ascii=False, sort_keys=True)}',
            f'sealed_destroy_authorized_by: {ref or "(未填 --ref：仅记录了 --allow-sealed)"}',
        ]
    (run_dir / 'PURGED.txt').write_text('\n'.join(lines) + '\n')
    print(f'PURGED: {removed} files removed; freed {size / 1024**3:.2f} GiB')
    print(f'run dir kept (marker only): {run_dir}')


def main():
    ap = argparse.ArgumentParser(description='Purge quarantine runs safely')
    ap.add_argument('--list', action='store_true', help='list quarantine runs')
    ap.add_argument('--dry-run', action='store_true', help='verify + show size, delete nothing')
    ap.add_argument('--purge', metavar='RUN_ID', help='purge a specific run')
    ap.add_argument('--yes', action='store_true', help='confirm purge (required)')
    ap.add_argument('--allow-sealed', action='store_true',
                    help='目标含 SEALED 时仍销毁（controller 决定；授权写进 PURGED.txt）')
    ap.add_argument('--ref', default='', help='谁批准了销毁封存证据（写入 PURGED.txt）')
    args = ap.parse_args()

    if args.list or not (args.purge):
        list_runs()
        return

    dry = not args.purge or (not args.yes)
    purge_run(args.purge, dry_run=dry, allow_sealed=args.allow_sealed, ref=args.ref)


if __name__ == '__main__':
    main()
