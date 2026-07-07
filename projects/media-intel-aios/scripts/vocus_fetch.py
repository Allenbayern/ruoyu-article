#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sample-json', required=True)
    p.add_argument('--output', required=True)
    a=p.parse_args()
    src=Path(a.sample_json); out=Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    data=json.loads(src.read_text(encoding='utf-8'))
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status':'OK','output':str(out)}, ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
