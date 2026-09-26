"""封存锚点的**覆盖缺口**回归（2026-09-25 第一轮独立复核点名的空白）。

为什么单独一个文件：这些用例要补的三个对象当轮正被第二轮复核用
`round2-frozen.sha256` 钉着，**不能改**（改了复核的哈希核对会失败）。所以新用例集中
放在这里，不改 `tests/test_run_seal.py` / `tests/test_preview_site.py` 一行。

补的是第一轮复核列出的 coverage_gaps：

1. `_replicate_anchor`（约 45 行：clone / pull / commit / push / 各失败分支）在整套测试里
   **从未真实执行**，只有 monkeypatch —— 这里用一个真的本地裸仓库当离机账本跑通。
2. **生产锚点库"保持为空"没有自动化断言**：fixture 隔离是防"写进默认库"的唯一机制，
   却只靠一次性人工计数。这里把它钉住，专门防"读走 env、写走常量"这种对称 bug。
3. v1 清单的 `MAY_BE_ABSENT` / `append_only` / `sealed_marker_sha256` / 新增文件
   没有回归测试；`--check-remote` 的 `remote_missing` 退出码映射也没有。
4. `publish()` 的 `ignore` 只测了顶层：要钉住"嵌套同名文件仍照发"（否则将来把回调写成
   全层级排除会静默丢文件）。
5. `render` 的封存拒绝没有独立用例。
6. 非 UTF-8 路径 × 锚点的**交互**：此前只断言状态落在集合里，这里钉住"锚点确实写成、
   且摘要比对跨代理字符仍成立"（即 F5 的修复真的生效）。
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from article_group import preview_site, run_seal, runs_guard
from article_group.run_state import seal, seal_articles
from tests.test_preview_site import _make_run as _make_preview_run
from tests.test_preview_site import build as build_preview
from tests.test_preview_site import publish as publish_preview
from tests.test_run_seal import _v1_sealed_run

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── ① `_replicate_anchor` 的真实路径：拿一个真的本地裸仓库当离机账本 ──────────────


def _bare_ledger(tmp_path: Path) -> Path:
    remote = tmp_path / "seal-ledger.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)],
                   check=True, capture_output=True)
    return remote


def _sealed_run(tmp_path: Path, name: str = "daily-970") -> Path:
    root = tmp_path / name
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 正文\n", encoding="utf-8")
    (root / "batch.json").write_text(json.dumps({"articles": [{"article_id": "art-001"}]}), encoding="utf-8")
    seal(root, identity="owner")
    return root


def test_anchor_is_actually_pushed_to_a_real_offhost_ledger(tmp_path: Path, monkeypatch) -> None:
    """`_replicate_anchor` 的 clone→add→commit→push 真跑一遍，并回读离机副本。"""
    remote = _bare_ledger(tmp_path)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))
    root = _sealed_run(tmp_path)

    block = run_seal.load_manifest(root)["anchor"]
    assert block["status"] == "anchored", block
    assert block["replication"] == "pushed", block
    assert block["kind"] == "offhost-snapshot", block

    name = run_seal.anchor_file_for(root).name
    shown = subprocess.run(["git", "-C", str(remote), "show", f"main:anchors/{name}"],
                           capture_output=True, text=True, check=True)
    pushed = json.loads(shown.stdout)
    assert pushed["manifest_digest"] == block["manifest_digest"]
    # 本机那份也已被回写成真实结果（不是永远 pending）
    local = json.loads(run_seal.anchor_file_for(root).read_text(encoding="utf-8"))
    assert local["replication"] == "pushed", local


def test_a_second_seal_reuses_the_existing_clone_and_pushes_again(tmp_path: Path, monkeypatch) -> None:
    """第二次封存走 `git pull --ff-only` 那一支（不是每次重新 clone）。"""
    from article_group.run_state import unseal

    remote = _bare_ledger(tmp_path)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))
    root = _sealed_run(tmp_path, name="daily-971")

    unseal(root, reason="测试：改完再封一次", identity="owner")
    seal(root, identity="owner")

    work = run_seal.anchor_file_for(root).parent / ".seal-ledger-work"
    assert (work / ".git").is_dir(), "第二次应当复用已有克隆（走 pull 分支）"
    name = run_seal.anchor_file_for(root).name
    subprocess.run(["git", "-C", str(remote), "show", f"main:anchors/{name}"],
                   check=True, capture_output=True)


# ── ② 生产锚点库必须保持为空（防"读 env、写常量"的对称 bug） ──────────────────


def test_the_default_anchor_store_is_never_written_by_tests(tmp_path: Path) -> None:
    """隔离 fixture 的守门能力本身要被测试钉住，而不是靠人工数一次。

    现有锚点用例全都经 `anchor_file_for()` 走 env，所以"写死在常量上"的 bug 会全程绿、
    却把 pytest 残留重新倒进生产库（2026-09-25 实测那里曾累积 58 个）。
    """
    default_dir = Path(run_seal.DEFAULT_ANCHOR_DIR)
    before = sorted(p.name for p in default_dir.glob("*.anchor.json")) if default_dir.is_dir() else []
    assert run_seal.anchor_file_for(tmp_path / "x").parent != default_dir, \
        "前提：测试期间锚点目录应已被 fixture 指到 tmp"

    _sealed_run(tmp_path, name="daily-972")

    after = sorted(p.name for p in default_dir.glob("*.anchor.json")) if default_dir.is_dir() else []
    assert after == before, f"测试往生产锚点库写了：{set(after) - set(before)}"


# ── ③ v1 清单的几段分支 + --check-remote 的 remote_missing ────────────────────


def test_v1_inventory_authorizes_a_missing_transient_but_catches_a_rewrite(tmp_path: Path) -> None:
    """v1：`MAY_BE_ABSENT` 的瞬时件缺失属授权，但内容被改写照样要抓。"""
    root = _v1_sealed_run(tmp_path, name="daily-973")

    # 封存 run 内的写入一律走留底通道（护栏会拦裸写——这本身也是它的契约）
    with runs_guard.sealed_write_token(root, reason="test:fixture", author="tester"):
        (root / ".preview-links.lock").write_text('{"pid": 1}', encoding="utf-8")
        payload = run_seal.load_manifest(root)
        payload["files"].append({
            "path": ".preview-links.lock", "size": 10,
            "sha256": "0" * 64,
        })
        (root / run_seal.MANIFEST_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 进程外删掉（瞬时件被正常清理）→ `MAY_BE_ABSENT` 授权缺失，不算漂移
    subprocess.run(["rm", "-f", str(root / ".preview-links.lock")], check=True)
    report = run_seal.verify(root)
    assert not [c for c in report["changes"] if c["path"] == ".preview-links.lock"], \
        f"瞬时件缺失被判成漂移：{report['changes']}"

    # 但"存在且内容不符"必须报（授权的是缺失，不是改写）
    with runs_guard.sealed_write_token(root, reason="test:tamper", author="tester"):
        (root / ".preview-links.lock").write_text("tampered", encoding="utf-8")
    kinds = {c["path"]: c["kind"] for c in run_seal.verify(root)["changes"]}
    assert kinds.get(".preview-links.lock") == "modified", kinds


def test_v1_inventory_catches_an_added_file_and_an_append_only_rewrite(tmp_path: Path) -> None:
    """v1：新增文件与 append-only 重写都要报（复核手测过，但此前没有回归测试）。"""
    root = _v1_sealed_run(tmp_path, name="daily-974")

    subprocess.run(["bash", "-c", f"printf x > {root / 'sneaked.txt'}"], check=True)
    with runs_guard.sealed_write_token(root, reason="test", author="tester"):
        (root / "step-log.jsonl").write_text('{"name": "rewritten"}\n', encoding="utf-8")

    kinds = {c["path"]: c["kind"] for c in run_seal.verify(root)["changes"]}
    assert kinds.get("sneaked.txt") == "added", kinds
    assert kinds.get("step-log.jsonl") in {"append_only_rewritten", "append_only_truncated"}, kinds


def test_v1_inventory_catches_a_changed_sealed_marker(tmp_path: Path) -> None:
    """v1：`SEALED` 标记自身的字节被改动要报。"""
    root = _v1_sealed_run(tmp_path, name="daily-975")
    with runs_guard.sealed_write_token(root, reason="test", author="tester"):
        (root / run_seal.SEALED_NAME).write_text('{"tampered": true}\n', encoding="utf-8")

    kinds = {c["path"]: c["kind"] for c in run_seal.verify(root)["changes"]}
    assert kinds.get(run_seal.SEALED_NAME) == "modified", kinds


def test_check_remote_missing_maps_to_unverifiable(tmp_path: Path, monkeypatch, capsys) -> None:
    """离机账本里没有这条锚点 = 无法验证（3），不是有漂移（2）。"""
    root = _sealed_run(tmp_path, name="daily-976")
    monkeypatch.setattr(run_seal, "check_remote_anchor",
                        lambda *_a, **_k: {"status": "remote_missing", "remote": "ssh://x/y.git"})
    assert run_seal.main(["--run-root", str(root), "--check-remote"]) == run_seal.EXIT_UNVERIFIABLE
    assert json.loads(capsys.readouterr().out)["status"] == "remote_missing"


# ── ④ publish 的 ignore 只排除顶层那一份 ─────────────────────────────────────


def test_publish_still_ships_a_nested_file_that_happens_to_share_the_record_name(tmp_path: Path) -> None:
    """排除的是**顶层**自己的账；`preview/wechat/` 下同名文件必须照发。"""
    run = _make_preview_run(tmp_path)
    build_preview(run)
    nested = run / "preview" / "wechat" / preview_site.PUBLISH_RECORD_NAME
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text('{"nested": true}', encoding="utf-8")

    static = tmp_path / "outbox"
    static.mkdir()
    record = publish_preview(run, static, base_url="http://192.168.100.168:8899")

    shipped = sorted(p.relative_to(static / "2026-09-17-daily-999").as_posix()
                     for p in (static / "2026-09-17-daily-999").rglob("*") if p.is_file())
    assert f"wechat/{preview_site.PUBLISH_RECORD_NAME}" in shipped, shipped
    assert preview_site.PUBLISH_RECORD_NAME not in shipped, shipped
    assert f"wechat/{preview_site.PUBLISH_RECORD_NAME}" in record["files"]


# ── ⑤ render 的封存拒绝（与 export 同一条护栏） ────────────────────────────────


def test_topic_backlog_render_refuses_to_write_into_a_sealed_run(tmp_path: Path, capsys) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from topic_backlog import main as backlog_main

    sealed = tmp_path / "runs" / "2026-09-25" / "daily-977"
    sealed.mkdir(parents=True)
    (sealed / "SEALED").write_text("{}", encoding="utf-8")
    db = tmp_path / "backlog.sqlite"

    code = backlog_main(["--db", str(db), "render", "--out", str(sealed / "view.md")])

    assert code == 3
    assert "refuse_sealed_run" in capsys.readouterr().out
    assert not (sealed / "view.md").exists()


# ── ⑥ 非 UTF-8 路径 × 锚点：修复要真的生效，而不只是"状态落在集合里" ─────────────


def test_a_non_utf8_run_is_anchored_and_verifies_intact(tmp_path: Path) -> None:
    """F5 的实质：非 UTF-8 run 不仅能封存，锚点也要写成、摘要比对跨代理字符仍成立。"""
    parent = tmp_path / "runs" / "2026-09-25"
    parent.mkdir(parents=True)
    root = Path(os.fsdecode(os.fsencode(str(parent)) + b"/daily-\xffanchor"))
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 正文\n", encoding="utf-8")

    seal(root, identity="owner")

    assert run_seal.read_anchor(root) is not None, "非 UTF-8 run 的锚点没写成"
    report = run_seal.verify(root)
    assert report["status"] == "intact", report
    assert report["changes"] == []
    assert report["anchor"]["status"] == "anchored"


# ── ⑦ 非 UTF-8 **内层**路径：三个写手都要能落盘（第二轮复核 minor） ──────────────
#
# 第二轮复核实测：非 UTF-8 的**内层**文件（不是 run 根）会让落 JSON 文本的地方抛
# UnicodeEncodeError。`evidence_write` 那条已由提交 `7143710` 修掉；`step_log` 与
# `run_state`（SEALED 标记）当时仍在直写。三处现在共用
# `evidence_paths.json_text`（叶子模块），这一组把三条路径都钉住。


def _run_with_non_utf8_inner_file(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "runs" / "2026-09-25" / "daily-978"
    (root / "delivery").mkdir(parents=True)
    inner = os.fsdecode(b"art-\xff001.md")
    (root / "delivery" / inner).write_text("# 正文\n", encoding="utf-8")
    return root, f"delivery/{inner}"


def test_step_log_records_a_non_utf8_inner_artifact(tmp_path: Path) -> None:
    """步骤流水里的 artifacts 路径含非 UTF-8 字节时，写盘不能崩、且能原样读回。"""
    import datetime as dt

    from article_group import step_log

    root, inner = _run_with_non_utf8_inner_file(tmp_path)
    now = dt.datetime(2026, 9, 25, 12, 0, tzinfo=dt.timezone.utc)

    entry = step_log.record_step(root, name="render", started_at=now, artifacts=[inner])

    steps = step_log.read_steps(root)
    assert len(steps) == 1, steps
    assert [item["path"] for item in steps[0]["artifacts"]] == [inner]
    assert entry["name"] == "render"


def test_seal_records_a_non_utf8_inner_file_in_the_manifest(tmp_path: Path) -> None:
    """非 UTF-8 的**内层文件**路径要能进清单（run_seal 的面），封存全程不崩。

    第三轮复核 F2 更正了这条用例的**声称**：它原先叫"SEALED 标记同样要能落盘"，
    可 SEALED 载荷只含 `sealed_at/by/articles`，**根本不含这个文件路径**——把
    `run_state` 的序列化换回改动前的实现，这条照样通过（空转）。这里改成断言它
    真正该断言的东西：**清单里记下了这个路径**。
    """
    root, inner = _run_with_non_utf8_inner_file(tmp_path)
    seal(root, identity="owner")

    manifest = run_seal.load_manifest(root)
    assert inner in [item["path"] for item in manifest["files"]], inner
    assert run_seal.verify(root)["status"] in {"intact", run_seal.STATUS_UNANCHORED}
    # 清单本身必须是严格 utf-8 可解的字节（代理字符被转义，不是裸写）
    (root / run_seal.MANIFEST_NAME).read_text(encoding="utf-8")


def test_seal_marker_survives_a_non_utf8_article_id(tmp_path: Path) -> None:
    """**真正**覆盖 `run_state` 的非 UTF-8 修复（第三轮复核 F2）。

    SEALED 载荷里唯一可能带非 UTF-8 的是 `articles[].article_id`——它来自
    `delivery/<稿件目录名>`（`seal_articles` 取 `item.parent.name`）。此前那条用例用的是
    *文件名*，进不了载荷，所以对 `run_state` 的修复完全空转。
    """
    root = tmp_path / "runs" / "2026-09-25" / "daily-983"
    article_id = os.fsdecode(b"art-\xff001")          # 非 UTF-8 的稿件**目录**名
    (root / "delivery" / article_id).mkdir(parents=True)
    (root / "delivery" / article_id / "delivery.md").write_text("# 正文\n", encoding="utf-8")

    articles = seal_articles(root)
    assert articles and articles[0]["article_id"] == article_id, articles  # 前提：载荷真带上了它

    seal(root, identity="owner", articles=articles)

    raw = (root / run_seal.SEALED_NAME).read_bytes()
    raw.decode("utf-8")                                # 严格 utf-8：不许裸写代理字符
    payload = json.loads(raw.decode("utf-8"))
    assert payload["articles"][0]["article_id"] == article_id, "代理字符必须原样读回"


def test_all_json_writers_share_one_surrogate_safe_serializer() -> None:
    """同一段取舍不许抄多份：四个写手必须指向同一个实现。"""
    from article_group import evidence_write, run_state, step_log
    from article_group.evidence_paths import json_text

    assert run_seal.json_text is json_text
    assert step_log.json_text is json_text
    assert run_state.json_text is json_text
    assert evidence_write._json_line({"a": 1}) == '{"a": 1}\n'


# ── ⑧ 第二轮复核点名的另外三条分支 ────────────────────────────────────────────


def test_a_real_clone_failure_is_recorded_as_a_local_snapshot(tmp_path: Path, monkeypatch) -> None:
    """真实失败路径（不是 monkeypatch）：离机仓库根本不是一个 git 仓库时会把 clone 打挂。

    断言新形状（第二轮复核 major）：本机锚点写成 → 清单说 **anchored/local-snapshot**、
    `replication=failed`，人读行带「仅本机快照」警告——不能报成 intact 却什么都不说。
    """
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(not_a_repo))
    root = _sealed_run(tmp_path, name="daily-980")

    block = run_seal.load_manifest(root)["anchor"]
    assert block["status"] == "anchored", block
    assert block["kind"] == "local-snapshot", block
    assert block["replication"] == "failed", block
    assert run_seal.read_anchor(root) is not None, "本机锚点仍应留下"

    report = run_seal.verify(root)
    assert report["status"] == "intact"
    text = run_seal._describe(report)
    assert "仅本机快照" in text and "只改本机锚点仍能掩盖" in text, text


def test_a_missing_kind_is_never_fabricated(tmp_path: Path) -> None:
    """`kind` 两边都没有时不许打印一个数据里不存在的取值（复核 F1 的 `or "snapshot"` 面）。

    注意：锚点文件没记 `kind` 但**清单块记了**时，回退用清单块的值是**特性**（封存当时的
    事实），不算伪造。这里把两边都抹掉，才是在测"没有就别编"。
    """
    root = _sealed_run(tmp_path, name="daily-981")
    anchor_path = run_seal.anchor_file_for(root)
    record = json.loads(anchor_path.read_text(encoding="utf-8"))
    record.pop("kind", None)
    anchor_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with runs_guard.sealed_write_token(root, reason="test:strip-kind", author="tester"):
        payload = run_seal.load_manifest(root)
        payload["anchor"].pop("kind", None)
        (root / run_seal.MANIFEST_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = run_seal.verify(root)
    assert report["anchor"]["status"] == "anchored"
    assert report["anchor"].get("kind") is None, report["anchor"]
    text = run_seal._describe(report)
    assert "snapshot" not in text, text          # 不许凭空造 kind
    assert "仅本机快照" in text, text             # 但警告必须还在


def test_unseal_then_reseal_is_a_reachable_remedy(tmp_path: Path, monkeypatch) -> None:
    """remedy 声明的那条出路（unseal→reseal）要能走通，且**离机副本真的补上**。

    第三轮复核 F6 更正：原版只证实"能跑通"，`assert first` 还是恒真占位。真正要证的是
    failed → 修好远端 → 补推 → **离机仓库里能读到摘要，且与清单一致**。
    """
    from article_group.run_state import unseal

    remote = _bare_ledger(tmp_path)
    real_replicate = run_seal._replicate_anchor
    flag = {"down": True}

    def replicate(*args, **kwargs):
        if flag["down"]:
            return ("failed", "远端暂时不可达")
        return real_replicate(*args, **kwargs)      # 第二次走**真实**推送

    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))
    monkeypatch.setattr(run_seal, "_replicate_anchor", replicate)

    root = _sealed_run(tmp_path, name="daily-982")
    block = run_seal.load_manifest(root)["anchor"]
    assert (block["status"], block["replication"]) == ("anchored", "failed"), block

    flag["down"] = False                             # "修好远端"
    unseal(root, reason="测试：补推锚点", identity="owner")
    seal(root, identity="owner")

    report = run_seal.verify(root)
    assert report["status"] == "intact", report
    assert (report["anchor"]["status"], report["anchor"]["replication"]) \
        == ("anchored", "pushed"), report["anchor"]

    # 端到端的关键一步：离机仓库里真有这份锚点，且摘要与**清单现算的**摘要一致
    name = run_seal.anchor_file_for(root).name
    shown = subprocess.run(["git", "-C", str(remote), "show", f"main:anchors/{name}"],
                           capture_output=True, text=True, check=True)
    local_digest = run_seal.read_anchor(root)["manifest_digest"]
    assert json.loads(shown.stdout)["manifest_digest"] == local_digest
    assert local_digest == run_seal._manifest_digest(run_seal.load_manifest(root))


def test_every_non_pushed_replication_gets_the_local_snapshot_warning() -> None:
    """除 `pushed` 之外，每一种复制状态都必须给出「仅本机快照」警告（第三轮 coverage #4）。

    并且措辞不许自相矛盾：`pending`/未知时不能说成"未离机复制"这个**事实**。
    """
    for replication, expect in (
        ("local-only", "没有离机副本"),
        ("failed", "离机复制失败"),
        ("pending", "尚未完成"),
        ("unknown", "无法判定"),
    ):
        text = run_seal._describe_anchor({
            "status": "anchored", "kind": "local-snapshot", "replication": replication,
            "reason": "（测试原因）",
        })
        assert "仅本机快照" in text, (replication, text)
        assert "只改本机锚点仍能掩盖" in text, (replication, text)
        assert expect in text, (replication, text)
        # 警告里必须带上"不能当作已有离机副本"，别把未知说成确定
        assert "离机副本" in text, (replication, text)

    pushed = run_seal._describe_anchor({
        "status": "anchored", "kind": "offhost-snapshot",
        "replication": "pushed", "remote": "ssh://x/y.git",
    })
    assert "已离机复制" in pushed and "仅本机快照" not in pushed, pushed


# ── ⑨ `--unseal` CLI 及其护栏（第三轮复核 F9） ────────────────────────────────


def test_unseal_cli_refuses_without_a_reason(tmp_path: Path) -> None:
    root = _sealed_run(tmp_path, name="daily-984")
    with pytest.raises(SystemExit) as exc:
        run_seal.main(["--run-root", str(root), "--unseal", "--author", "owner"])
    assert "必须给 --reason" in str(exc.value)
    assert (root / run_seal.SEALED_NAME).is_file(), "被拒绝时不许动 SEALED"


def test_unseal_cli_refuses_the_default_agent_identity(tmp_path: Path) -> None:
    root = _sealed_run(tmp_path, name="daily-985")
    with pytest.raises(SystemExit) as exc:
        run_seal.main(["--run-root", str(root), "--unseal", "--reason", "要重封"])
    assert "必须显式给 --author" in str(exc.value)
    assert (root / run_seal.SEALED_NAME).is_file()


def test_unseal_cli_refuses_an_unsealed_run(tmp_path: Path) -> None:
    root = tmp_path / "daily-986"
    (root / "delivery" / "art-001").mkdir(parents=True)
    with pytest.raises(SystemExit) as exc:
        run_seal.main(["--run-root", str(root), "--unseal",
                       "--reason", "要重封", "--author", "owner"])
    assert "不是已封存状态" in str(exc.value)


def test_unseal_cli_leaves_a_trace_and_reopens_the_run(tmp_path: Path) -> None:
    """成功路径：留痕文件在、变更日志有账、run 恢复可写。"""
    from article_group.evidence_write import read_changelog
    from article_group.run_state import is_sealed

    root = _sealed_run(tmp_path, name="daily-987")
    assert is_sealed(root)

    code = run_seal.main(["--run-root", str(root), "--unseal",
                          "--reason", "锚点写坏了，要重封", "--author", "owner"])

    assert code == run_seal.EXIT_INTACT
    assert not (root / run_seal.SEALED_NAME).exists(), "SEALED 应已改名"
    revoked = list(root.glob(f"{run_seal.SEALED_NAME}.revoked.*"))
    assert revoked, "必须留下改名后的留痕文件（不是删除）"
    assert not is_sealed(root), "撤销后该 run 应恢复可写"

    entries = [item for item in read_changelog(root) if "unseal" in str(item.get("reason", ""))]
    assert entries, read_changelog(root)
    assert entries[-1]["author"] == "owner"


def _extract_command(remedy: str) -> str:
    """从 remedy 里抠出「可执行命令」那一段（`可执行命令：python -m article_group.run_seal …`）。"""
    for line in remedy.splitlines():
        marker = "可执行命令："
        if marker in line:
            return line.split(marker, 1)[1].strip()
    raise AssertionError(f"remedy 里没有可执行命令：{remedy!r}")


def _runnable(command: str, reason: str, author: str) -> str:
    """把占位符换成真实值，并把 `python` 换成当前解释器（本机 `python` 不在 PATH）。

    这是**执行环境**的替换，不是绕过命令本身的引用问题：引用正确与否由 `sh -n`
    那一关单独钉住。
    """
    return (command
            .replace("python -m", f"{shlex.quote(sys.executable)} -m", 1)
            .replace(f"'{run_seal.UNSEAL_REASON_PLACEHOLDER}'", shlex.quote(reason))
            .replace(f"'{run_seal.UNSEAL_AUTHOR_PLACEHOLDER}'", shlex.quote(author)))


def test_the_remedy_prints_a_copy_pasteable_unseal_command(tmp_path: Path, monkeypatch) -> None:
    """remedy 给的命令要**真能粘进 shell 跑**（F9 的本意；第四轮复核 R1 加严）。

    此前这条用例只做子串匹配（`"--unseal" in remedy`），于是打印出的命令**粘贴即报错**
    也照样绿：run 路径没引用（带空格就拆成两个参数）、`--author <你的身份>` 里的尖括号
    被 shell 当重定向（实测 `Syntax error: end of file unexpected`，退出 2）。

    现在分两步钉住，两步都不可省：
    1. **逐字粘贴**（含占位符）交给 `sh -n` 做语法检查——必须 0；
    2. 占位符换成真实值后**真的执行**，断言退出 0 且 SEALED 确实被改名留痕。

    要走到未锚定态：让锚点**写不进去**（封存时记 `anchor_unavailable`、磁盘上也没有锚点）。
    """
    monkeypatch.setattr(run_seal, "write_anchor",
                        lambda *_a, **_k: {"status": "anchor_unavailable", "reason": "模拟写不进去"})
    root = _sealed_run(tmp_path, name="daily-988")

    report = run_seal.verify(root)
    assert report["status"] == run_seal.STATUS_UNANCHORED, report
    remedy = report["anchor"]["remedy"]
    command = _extract_command(remedy)

    # ① 逐字粘贴（占位符原样）不许是语法错误
    parsed = subprocess.run(["sh", "-n", "-c", command], capture_output=True, text=True)
    assert parsed.returncode == 0, f"逐字粘贴就有语法错：{parsed.stderr}\n{command}"

    # ② 换成真实值后必须真的跑通
    executed = subprocess.run(
        ["sh", "-c", _runnable(command, "第四轮复核：验证 remedy 可粘贴", "owner")],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert executed.returncode == 0, f"remedy 的命令跑不通：\n{executed.stdout}\n{executed.stderr}"
    assert not (root / run_seal.SEALED_NAME).exists(), "命令跑通了却没撤销封存？"


def test_the_remedy_command_survives_a_run_path_with_spaces(tmp_path: Path, monkeypatch) -> None:
    """run 路径带空格时 remedy 依然可执行（R1 的具体反例：不引用会拆成两个参数）。"""
    monkeypatch.setattr(run_seal, "write_anchor",
                        lambda *_a, **_k: {"status": "anchor_unavailable", "reason": "模拟写不进去"})
    root = _sealed_run(tmp_path, name="daily 990 有空格")

    command = _extract_command(run_seal.verify(root)["anchor"]["remedy"])
    parsed = subprocess.run(["sh", "-n", "-c", command], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr

    executed = subprocess.run(
        ["sh", "-c", _runnable(command, "带空格的路径", "owner")],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert executed.returncode == 0, \
        f"带空格的 run 路径把命令打挂了：\n{executed.stdout}\n{executed.stderr}"
    assert not (root / run_seal.SEALED_NAME).exists()


def test_the_failed_push_remedy_names_the_real_run(tmp_path: Path, monkeypatch) -> None:
    """R2：离机复制失败时的 remedy 也要给**带真实路径**的可执行命令，而不是字面量 `<run>`。"""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(not_a_repo))
    root = _sealed_run(tmp_path, name="daily-989")

    block = run_seal.load_manifest(root)["anchor"]
    assert (block["status"], block["replication"]) == ("anchored", "failed"), block

    command = _extract_command(block["remedy"])
    assert str(root) in command, f"remedy 没带真实 run 路径（还是占位符？）：{command}"
    assert "<run>" not in command, command
    parsed = subprocess.run(["sh", "-n", "-c", command], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr


# ── ⑩ 第三轮 F7 的两条 remedy / unseal 对账 / 护栏（第四轮复核 R3/R4/R6/R7） ──────


def test_a_v1_manifest_carrying_the_v2_flag_also_carries_a_remedy(tmp_path: Path) -> None:
    """R3：这一支加了 remedy 却没人断言——删掉它整套测试仍是绿的。

    复核实测：`REVERT=contradictory_remedy_absent` 之后 `-k inventory` 仍 `1 passed`。
    """
    run = _make_preview_run(tmp_path)
    build_preview(run)
    payload = run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="t")
    payload["schema_version"] = run_seal.SCHEMA_VERSION_V1
    payload["inventory"] = run_seal.INVENTORY_ALL_ENTRIES
    run_seal.write_manifest(run, payload)

    result = run_seal.verify(run)
    assert result["status"] == "unverifiable", result
    remedy = result.get("remedy", "")
    assert remedy, "版本/标志矛盾这一支没有 remedy——操作者拿到结论却没有出路"
    assert str(run_seal.anchor_file_for(run)) in remedy, remedy
    assert "--backfill" in remedy, remedy


def test_a_v2_manifest_without_the_flag_also_carries_a_remedy(tmp_path: Path) -> None:
    """R3 的另一支：v2 声明却缺 inventory 标志。"""
    run = _make_preview_run(tmp_path)
    build_preview(run)
    run_seal.write_manifest(
        run, run_seal.build_manifest(run, sealed_at="2026-09-24T00:00:00+08:00", sealed_by="t"))
    manifest_path = run / run_seal.MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.pop("inventory", None)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    result = run_seal.verify(run)
    assert result["status"] == "unverifiable", result
    remedy = result.get("remedy", "")
    assert remedy, "缺 inventory 标志这一支没有 remedy"
    assert str(run_seal.anchor_file_for(run)) in remedy, remedy
    assert "--backfill" in remedy, remedy


def test_verify_after_unseal_does_not_report_an_unauthorized_change(tmp_path: Path) -> None:
    """R4：授权撤销封存之后，verify 不该把 SEALED 的消失算成「无账的可疑改动」。

    `unseal` 是按 `SEALED.revoked.<stamp>` 记的账，而 verify 看到的是 `SEALED` 不见了，
    路径对不上——于是 CLI 说「已记账」、机器可读层说「未授权」，两句话互相矛盾。
    """
    root = _sealed_run(tmp_path, name="daily-991")
    assert run_seal.verify(root)["status"] == "intact"

    code = run_seal.main(["--run-root", str(root), "--unseal",
                          "--reason", "锚点写坏了，要重封", "--author", "owner"])
    assert code == run_seal.EXIT_INTACT

    report = run_seal.verify(root)
    marker_changes = [item for item in report["changes"] if item["path"] == run_seal.SEALED_NAME]
    assert marker_changes, f"SEALED 不见了却不在 changes 里：{report['changes']}"
    assert all(item["kind"] == "missing" for item in marker_changes), marker_changes
    assert report["unauthorized_changes"] == [], report["unauthorized_changes"]
    assert all(item["authorized"] for item in report["changes"]), report["changes"]


def test_unseal_author_guard_is_casefolded_and_rejects_the_placeholder(tmp_path: Path) -> None:
    """R6：`AGENT`（大小写变体）与 remedy 自己印的 `<你的身份>` 都必须被拒。"""
    for index, bad in enumerate(("AGENT", "Agent", "<你的身份>")):
        root = _sealed_run(tmp_path, name=f"daily-992-{index}")
        with pytest.raises(SystemExit) as exc:
            run_seal.main(["--run-root", str(root), "--unseal",
                           "--reason", "要重封", "--author", bad])
        assert "必须显式给 --author" in str(exc.value), bad
        assert (root / run_seal.SEALED_NAME).is_file(), f"{bad} 被拒时不许动 SEALED"


def test_unseal_refuses_to_silently_swallow_other_flags(tmp_path: Path) -> None:
    """R7：`--unseal --backfill` 此前静默短路，操作者会以为 backfill 也跑了。"""
    root = _sealed_run(tmp_path, name="daily-993")
    with pytest.raises(SystemExit) as exc:
        run_seal.main(["--run-root", str(root), "--unseal", "--backfill",
                       "--reason", "要重封", "--author", "owner"])
    assert "不能同时使用" in str(exc.value)
    assert (root / run_seal.SEALED_NAME).is_file(), "拒绝时不许动 SEALED"
    assert run_seal.verify(root)["status"] == "intact"



# ── ⑪ 既有残余收口：`review/.before/**` 的"只写不记"通道（2026-09-25） ──────────


def _sealed_run_with_review(tmp_path: Path, name: str) -> Path:
    """封存时**已有** `review/` 的 run（真实 run 的形状）。

    `_sealed_run` 是个最小夹具，连 `review/` 都没有；那样一来后面建 `review/` 会多出一个
    "新增目录"，把本组用例的靶子（快照账目）淹掉。这里补齐成真实形状。
    """
    root = tmp_path / name
    (root / "delivery" / "art-001").mkdir(parents=True)
    (root / "delivery" / "art-001" / "delivery.md").write_text("# 正文\n", encoding="utf-8")
    (root / "review").mkdir()
    (root / "batch.json").write_text(json.dumps({"articles": [{"article_id": "art-001"}]}), encoding="utf-8")
    seal(root, identity="owner")
    return root


def test_an_unrecorded_snapshot_file_is_reported_as_unauthorized(tmp_path: Path) -> None:
    """留底快照整条不在清单里，所以必须**按账目**兜底。

    此前 `review/.before/**` 完全排除：封存后往那儿写任何文件，verify 仍报 intact——
    一条对 added/modified 完全不可见的写入面（第一轮复核就点名的既有残余）。
    """
    root = _sealed_run_with_review(tmp_path, "daily-994")
    assert run_seal.verify(root)["status"] == "intact"

    # 护栏在**本进程**里会挡下这次写入；而这条通道的威胁模型正是"进程外写手"
    # （`sys.addaudithook` 只作用于装钩子的进程），所以用子进程来模拟它。
    smuggled = root / "review" / ".before" / "20260925T000000" / "delivery" / "art-001" / "delivery.md"
    subprocess.run([sys.executable, "-c",
                    "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);"
                    "p.write_text('# 伪造的旧版本\\n',encoding='utf-8')",
                    str(smuggled)], check=True)
    assert smuggled.is_file()

    report = run_seal.verify(root)
    assert report["status"] == "drifted", report
    offenders = [item for item in report["changes"] if item["kind"] == "snapshot_unrecorded"]
    assert [item["path"] for item in offenders] == [
        "review/.before/20260925T000000/delivery/art-001/delivery.md"], report["changes"]
    assert offenders[0]["path"] in {item["path"] for item in report["unauthorized_changes"]}


def test_a_recorded_snapshot_file_is_not_a_change(tmp_path: Path) -> None:
    """**有账**的留底快照仍不算篡改——留底通道本来就是封存后唯一合法的写入面。

    不给出这一条，"兜底"就会被读成"禁止封存后留底"，而那会把正常流程判成漂移。
    """
    from article_group.evidence_write import write_evidence

    root = _sealed_run_with_review(tmp_path, "daily-995")
    target = root / "delivery" / "art-001" / "delivery.md"
    write_evidence(target, "# 改过的正文\n", run_dir=root, reason="test:force", force=True)

    report = run_seal.verify(root)
    snapshot_changes = [item for item in report["changes"] if item["kind"] == "snapshot_unrecorded"]
    assert snapshot_changes == [], report["changes"]
    # 被覆盖的那个文件本身当然是改动，但**有账**（force 记账），所以不是未授权
    assert report["unauthorized_changes"] == [], report["unauthorized_changes"]


def test_two_snapshots_of_the_same_target_are_both_accounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一个目标被 force 写**两次**（两个留底快照）时，两个快照都必须算"有账"。

    第六轮复核 major（2026-09-25）：`_unrecorded_snapshots` 从 `_changelog_index()`
    取账，而那个索引按**目标 path** 去重、只留最后一条，于是同一目标写两次时，
    第一个快照的 `snapshot_path` 不在集合里 → 被误报成 `snapshot_unrecorded`。

    上一个用例（写一次）恰好在去重账下蒙对，所以没抓住它。真实后果不是理论：
    daily-009 报 1174 条、daily-010 报 428 条假漂移，状态从 `unanchored`（退出 3）
    变成 `drifted`（退出 2）——按退出码消费结果的自动化会收到**假篡改告警**，
    而真的无账快照被淹在里面。

    注意反方向：这条误报只多报、不漏报，所以它不是封存绕过；本用例只钉住"别误报"。
    """
    import datetime as _dt

    from article_group import evidence_write
    from article_group.evidence_write import write_evidence

    root = _sealed_run_with_review(tmp_path, "daily-996")
    target = root / "delivery" / "art-001" / "delivery.md"

    # 快照目录按秒命名，同一秒内两次写会落进同一个快照路径（也就不会触发本 bug），
    # 所以把时钟错开 30 秒，制造"两个不同时刻的快照"这个真实形态。
    # 每次 `write_evidence` 会取**两次** `_now()`（快照目录 + 记账时刻），故每两次调用
    # 才前进一格——直接按调用次数递增会让快照目录与记账时刻错开。
    start = _dt.datetime(2026, 9, 25, 12, 0, 0, tzinfo=_dt.timezone.utc)
    tick = {"n": 0}

    def fake_now() -> _dt.datetime:
        moment = start + _dt.timedelta(seconds=30 * (tick["n"] // 2))
        tick["n"] += 1
        return moment

    monkeypatch.setattr(evidence_write, "_now", fake_now)

    write_evidence(target, "# 第一次改\n", run_dir=root, reason="test:force-1", force=True)
    write_evidence(target, "# 第二次改\n", run_dir=root, reason="test:force-2", force=True)

    snapshots = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "review" / ".before").rglob("*.md")
    )
    # 前提断言：真的产生了**两个**快照，否则本用例会退化成上一个用例的重复
    assert len(snapshots) == 2, snapshots

    report = run_seal.verify(root)
    assert [c for c in report["changes"] if c["kind"] == "snapshot_unrecorded"] == [], report["changes"]
    assert report["unauthorized_changes"] == [], report["unauthorized_changes"]


