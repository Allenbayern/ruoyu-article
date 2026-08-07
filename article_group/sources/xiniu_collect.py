#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sample-html', required=True)
    p.add_argument('--output', required=True)
    a=p.parse_args()
    html=Path(a.sample_html).read_text(encoding='utf-8', errors='ignore')
    title=(re.search(r'<title>\s*(.*?)\s*</title>', html, re.S|re.I) or [None, Path(a.sample_html).stem])[1]
    row={'source':'xiniu-yule','source_name':'xiniu-yule','title':re.sub(r'\s+',' ',title).strip(),'summary':'本地样本缺省抽取','content_type':'article','url':''}
    out=Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps({'status':'OK','count':1,'output':str(out)}, ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
