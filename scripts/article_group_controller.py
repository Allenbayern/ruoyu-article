#!/usr/bin/env python3
import argparse, json, hashlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from article_group.controller_v1 import validate_controller_manifest, validate_stage_decision, append_stage_decision

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
 for name in ("init","record","verify"):
  s=sub.add_parser(name); s.add_argument("--run-dir",type=Path,required=True); s.add_argument("--input",type=Path); s.add_argument("--output",type=Path)
 a=p.parse_args(); root=a.run_dir.resolve()
 if not root.is_dir(): return 2
 if a.cmd=="init":
  if not a.input or not a.output: return 2
  m=json.loads(a.input.read_text()); e=validate_controller_manifest(m)
  if e:return print(json.dumps({"status":"FAIL","errors":e})),1
  a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n"); return 0
 if not a.input: return 2
 m=json.loads(a.input.read_text()); manifest_path=root/"controller-manifest.json"
 if not manifest_path.is_file(): return 1
 manifest=json.loads(manifest_path.read_text())
 if a.cmd=="record":
  e=validate_stage_decision(m,manifest)
  if e:return print(json.dumps({"status":"FAIL","errors":e})),1
  append_stage_decision(root/"stage-decisions.jsonl",m); return 0
 e=validate_controller_manifest(manifest); out={"status":"PASS" if not e else "FAIL","errors":e,"manifest_sha256":digest(manifest_path),"publication_authorization":manifest.get("publication_authorization","not_authorized")}
 if a.output: a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps(out,ensure_ascii=False)); return 0 if not e else 1
if __name__=="__main__": raise SystemExit(main())