# ── ⑫ 离机推送的持久化开关（2026-09-25 controller 授权"启用离机锚点推送"） ──────


def test_anchor_remote_resolution_order(monkeypatch, tmp_path: Path) -> None:
    """`_anchor_remote()`：环境变量优先 → 配置文件 → 空（只留本机快照）。"""
    conf = tmp_path / "seal-anchor-push.conf"
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_CONFIG_ENV, str(conf))

    # ① 都没有 → 空（安全默认：不推离机）
    assert run_seal._anchor_remote() == ""

    # ② 只有配置文件 → 读它（`remote=<url>` 形式）
    conf.write_text("# 离机锚点账本\n\nremote=ssh://example/ledger.git\n", encoding="utf-8")
    assert run_seal._anchor_remote() == "ssh://example/ledger.git"

    # ③ 裸 URL 行也认
    conf.write_text("ssh://bare/ledger.git\n", encoding="utf-8")
    assert run_seal._anchor_remote() == "ssh://bare/ledger.git"

    # ④ 环境变量优先于配置文件
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, "ssh://from-env/ledger.git")
    assert run_seal._anchor_remote() == "ssh://from-env/ledger.git"

    # ⑤ 没有有效行 → 空（注释/空行/别的键都不算）
    monkeypatch.delenv(run_seal.ANCHOR_PUSH_ENV, raising=False)
    conf.write_text("# 只有注释\n\nother_key=x\n", encoding="utf-8")
    assert run_seal._anchor_remote() == ""


