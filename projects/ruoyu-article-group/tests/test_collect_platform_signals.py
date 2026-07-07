import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "collect_platform_signals.py"


def load_module():
    spec = importlib.util.spec_from_file_location("collect_platform_signals", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collect_platform_signals_generates_agent_ready_handover_files(tmp_path, monkeypatch):
    source_html = tmp_path / "weibo-hot.html"
    source_html.write_text(
        """
        <html>
          <head><title>暑期档新片口碑反转</title></head>
          <body>主演回应争议，热搜讨论仍在发酵。</body>
        </html>
        """,
        encoding="utf-8",
    )
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "project": "测试文章组",
                "topic_domain": "影视娱乐",
                "publishing_platforms": ["今日头条", "微信公众号"],
                "sources": [
                    {
                        "name": "微博热搜样例",
                        "platform": "weibo",
                        "mode": "public_url",
                        "url": source_html.as_uri(),
                        "cookie_env": "WEIBO_COOKIE",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module = load_module()
    rc = module.main(
        [
            "--workspace",
            str(tmp_path),
            "--config",
            str(config),
            "--date",
            "2026-07-02",
            "--limit",
            "5",
        ]
    )

    assert rc == 0
    quality_dir = tmp_path / "handover-hotspot" / "04-QUALITY-FEEDBACK"
    expected_files = [
        "directive-latest.md",
        "latest-feedback.md",
        "director-review-latest.md",
        "article-approved-latest.md",
    ]
    for name in expected_files:
        assert (quality_dir / name).exists(), name

    feedback = (quality_dir / "latest-feedback.md").read_text(encoding="utf-8")
    approved = (quality_dir / "article-approved-latest.md").read_text(encoding="utf-8")
    directive = (quality_dir / "directive-latest.md").read_text(encoding="utf-8")

    assert "微博热搜样例" in feedback
    assert "暑期档新片口碑反转" in feedback
    assert "主平台：今日头条 / 微信公众号" in directive
    assert "## approved 白名单" in approved
    assert "WEIBO_COOKIE" in directive
    workflow = tmp_path / "handover-hotspot" / "WORKFLOW-RECAST-CONTENT-AND-VIDEO-2026-06-10.md"
    assert workflow.exists()
    workflow_text = workflow.read_text(encoding="utf-8")
    assert "四层状态" in workflow_text
    assert "正式成稿" in feedback
    assert "fake-cookie" not in feedback + approved + directive + workflow_text


def test_secret_like_values_are_redacted_from_outputs(tmp_path, monkeypatch):
    source_html = tmp_path / "zhihu.html"
    source_html.write_text("<title>一部剧为什么能让观众吵起来</title>", encoding="utf-8")
    monkeypatch.setenv("ZHIHU_COOKIE", "fake-cookie-should-not-be-written")
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps(
            {
                "project": "测试文章组",
                "topic_domain": "影视娱乐",
                "sources": [
                    {
                        "name": "知乎热榜样例",
                        "platform": "zhihu",
                        "mode": "public_url",
                        "url": source_html.as_uri(),
                        "cookie_env": "ZHIHU_COOKIE",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module = load_module()
    assert module.main(["--workspace", str(tmp_path), "--config", str(config), "--date", "2026-07-02"]) == 0

    all_output = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "handover-hotspot" / "04-QUALITY-FEEDBACK").glob("*.md")
    )
    assert "fake-cookie-should-not-be-written" not in all_output
    assert "ZHIHU_COOKIE" in all_output
