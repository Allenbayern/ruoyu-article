#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def iter_items(payload):
    if isinstance(payload, dict):
        return payload.get('items') or payload.get('data') or []
    return payload if isinstance(payload, list) else []

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sample-json', required=True)
    p.add_argument('--hotboard-source', default='hotlist_web')
    p.add_argument('--output', required=True)
    a=p.parse_args()
    payload=json.loads(Path(a.sample_json).read_text(encoding='utf-8'))
    rows=[]
    for item in iter_items(payload):
        if not isinstance(item, dict): continue
        rows.append({
            'source':'hotboard','hotboard_source':a.hotboard_source,'source_name':item.get('source') or a.hotboard_source,
            'rank':item.get('rank'),'title':item.get('title') or item.get('name') or '',
            'url':item.get('url') or '', 'hot_score':item.get('hot') or item.get('hot_score') or 0,
            'summary':item.get('summary') or item.get('desc') or '', 'content_type':'dispatch'
        })
    out=Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    print(json.dumps({'status':'OK','count':len(rows),'output':str(out)}, ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