def test_the_production_push_config_is_not_read_under_pytest() -> None:
    """生产配置**必须**被测试隔离掉。

    `~/.dsh/seal-anchor-push.conf` 一旦真的存在（启用离机推送之后它就会存在），
    只 `delenv` 是不够的：`_anchor_remote()` 会回退去读它，于是**跑一次套件就
    往真实离机账本推 pytest 残留锚点**。这条用例把隔离本身钉住。
    """
    assert run_seal._anchor_push_config_path() != run_seal.DEFAULT_ANCHOR_PUSH_CONFIG, \
        "测试环境里配置文件路径仍指向生产路径——锚点隔离失效"
    assert run_seal._anchor_remote() == "", \
        "测试环境里解析出了非空离机地址——跑套件会去推真实账本"


def test_the_durable_push_config_drives_real_replication(tmp_path: Path, monkeypatch) -> None:
    """**持久化配置**（不是环境变量）也要能真的驱动 clone→commit→push。

    这条是本项的重点：授权"启用离机锚点推送"落成的就是那个配置文件，
    所以"读得到配置"与"配置真的让锚点离机"必须一起被证明。
    """
    remote = _bare_ledger(tmp_path)
    config = tmp_path / "seal-anchor-push.conf"
    config.write_text(f"# 测试用离机账本\nremote={remote}\n", encoding="utf-8")
    # 关键：**不设** RUOYU_SEAL_ANCHOR_PUSH，只给配置文件路径
    monkeypatch.delenv(run_seal.ANCHOR_PUSH_ENV, raising=False)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_CONFIG_ENV, str(config))

    root = _sealed_run(tmp_path, name="daily-996")
    block = run_seal.load_manifest(root)["anchor"]
    assert (block["status"], block["replication"], block["kind"]) == \
        ("anchored", "pushed", "offhost-snapshot"), block

    name = run_seal.anchor_file_for(root).name
    shown = subprocess.run(["git", "-C", str(remote), "show", f"main:anchors/{name}"],
                           capture_output=True, text=True, check=True)
    assert json.loads(shown.stdout)["manifest_digest"] == block["manifest_digest"]


