#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--article-output', required=True)
    a=p.parse_args()
    inp=Path(a.input); out=Path(a.article_output)
    rows=[]
    if inp.exists():
        for line in inp.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                item=json.loads(line)
            except json.JSONDecodeError:
                continue
            item.setdefault('source','xiniu-yule')
            item.setdefault('source_name','xiniu-yule')
            item.setdefault('vault','article_vault')
            item.setdefault('content_type','article')
            item.setdefault('raw_score',60)
            item.setdefault('production_score',60)
            rows.append(item)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    print(json.dumps({'status':'OK','count':len(rows),'article_output':str(out)}, ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
