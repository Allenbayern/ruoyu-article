#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path

def extract(pattern, text, default=''):
    m=re.search(pattern, text, re.S|re.I)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else default

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sample-html', required=True)
    p.add_argument('--output', required=True)
    a=p.parse_args()
    html=Path(a.sample_html).read_text(encoding='utf-8', errors='ignore')
    title=extract(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)', html) or extract(r'<title>\s*(.*?)\s*</title>', html)
    desc=extract(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)', html) or extract(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)', html)
    url=extract(r'<meta\s+property=["\']og:url["\']\s+content=["\']([^"\']+)', html)
    row={'source':'douban','url':url,'title':title,'summary':desc,'content':desc,'content_type':'article','sample_evidence':'local_html_meta'}
    out=Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status':'OK','output':str(out)}, ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