# ── ⑬ 事后补锚 `--reanchor`（2026-09-25 controller 裁决 b） ─────────────────────
#
# 对象就是 daily-008/009/010 的真实形态：真 v1 清单、**没有 anchor 块**、磁盘上没有锚点
# （复用 `_v1_sealed_run`）。补锚要么把它们从"什么都证明不了"变成"从今天起可证明"，
# 要么就会再造一个安全假象——所以这一组的重点全在**不能报成 intact**。


def _tree_digest(root: Path) -> str:
    """run 内所有文件/符号链接的路径+内容的整体摘要（证明"run 没被动过"）。"""
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(
            ("link:" + os.readlink(path)).encode("utf-8", "surrogateescape")
            if path.is_symlink() else path.read_bytes()
        )
        digest.update(b"\0")
    return digest.hexdigest()


def test_reanchor_marks_the_anchor_retroactive_and_never_reports_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """补锚之后：状态是 `anchored_retroactive`（退出 3），**不是** intact/anchored。

    这是本项的安全要害。事后补的锚点只证明"从补锚那一刻起"清单未被改写，而"封存当时
    就锚好"的 run 报 intact——两者若在机器可读层长得一样，就正是 F1/F2 消除的那类假象，
    按 `status == intact` 消费结果的自动化会把这三条旧 run 读成"证明过没被改"。
    """
    root = _v1_sealed_run(tmp_path, name="daily-971")
    assert run_seal.verify(root)["status"] == run_seal.STATUS_UNANCHORED

    pushed: list[tuple] = []
    monkeypatch.setattr(run_seal, "_replicate_anchor",
                        lambda *args, **kwargs: pushed.append(args) or ("pushed", "ssh://x"))
    # 就算环境里配了离机推送，补锚也**不许**去推：事后锚点进离机账本后，
    # 在账本里与封存当时的锚点无法区分。
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, "ssh://should-never-be-contacted/ledger.git")

    result = run_seal.reanchor(root, author="owner", reason="controller 2026-09-25 裁决 b")
    assert result["status"] == "reanchored", result
    assert result["retroactive"] is True
    assert pushed == [], "补锚不得推离机"

    on_disk = run_seal.read_anchor(root)
    assert on_disk is not None, "补锚没写下锚点文件"
    assert on_disk["retroactive"] is True, on_disk
    assert on_disk["retroactive_by"] == "owner"
    assert on_disk["retroactive_reason"], on_disk
    assert on_disk["replication"] == "local-only", on_disk

    report = run_seal.verify(root)
    assert report["status"] == run_seal.STATUS_ANCHORED_RETROACTIVE, report
    assert report["status"] != "intact"
    assert report["changes"] == [], report["changes"]
    anchor = report["anchor"]
    assert anchor["status"] == run_seal.STATUS_ANCHORED_RETROACTIVE, anchor
    assert anchor["retroactive"] is True and anchor["retroactive_by"] == "owner", anchor
    assert anchor["replication"] == "local-only"

    text = run_seal._describe(report)
    assert run_seal.STATUS_ANCHORED_RETROACTIVE in text, text
    assert "事后补" in text, text
    assert "不按 intact 上报" in text, text

    # CLI 层也不许给 0（脚本按退出码分流时不能把它读成完好）
    assert run_seal.main(["--run-root", str(root)]) == run_seal.EXIT_UNVERIFIABLE


