import json, subprocess, sys
def test_cli_init_record_verify(tmp_path):
 root=tmp_path/"run"; root.mkdir(); inp=tmp_path/"m.json"
 inp.write_text(json.dumps({"schema_version":"article-group-controller-v1","run_id":"r","batch_id":"b","articles":[{"topic_id":"t"}],"publication_authorization":"not_authorized"}))
 out=root/"controller-manifest.json"
 assert subprocess.run([sys.executable,"scripts/article_group_controller.py","init","--run-dir",str(root),"--input",str(inp),"--output",str(out)]).returncode==0
 d=tmp_path/"d.json"; d.write_text(json.dumps({"schema_version":"controller-stage-decision-v1","topic_id":"t","from_state":"idea","to_state":"precheck","decision":"pass","decided_at":"x"}))
 assert subprocess.run([sys.executable,"scripts/article_group_controller.py","record","--run-dir",str(root),"--input",str(d)]).returncode==0
 assert subprocess.run([sys.executable,"scripts/article_group_controller.py","verify","--run-dir",str(root)]).returncode==1
