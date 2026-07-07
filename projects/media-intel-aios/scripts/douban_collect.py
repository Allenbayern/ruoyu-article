#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--article-output', required=True)
    p.add_argument('--story-output', required=True)
    a=p.parse_args()
    data=json.loads(Path(a.input).read_text(encoding='utf-8'))
    article={
        'source':'douban','source_name':'douban','vault':'article_vault',
        'title':data.get('title',''), 'summary':data.get('summary') or data.get('content',''), 'content':data.get('content') or data.get('summary',''),
        'url':data.get('url',''), 'content_type':'article','raw_score':68,'production_score':68,
        'sample_evidence':data.get('sample_evidence','local_sample')
    }
    ao=Path(a.article_output); so=Path(a.story_output)
    ao.parent.mkdir(parents=True, exist_ok=True); so.parent.mkdir(parents=True, exist_ok=True)
    ao.write_text(json.dumps(article, ensure_ascii=False)+'\n', encoding='utf-8')
    so.write_text('', encoding='utf-8')
    print(json.dumps({'status':'OK','article_count':1,'story_count':0,'article_output':str(ao),'story_output':str(so)}, ensure_ascii=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