def test_reanchor_changes_nothing_inside_the_run(tmp_path: Path) -> None:
    """补锚只往 run **之外**的锚点库写一个文件：run 内每个字节逐位相同。

    改封存 run 的清单（哪怕只是补一个 `anchor` 块）就是"为了取证而改证据"，
    而且 `_manifest_digest()` 本来就排除 `anchor` 块，不加也照样锚得上。
    """
    root = _v1_sealed_run(tmp_path, name="daily-972")
    before = _tree_digest(root)

    assert run_seal.reanchor(root, author="owner", reason="证明 run 没被动过")["status"] == "reanchored"

    assert _tree_digest(root) == before, "补锚动了 run 内的字节"
    assert "anchor" not in run_seal.load_manifest(root), "补锚往封存清单里塞了 anchor 块"


def test_reanchor_has_teeth_a_rewritten_manifest_is_still_caught(tmp_path: Path) -> None:
    """补锚给的是**真**保证：补完之后改写清单，`verify` 必须报 drifted。

    只钉"状态名不是 intact"是不够的——若补锚写的摘要根本没被用来比对，状态名照样对，
    但那是一个空壳。这里在补锚后用子进程改写清单正文（模拟进程外写手），必须被抓到。
    """
    root = _v1_sealed_run(tmp_path, name="daily-973")
    assert run_seal.reanchor(root, author="owner", reason="x")["status"] == "reanchored"
    assert run_seal.verify(root)["status"] == run_seal.STATUS_ANCHORED_RETROACTIVE

    subprocess.run(
        [sys.executable, "-c",
         "import json,pathlib,sys;"
         "p=pathlib.Path(sys.argv[1])/'SEALED.manifest.json';"
         "m=json.loads(p.read_text(encoding='utf-8'));"
         "m['file_count']=m.get('file_count',0)+1;"
         "p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8')",
         str(root)],
        check=True,
    )
    report = run_seal.verify(root)
    assert report["status"] == "drifted", report
    assert any(item["kind"] == "anchor_mismatch" for item in report["changes"]), report["changes"]


