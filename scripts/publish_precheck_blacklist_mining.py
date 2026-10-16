#!/usr/bin/env python3
"""黑名单候选词挖掘：把"候选模式清单 + 命中数"留档，供任何人事后复算。

背景（第 5 轮规则集复核 F5-02）：`my-rules.md` 里写过"共测 62 个候选模式，
只有 7 个出现"，但清单没留档、不可独立复现。本文件就是那个清单：
四组候选模式（导流与交易 / 效果与收益保证 / 绝对化用语 / 强监管行业）逐条
在我们自己的语料上计数，输出哪些真的出现过。

口径（与 my-rules.md §词频表 一致）：
  自有语料 = runs/**/draft.md + runs/**/body_draft.md
           + ruoyu-content/03-article-corpus/{social,film}/** + ruoyu-content/05-drafts/**
  对照语料 = ruoyu-content/10-case-library/writing-dna/raw-corpus/（**顶层**，即 `iterdir()` 直接取文件；
           不含 `external/` 与 `ruoyu_archive/` 两个子目录 —— 递归口径会把 154 变成 308）
本脚本**只读**，不写任何仓库文件。

用法：.venv/bin/python scripts/publish_precheck_blacklist_mining.py

本文件**刻意不放** `references/publish-precheck/`：那是 `rules_identity()` 扫的纯数据目录，
放一个可导入的 .py 进去，一次 `import` 写出的 `__pycache__/*.pyc` 会把 `file_count` /
`dir_sha256` 顶歪（第 6 轮复核实测：file_count 9→10、dir_sha256 12eef780…→8507036c…）。
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path("/home/allen/Projects/ruoyu-film-daily")

GROUPS: dict[str, list[str]] = {
    "A 导流与交易": [
        "私信我", "私聊我", "私我", "dd我", "加微信", "加我微信", "加个微信", "微信号",
        "微信同号", "加我v", "扫码", "扫二维码", "扫我二维码", "进群", "加群", "粉丝群",
        "看我主页", "主页橱窗", "商品橱窗", "小黄车", "挂车", "带货链接", "淘口令",
        "点击下方链接", "点击链接", "戳下方链接", "点下方链接", "评论区扣", "后台回复",
        "关注后回复", "免费领取", "领取课程", "领取资料", "报名入口", "课程报名",
    ],
    "B 效果与收益保证": [
        "七天见效", "立竿见影", "包过", "保过", "保证有效", "百分百有效", "无副作用",
        "包治", "根治", "稳赚", "稳赚不赔", "月入过万", "月入十万", "轻松月入",
        "一夜暴富", "躺着赚钱",
    ],
    "C 绝对化用语": [
        "最好", "最佳", "最强", "最火", "最红", "最新", "最高", "最低", "最全", "最大",
        "第一", "全网第一", "销量第一", "全球第一", "顶级", "极致", "唯一", "独家",
        "万能", "百分之百", "史上最", "史上最强", "绝无仅有", "史无前例", "国家级",
        "世界级", "限时", "秒杀", "抢购", "全网最",
    ],
    "D 强监管行业": [
        "医疗", "药品", "疗效", "治疗", "投资", "理财", "收益率", "保本", "荐股", "涨停",
        "贷款", "放款", "征信", "学历提升", "代考", "办证", "假证", "保健品",
    ],
}


def own_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for pat in ("draft.md", "body_draft.md"):
        out += [p for p in (REPO / "runs").rglob(pat) if p.is_file()]
    for d in ("03-article-corpus/social", "03-article-corpus/film", "05-drafts"):
        out += [
            p
            for p in (REPO / "ruoyu-content" / d).rglob("*")
            if p.is_file() and p.suffix.lower() in (".md", ".txt")
        ]
    return sorted(set(out))


def ext_files() -> list[pathlib.Path]:
    root = REPO / "ruoyu-content/10-case-library/writing-dna/raw-corpus"
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir() if p.is_file() and p.suffix.lower() in (".md", ".txt")
    )


def count(files: list[pathlib.Path], words: list[str]) -> dict[str, int]:
    acc = {w: 0 for w in words}
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for w in words:
            acc[w] += len(re.findall(re.escape(w), text))
    return acc


def main() -> None:
    own, ext = own_files(), ext_files()
    all_words = [w for words in GROUPS.values() for w in words]
    print(f"自有语料：{len(own)} 文件  对照语料：{len(ext)} 文件")
    print(f"候选模式总数：{len(all_words)}（{len(GROUPS)} 组）\n")

    own_acc = count(own, all_words)
    ext_acc = count(ext, all_words)
    hit_own = [w for w in all_words if own_acc[w]]
    print(f"在自有语料出现过的模式：{len(hit_own)} / {len(all_words)}")
    print(f"  模式            自有    对照")
    for w in hit_own:
        print(f"  {w:<14} {own_acc[w]:>5}  {ext_acc[w]:>6}")
    never = [w for w in all_words if not own_acc[w]]
    print(f"\n自有语料 0 命中：{len(never)} 个模式")
    print("  " + " / ".join(never))
    print(f"\n对照语料出现过的模式：{[w for w in all_words if ext_acc[w]] or '无'}")


if __name__ == "__main__":
    main()
