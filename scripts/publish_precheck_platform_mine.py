#!/usr/bin/env python3
"""平台官方规则轮（2026-10-16）的候选词面**误报测量**脚本 —— 只读，可原样复算。

背景：Allen 2026-10-16 指示"去搜索一下"平台官方规则（见
`docs/dsh/publish-precheck-advisory-2026-10-15.md` §12）。本轮从微信《运营规范》官方页与头条官方域
摘出候选词面，**先在本仓语料上量误报**再决定收不收。本脚本就是那次测量的留档（第 9 轮复核对
`R9-06` 指出：原脚本只落在 `/tmp/plat/mine_platform.py`，违反 `~/.dsh/AGENTS.md` §5
"项目级证据禁止落 /tmp"，故移进仓库，放在 `publish_precheck_blacklist_mining.py` 旁边）。

口径与 `publish_precheck_blacklist_mining.py` **一致**：自有语料 = 220 文件（`own_files()`），
对照语料 = 154 文件（`ext_files()`）。判定标准：候选词面必须在两组里**都 0 命中**才可能入选。

用法（只读，不写任何仓库文件）：

    uv run python scripts/publish_precheck_platform_mine.py

结论（2026-10-16 实测）：本脚本列的候选里，唯一在自有语料命中的是**手机号正则**
`1[3-9]\\d{9}` —— 1 处，位于 `ruoyu-content/03-article-corpus/film/2026-05-26/a-ma-boxoffice-150b.md`
第 4 行的原文链接 `https://m.bjnews.com.cn/detail/1779513861129670.html`（`17795138611` 是 16 位
URL 数字 ID 的前 11 位，**不是票房数字串** —— 第 9 轮复核纠正了文档原先的措辞）。该条因此**未入选**；
其余候选（诱导分享/利诱/紧迫感/分销/关注族等）在两组里均为 0。
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts.publish_precheck_blacklist_mining import count, ext_files, own_files  # noqa: E402

#: 2026-10-16 从平台官方规则里摘出的候选（诱导分享 / 利诱分享关注 / 紧迫感 / 分销 / 关注族 / 旁证类）
WORDS: list[str] = [
    "不转不是", "必转", "转疯了", "转发后", "请好心人转发", "转发朋友圈", "分享到朋友圈",
    "集赞", "点赞", "关注后", "关注公众号", "点击上方", "蓝字", "搜一搜",
    "拉人头", "发展下线", "多级分销", "传销", "看广告", "领红包", "抽奖", "看完即删",
    "内部消息", "机密", "二维码", "加V", "认证账号",
    # 第 9 轮复核给出的官方逐字词面（本轮增补正式采用前也一并量过）
    "拆礼盒", "分享至朋友圈", "分享可增加一次抽奖机会",
]

#: 官方 R05 已覆盖、但只看商业模式的形态；单独用正则量它的误报
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")


def main() -> None:
    own, ext = own_files(), ext_files()
    print(f"自有语料 {len(own)} 文件 / 对照语料 {len(ext)} 文件")
    own_counts, ext_counts = count(own, WORDS), count(ext, WORDS)
    for word in WORDS:
        hits = [p for p in own if word in p.read_text(encoding="utf-8", errors="ignore")]
        example = str(hits[0].relative_to(pathlib.Path(__file__).resolve().parent.parent)) if hits else ""
        print(f"{word:14s} 自有={own_counts.get(word, 0):4d}（{len(hits):2d} 篇） 对照={ext_counts.get(word, 0):4d}  {example}")

    for label, files in (("自有", own), ("对照", ext)):
        total, examples = 0, []
        for path in files:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in PHONE_PATTERN.finditer(text):
                total += 1
                if len(examples) < 3:
                    examples.append(f"{path.name}:{match.group()}")
        print(f"[手机号 1[3-9]\\d{{9}}] {label} 命中={total} 例={examples}")


if __name__ == "__main__":
    main()