def test_reanchor_refuses_open_runs_and_already_anchored_runs(tmp_path: Path) -> None:
    """未封存的、以及已经锚过的 run 都不许补锚——补锚只用于**从未锚过**的 run。"""
    open_root = tmp_path / "never-sealed"
    (open_root / "delivery").mkdir(parents=True)
    (open_root / "delivery" / "a.md").write_text("# x\n", encoding="utf-8")
    assert run_seal.reanchor(open_root, author="owner", reason="x")["status"] == "not_sealed"

    anchored = _sealed_run(tmp_path, name="daily-974")
    assert run_seal.reanchor(anchored, author="owner", reason="x")["status"] == "already_anchored"
    # 被拒绝之后不许留下任何痕迹：那个 run 仍然是正常锚定的 intact、锚点没被改成 retroactive
    assert "retroactive" not in run_seal.read_anchor(anchored)
    assert run_seal.verify(anchored)["status"] == "intact"


def test_reanchor_cli_requires_a_reason_and_an_accountable_author(tmp_path: Path) -> None:
    """补锚是制造证据的动作：必须有人担责（`--author`，不许 agent/占位符）、必须有理由。"""
    root = _v1_sealed_run(tmp_path, name="daily-975")

    with pytest.raises(SystemExit):
        run_seal.main(["--run-root", str(root), "--reanchor", "--author", "owner"])
    for bad_author in ("agent", "AGENT", "<你的身份>"):
        with pytest.raises(SystemExit):
            run_seal.main(["--run-root", str(root), "--reanchor",
                           "--reason", "x", "--author", bad_author])
    # 与其它独立动作不能同时给（第四轮复核 R7 的口径）
    with pytest.raises(SystemExit):
        run_seal.main(["--run-root", str(root), "--reanchor", "--unseal",
                       "--reason", "x", "--author", "owner"])

    assert run_seal.read_anchor(root) is None, "护栏拦下之后不许留下锚点"
    assert run_seal.verify(root)["status"] == run_seal.STATUS_UNANCHORED


# ── ⑭ 复现/验收脚本自己的锚点隔离（2026-09-25，实测事故后补） ────────────────────


