#!/usr/bin/env python3
"""词库（`wordlists/`）候选词挖掘：把候选清单 + 命中数留档，供任何人事后复算。

## 为什么要单独挖词库，而不是继续加 `my-rules.md` 黑名单？

上游 `scan.py` 两条通道的语义不同（`scan.py:137-165` / `:215-232`）：

| 通道 | 写法 | 匹配 | 门控 | 档位 |
|---|---|---|---|---|
| `my-rules.md` 黑名单 | **正则**（第一列） | `re.compile(..., re.I)` | 无（不看商业属性） | 每行自带 `见词即报/语境判` |
| `wordlists/*.md` / `*.txt` | **纯字面词** | `re.escape(term)` + `re.I` | 无 | 固定 `中` / `mode=semantic`（语境判） |

所以词库适合放**字面词**：不需要正则能力、又不该被商业属性门控的词。
第 9 轮补的 13 行黑名单是"正则 + 作者动作"；词库这一层此前**从未开火**
（`wordlist_terms=0`），本脚本负责把候选词一条条量出来，只收 0 误报的。

## 口径（与 `publish_precheck_blacklist_mining.py` 完全一致）

  自有语料 = `runs/**/draft.md` + `runs/**/body_draft.md`
           + `ruoyu-content/03-article-corpus/{social,film}/**` + `ruoyu-content/05-drafts/**`
  对照语料 = `ruoyu-content/10-case-library/writing-dna/raw-corpus/`（**顶层** `iterdir()`）

入选判据（全部满足才收）：① 自有语料 0 命中；② 对照语料 0 命中；
③ 不是常用词的子串（例如 `威信`＝"威信扫地"、`秒杀`/`拼单` 在行业分析里合法）；
   ③b **只收"作者对读者发出的动作/界面形态"字面词，不收行业·题材现象词**（第 13 轮 F-2：`一手货源`
      这类 B2B 口径虽然两语料 0 命中，但剧情转述里会出现，与 `招商加盟`/`秒杀` 同类，一并**不收**）；
   ③c **不重复官方已无条件覆盖的面**（第 13 轮 F-1：`general-community-safety.G09`
      `commercial_only=false` / `critical`，pattern 含 `手机号|微信号` —— 非商业档联系方式面**不是盲区**，
      故 `微信号`/`手机号` 零边际检出，**不收**）；
④ 与我们自己的定稿排版规范不冲突（关闭/在看/蓝字族一律不收 —— 文末关注大卡就是那么写的）。

本脚本**只读**，不写任何仓库文件，也不放在 `references/publish-precheck/`（那是
`rules_identity()` 扫的纯数据目录，放 `.py` 会因 `__pycache__` 顶歪 `dir_sha256`）。

用法：`.venv/bin/python scripts/publish_precheck_wordlist_mine.py`
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path("/home/allen/Projects/ruoyu-film-daily")

GROUPS: dict[str, list[str]] = {
    "E 绕审/变体联系方式写法": [
        "薇信", "嶶信", "唯信", "威信", "威信同号", "薇信同号", "微我", "扣扣", "扣我",
        "企鹅号", "v信", "V信", "加微", "薇❤",
    ],
    "F 站外账号引导短语": [
        "同名公众号", "公众号同名", "全网同名", "同名微博", "同名抖音", "同名快手",
        "同名小红书", "我的抖音", "我的快手", "我的微博", "我的小红书", "主页同名",
        "主页简介", "个人简介里", "置顶评论", "置顶里有", "第一条评论", "评论区置顶",
        # 第 13 轮补：同族平台枚举原本漏了微信视频号与今日头条（恰是本层要覆盖的两个平台）
        "同名视频号", "同名头条号", "同名B站", "同名知乎", "同名微信",
        "我的视频号", "我的头条号", "我的B站", "我的知乎", "我的微信",
    ],
    "G 交易黑话（账号级交易风险）": [
        "刷单", "返利", "薅羊毛", "一手货源", "代购", "微商", "带货佣金", "佣金链接",
        "拼单", "拼团", "砍一刀", "砍价链接", "助力链接", "招商加盟", "代理加盟",
        "招代理", "发展下线", "拉人头", "引流", "变现", "私域", "免单", "秒杀",
        "抢购", "限时秒杀", "包邮", "下单链接", "库存告急", "最后一天",
    ],
    "H 联系方式数字（对照组，预期不收）": [
        "微信号", "手机号", "电话号码", "联系方式",
    ],
}


def _chars(files: list[pathlib.Path]) -> int:
    """字节数之外也给**字符数**（第 13 轮 F-4：文件数可复算、字符数过去印不出来）。"""
    return sum(len(p.read_text(encoding="utf-8", errors="replace")) for p in files)


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
            acc[w] += len(re.findall(re.escape(w), text, re.IGNORECASE))
    return acc


def main() -> None:
    own, ext = own_files(), ext_files()
    all_words = [w for words in GROUPS.values() for w in words]
    print(f"自有语料：{len(own)} 文件 / {_chars(own)} 字符")
    print(f"对照语料：{len(ext)} 文件 / {_chars(ext)} 字符")
    print(f"候选词总数：{len(all_words)}（{len(GROUPS)} 组）\n")

    own_acc = count(own, all_words)
    ext_acc = count(ext, all_words)
    for group, words in GROUPS.items():
        hits = [w for w in words if own_acc[w] or ext_acc[w]]
        print(f"[{group}] 候选 {len(words)} 个，出现过的 {len(hits)} 个")
        for w in words:
            if own_acc[w] or ext_acc[w]:
                print(f"    {w:<12} 自有 {own_acc[w]:>4}  对照 {ext_acc[w]:>4}")
        zero = [w for w in words if not own_acc[w] and not ext_acc[w]]
        print(f"    两语料 0 命中（可入选）：{' / '.join(zero) or '无'}\n")

    clean = [w for w in all_words if not own_acc[w] and not ext_acc[w]]
    print(f"合计两语料 0 命中：{len(clean)} / {len(all_words)}")
    print("  " + " / ".join(clean))


if __name__ == "__main__":
    main()
