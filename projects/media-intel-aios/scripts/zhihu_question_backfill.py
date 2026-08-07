#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--dispatch', required=True)
    p.add_argument('--output', required=True)
    a=p.parse_args()
    dispatch=Path(a.dispatch)
    out=Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    rows=[]
    if dispatch.exists():
        for line in dispatch.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            try:
                item=json.loads(line)
            except json.JSONDecodeError:
                continue
            url=str(item.get('url') or '')
            if 'zhihu.com/question/' in url:
                rows.append({'source':'zhihu_question_backfill','url':url,'status':'queued','title':item.get('title','')})
    out.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    print(json.dumps({'status':'OK','count':len(rows),'output':str(out)}, ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