def test_the_repro_script_never_pushes_to_the_configured_ledger(tmp_path: Path) -> None:
    """复现脚本必须把**持久化推送配置**也隔离掉，否则会往真实离机账本推残留。

    实测事故：§24.3 启用离机推送后 `_anchor_remote()` 多了"回退读
    `~/.dsh/seal-anchor-push.conf`"这一级，而 `repro_anchor_bypass.py` 当时只
    `delenv` 环境变量、没有隔离配置路径——于是 mac-backup 可达时生产账本里多了三条
    `2026-09-25-var-{a,b,c}.anchor.json` 复现残留（`verify-objective.py` 每跑一次都会经过它）。

    这条用例给一个**本地裸仓库**当配置里的远端，跑完复现脚本后它必须仍然没有任何 ref：
    脚本若只挡环境变量、放行继承来的配置路径，就会真的推上去。
    """
    import os

    script = (Path(__file__).resolve().parents[1]
              / "runs/2026-09-25/seal-anchor-bypass/repro_anchor_bypass.py")
    if not script.is_file():
        # `runs/` 只是部分被跟踪（见 AGENTS.md「Where the suite may be run」）：
        # 干净检出里没有这个脚本，显式跳过并说明，而不是让用例恒真通过。
        pytest.skip("干净检出里没有 runs/…/repro_anchor_bypass.py（runs/ 只部分被跟踪）")

    remote = _bare_ledger(tmp_path)
    config = tmp_path / "prod-like-push.conf"
    config.write_text(f"# 假装这是生产配置\nremote={remote}\n", encoding="utf-8")
    env = {**os.environ, run_seal.ANCHOR_PUSH_CONFIG_ENV: str(config)}
    env.pop(run_seal.ANCHOR_PUSH_ENV, None)

    completed = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
    assert completed.returncode == 0, completed.stderr[-800:]

    refs = subprocess.run(["git", "-C", str(remote), "for-each-ref"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert refs == "", f"复现脚本往配置里的离机账本推了东西：{refs}"


# ── ⑮ 离机推送的分支对齐（2026-09-25 mac-backup scratch 账本上实跑击中） ─────────


def test_consecutive_anchors_replicate_even_when_the_ledger_default_branch_is_not_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一远端**连续**封存两次都必须 `pushed` —— 账本默认分支不是 main 时也要成立。

    2026-09-25 在 mac-backup 的 scratch 账本上实跑击中（RUN-RECORD §25.3）：
    `_replicate_anchor()` 推 `HEAD:main`，而工作副本的 upstream 是 `git clone` 时按
    **远端 HEAD** 定下的。scratch 仓库是 `git init --bare`（默认 `master`）建的，空仓库 clone
    出的工作副本把 `master` 记成 merge ref；于是**第二条**锚点 `git pull --ff-only` 去找
    `refs/heads/master`，逐字报
    `Your configuration specifies to merge with the ref 'refs/heads/master' from the remote,
    but no such ref was fetched.` → `replication=failed`。

    危害不是安全假象（如实记 failed），而是**第一条之后的所有锚点都退化成仅本机快照**。
    这条用例把"分支名不再取决于 clone 那一刻远端碰巧指向谁"钉住。
    """
    remote = tmp_path / "ledger.git"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(remote)],
                   check=True, capture_output=True)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))

    for index in (1, 2):
        root = _sealed_run(tmp_path, name=f"daily-98{index}")
        block = run_seal.load_manifest(root)["anchor"]
        assert (block["status"], block["replication"]) == ("anchored", "pushed"), (index, block)

    listed = subprocess.run(["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "main"],
                            capture_output=True, text=True, check=True).stdout
    assert listed.count(".anchor.json") == 2, listed


# ── ⑯ 第六轮复核的 3 条 minor：远端 URL、分叉不丢提交、以及那条已知一步滞后 ──────


def test_a_stale_work_tree_remote_follows_the_configured_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """换了配置里的离机账本后，必须真的推**新**账本——清单的 `remote` 不许谎报。

    第六轮复核 minor 3（pre-existing，`940a121` 上同样复现）：复用工作副本时从不校验
    `origin` 指向。改 `RUOYU_SEAL_ANCHOR_PUSH` 后仍 fetch/push **旧**账本，而清单的
    `anchor.remote` 一律写新 URL —— 新账本一个 ref 都没有，信清单去新账本报案的人找不到锚点。
    这条钉住"实际推送目标 == 清单记录的 remote"。
    """
    ledger_a = tmp_path / "ledger-a.git"
    ledger_b = tmp_path / "ledger-b.git"
    for path in (ledger_a, ledger_b):
        subprocess.run(["git", "init", "--bare", "-b", "main", str(path)],
                       check=True, capture_output=True)

    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(ledger_a))
    first = _sealed_run(tmp_path, name="daily-961")
    assert run_seal.load_manifest(first)["anchor"]["replication"] == "pushed"

    # 换账本，但**不删**工作副本（这正是操作者最容易漏的一步）
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(ledger_b))
    second = _sealed_run(tmp_path, name="daily-962")
    block = run_seal.load_manifest(second)["anchor"]
    assert block["replication"] == "pushed", block
    assert block["remote"] == str(ledger_b), block

    def anchors_in(ledger: Path) -> set[str]:
        listed = subprocess.run(["git", "-C", str(ledger), "ls-tree", "-r", "--name-only", "main"],
                                capture_output=True, text=True)
        if listed.returncode != 0:
            return set()
        return {line.split("/")[-1] for line in listed.stdout.split() if line.endswith(".anchor.json")}

    # 事实与清单一致：锚点落在**新**账本。旧账本历史**不搬过来**（第七轮复核 minor 1：
    # 搬家会在"新账本已有同名不同内容锚点"时必然冲突，把之后每条 run 都卡死），
    # 所以旧账本仍只有它自己那一条，新账本只有换过来之后的这一条。
    assert anchors_in(ledger_b) == {run_seal.anchor_file_for(second).name}
    assert anchors_in(ledger_a) == {run_seal.anchor_file_for(first).name}
    # 换账本这件事必须在成功路径上留痕（否则完全不可见）
    assert "改指到" in block.get("replication_note", ""), block


def test_switching_to_a_ledger_that_already_has_a_same_named_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """换账本 + 目标账本**已有同名不同内容**的锚点：新 run 仍必须 `pushed`、不许卡死。

    第七轮复核 minor 1 的实测（探针 p9）：此前"把旧账本历史 rebase 到新账本之上"的设计，
    只要新账本里存在同名锚点（锚点名只由「日期-批次」派生）就 add/add 冲突 → **之后每一条**
    run 都 `failed`、账本一个 ref 都收不到，而且卡死那条连"下次随历史补推"的机会都没有。
    """
    ledger_a = tmp_path / "ledger-a.git"
    ledger_b = tmp_path / "ledger-b.git"
    for path in (ledger_a, ledger_b):
        subprocess.run(["git", "init", "--bare", "-b", "main", str(path)],
                       check=True, capture_output=True)

    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(ledger_a))
    first = _sealed_run(tmp_path, name="daily-971")
    assert run_seal.load_manifest(first)["anchor"]["replication"] == "pushed"

    # 目标账本上先塞一条**同名但内容不同**的锚点（模拟"另一台机器的账本"）。
    # 锚点名只由「日期-批次」派生，所以这里能用 `anchor_file_for()` 在**封存之前**算出名字。
    target_run = tmp_path / "daily-972"
    same_name = run_seal.anchor_file_for(target_run).name
    seed = tmp_path / "seed-b"
    subprocess.run(["git", "clone", str(ledger_b), str(seed)], check=True, capture_output=True)
    (seed / "anchors").mkdir(parents=True, exist_ok=True)
    (seed / "anchors" / same_name).write_text('{"schema_version": "seal-anchor-v1", "note": "别的机器"}\n',
                                              encoding="utf-8")
    for args in (["add", "--", f"anchors/{same_name}"],
                 ["-c", "user.name=other", "-c", "user.email=other@x", "commit", "-m", "seed other machine"]):
        subprocess.run(["git", "-C", str(seed), *args], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "push", "origin", "main:main"], check=True, capture_output=True)

    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(ledger_b))
    switched = _sealed_run(tmp_path, name="daily-972")
    block = run_seal.load_manifest(switched)["anchor"]
    assert block["replication"] == "pushed", block
    note = block.get("replication_note", "")
    assert "改指到" in note, block
    # 换账本走的是**重新 clone**，不该靠"搬家 → 冲突 → 救援"收场；旧账本的历史也不该被搬进来
    assert "rebase 冲突" not in note, block

    listed = subprocess.run(["git", "-C", str(ledger_b), "ls-tree", "-r", "--name-only", "main"],
                            capture_output=True, text=True, check=True).stdout
    assert run_seal.anchor_file_for(first).name not in listed, listed

    shown = subprocess.run(["git", "-C", str(ledger_b), "show", f"main:anchors/{same_name}"],
                           capture_output=True, text=True, check=True).stdout
    # 同名那条已被本机（权威）版本覆盖：账本上留下的是我们这次封存的摘要
    assert json.loads(shown)["manifest_digest"] == block["manifest_digest"]


def test_a_divergent_ledger_still_replicates_the_local_only_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """账本被别处推进过（分叉）时，上一次推送失败的锚点必须**补推上去**、不许静默丢掉。

    第六轮复核 minor 1：原 `else` 分支 `checkout -B main origin/main` 会把本地那条已 commit
    未推送的锚点硬重置掉，git 还连带删掉工作副本里待推送的锚点文件——那条锚点永不再推，
    只有本机锚点目录里还留一份。现在改成 rebase 到远端之上再一起推。

    同时钉住第六轮复核 minor 2 记的**已知一步滞后**（已写进 `write_anchor` 的 docstring）：
    补推成功后，那条**历史 run** 的清单仍写 `replication=failed`（低报，不是假 intact），
    它的离机副本内容是"推送当时态"。
    """
    remote = _bare_ledger(tmp_path)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))
    first = _sealed_run(tmp_path, name="daily-963")
    assert run_seal.load_manifest(first)["anchor"]["replication"] == "pushed"

    # 让推送失败（远端 pre-receive 拒绝）：fetch/对齐都成功，于是本地留下已 commit 的锚点
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    failed = _sealed_run(tmp_path, name="daily-964")
    failed_block = run_seal.load_manifest(failed)["anchor"]
    assert failed_block["replication"] == "failed", failed_block

    work = run_seal._anchor_dir() / ".seal-ledger-work"
    local_before = subprocess.run(["git", "-C", str(work), "log", "--format=%s", "main"],
                                  capture_output=True, text=True, check=True).stdout.splitlines()
    assert any("daily-964" in line for line in local_before), local_before

    # 外部写手推进账本（模拟"另一个 writer"或人工 push）：与本地 main 分叉
    hook.unlink()
    other = tmp_path / "other-writer"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    (other / "anchors" / "external.anchor.json").write_text("{}\n", encoding="utf-8")
    for args in (["add", "--", "anchors/external.anchor.json"],
                 ["-c", "user.name=other", "-c", "user.email=other@x", "commit", "-m", "external writer"]):
        subprocess.run(["git", "-C", str(other), *args], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(other), "push", "origin", "main:main"], check=True, capture_output=True)

    third = _sealed_run(tmp_path, name="daily-965")
    third_block = run_seal.load_manifest(third)["anchor"]
    assert third_block["replication"] == "pushed", third_block

    listed = subprocess.run(["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "main"],
                            capture_output=True, text=True, check=True).stdout
    assert run_seal.anchor_file_for(failed).name in listed, listed   # 补推成功，没被丢掉
    assert run_seal.anchor_file_for(third).name in listed, listed
    assert "anchors/external.anchor.json" in listed, listed          # 外部写手的提交也还在
    remote_log = subprocess.run(["git", "-C", str(remote), "log", "--format=%s", "main"],
                                capture_output=True, text=True, check=True).stdout
    assert "external writer" in remote_log
    assert "daily-964" in remote_log, remote_log                     # 本地提交 rebase 后推上去了

    # minor 2 的已知一步滞后：那条历史 run 的**清单**仍写 failed（低报），账本里却已经有它
    assert run_seal.load_manifest(failed)["anchor"]["replication"] == "failed"
    shown = subprocess.run(["git", "-C", str(remote), "show",
                            f"main:anchors/{run_seal.anchor_file_for(failed).name}"],
                           capture_output=True, text=True, check=True).stdout
    assert json.loads(shown)["manifest_digest"] == failed_block["manifest_digest"]


def test_a_same_ledger_conflict_does_not_block_the_current_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同名路径 add/add 冲突时：本条 run 照常推送、冲突那批留档、且**不静默**。

    第七轮复核 minor 1 的另一半，也是它点名的 coverage gap：rebase 失败这条分支此前
    **没有任何用例覆盖**——把实现换成恒失败，套件也不会红。这里把它钉住：
    本条 run 仍 `pushed`（不连坐）、冲突路径与 rescue 分支名写进 `replication_note`、
    本地待推送提交在 rescue 分支上完整保留、账本上那条同名锚点没被我们覆盖。
    """
    remote = _bare_ledger(tmp_path)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))
    first = _sealed_run(tmp_path, name="daily-981")
    assert run_seal.load_manifest(first)["anchor"]["replication"] == "pushed"

    # 让 run2 的推送失败：本地留下已 commit 未推送的锚点
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    failed = _sealed_run(tmp_path, name="daily-982")
    assert run_seal.load_manifest(failed)["anchor"]["replication"] == "failed"
    hook.unlink()

    # 外部写手把**同名路径**用**不同内容**推上账本 → 真分叉 + 真冲突
    clashing = run_seal.anchor_file_for(failed).name
    other = tmp_path / "other-writer"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    (other / "anchors").mkdir(exist_ok=True)
    (other / "anchors" / clashing).write_text('{"note": "别的机器写的同名锚点"}\n', encoding="utf-8")
    for args in (["add", "--", f"anchors/{clashing}"],
                 ["-c", "user.name=other", "-c", "user.email=other@x", "commit", "-m", "external same-name"],
                 ["push", "origin", "main:main"]):
        subprocess.run(["git", "-C", str(other), *args], check=True, capture_output=True)

    third = _sealed_run(tmp_path, name="daily-983")
    block = run_seal.load_manifest(third)["anchor"]
    assert block["replication"] == "pushed", block                 # 不连坐
    note = block.get("replication_note", "")
    assert "rebase 冲突" in note and "seal-rescue-" in note, note
    assert clashing in note, note                                  # 冲突路径必须可见

    work = run_seal._anchor_dir() / ".seal-ledger-work"
    branches = subprocess.run(["git", "-C", str(work), "branch", "--format=%(refname:short)"],
                              capture_output=True, text=True, check=True).stdout.split()
    rescue = [name for name in branches if name.startswith("seal-rescue-")]
    assert rescue, f"没有留下 rescue 分支：{branches}"
    rescue_log = subprocess.run(["git", "-C", str(work), "log", "--format=%s", rescue[0]],
                                capture_output=True, text=True, check=True).stdout
    assert "daily-982" in rescue_log, rescue_log                   # 本地提交没丢

    # 冲突那批没被推上去：账本上那条同名锚点仍是外部写手的版本
    shown = subprocess.run(["git", "-C", str(remote), "show", f"main:anchors/{clashing}"],
                           capture_output=True, text=True, check=True).stdout
    assert "别的机器" in shown, shown
    # 本条 run 的锚点确实进了账本
    listed = subprocess.run(["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "main"],
                            capture_output=True, text=True, check=True).stdout
    assert run_seal.anchor_file_for(third).name in listed, listed


def test_the_recorded_remote_is_the_effective_push_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """清单里的 `remote` 必须是 git **解析后**的真实推送目标（第七轮复核 minor 2）。

    全局 `url.<base>.insteadOf` 这类重写发生在工作副本之外：只把 `set-url` 改成配置串，
    清单仍会写出与实际落点不符的 remote（实测：清单写 A、锚点落在 B、A 一个 ref 都没有）。
    这里用一份**临时 global config** 造重写（不动本机真实的 git 配置）。
    """
    real = tmp_path / "real-target.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(real)], check=True, capture_output=True)
    alias = "alias:seal-ledger"
    config = tmp_path / "gitconfig"
    config.write_text(f'[url "{real}"]\n\tinsteadOf = {alias}\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "no-system-config"))
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, alias)

    root = _sealed_run(tmp_path, name="daily-991")
    block = run_seal.load_manifest(root)["anchor"]
    assert block["replication"] == "pushed", block
    assert block["remote"] == str(real), block          # 解析后的真实落点，不是 alias 串

    listed = subprocess.run(["git", "-C", str(real), "ls-tree", "-r", "--name-only", "main"],
                            capture_output=True, text=True, check=True).stdout
    assert run_seal.anchor_file_for(root).name in listed, listed


# ── ⑰ 第八轮复核 major：no-op push 不许记 pushed + 跨进程锁 ─────────────────────


def test_a_noop_push_is_not_recorded_as_pushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git push` 返回 0 但**什么都没推**（"Everything up-to-date"）时，不许记 `pushed`。

    第八轮复核 major 的实测形态：换账本那一支的 `rmtree` 会删掉**另一个 seal 进程**正在用的
    工作副本，那个进程随后的 `git push origin main:main` 退化成 no-op 且 rc=0，于是清单与锚点
    文件双双写 `offhost-snapshot / replication=pushed`——而它的锚点在**新旧账本里都不存在**。
    读回核对（`_confirm_anchor_on_ledger`）把这一类整片堵死：先把 push 打桩成"rc=0 但不推"，
    断言落 `failed` 而不是 `pushed`。
    """
    remote = _bare_ledger(tmp_path)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))

    def noop_push(work: Path, *, env) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["git", "push"], returncode=0, stdout="Everything up-to-date\n", stderr="")

    monkeypatch.setattr(run_seal, "_push_ledger", noop_push)

    root = _sealed_run(tmp_path, name="daily-997")
    block = run_seal.load_manifest(root)["anchor"]
    assert block["replication"] == "failed", block
    assert "读回" in block.get("reason", ""), block
    assert run_seal.read_anchor(root)["replication"] == "failed", run_seal.read_anchor(root)


def test_the_ledger_push_takes_a_cross_process_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_replicate_anchor` 必须持跨进程锁：拿不到锁就**有界等待后如实失败**，不并行下去。

    第八轮复核 major 的 ②：换账本的 `rmtree` 不能毁掉别的进程正在用的工作副本。这里在同一个
    进程里持锁（`flock` 按 open file description 计，同进程的第二个 fd 同样会阻塞），断言调用
    在超时后落 `failed`；锁一释放，同样一次调用就能真的推上去——证明那次失败只因为没拿到锁。
    """
    remote = _bare_ledger(tmp_path)
    monkeypatch.setenv(run_seal.ANCHOR_PUSH_ENV, str(remote))
    monkeypatch.setattr(run_seal, "LEDGER_LOCK_TIMEOUT_SECONDS", 1)

    anchor_dir = run_seal._anchor_dir()
    anchor_dir.mkdir(parents=True, exist_ok=True)
    blocked = anchor_dir / "daily-999.anchor.json"
    blocked.write_text('{"schema_version": "seal-anchor-v1", "manifest_digest": "z"}\n', encoding="utf-8")

    with run_seal._ledger_lock(anchor_dir):
        replication, detail, _note = run_seal._replicate_anchor(blocked, ident=blocked.name)
        assert replication == "failed", (replication, detail)
        assert "锁" in detail, detail

    free = anchor_dir / "daily-998.anchor.json"
    free.write_text('{"schema_version": "seal-anchor-v1", "manifest_digest": "y"}\n', encoding="utf-8")
    replication, detail, _note = run_seal._replicate_anchor(free, ident=free.name)
    assert replication == "pushed", (replication, detail)
