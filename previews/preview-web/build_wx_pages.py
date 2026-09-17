#!/usr/bin/env python3
"""Wrap WenYan-rendered WeChat HTML into a one-click-copy page.

The clipboard API needs a secure context, so the button uses the classic
selection + document.execCommand('copy') path, which works over plain http on
a LAN. The article itself keeps its inline styles, so pasting into 公众号后台
retains the layout.

路径由脚本自身位置推导（Linux 原生）：ROOT = 本脚本所在目录，
输入 wx/*.wx.html 与输出 wx/*.html 都在 ROOT/wx/ 下。
"""
from __future__ import annotations

import html
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
WX = ROOT / "wx"

# 文颜 / doocs-md 编辑器地址（渲染机，默认本机；可用环境变量覆盖）
MD_EDITOR_URL = os.environ.get("MD_EDITOR_URL", "http://192.168.100.168:8080/")

PAGES = [
    ("art-001", "art-001.wx.html", "《让子弹飞》之后，姜文为什么一部比一部拧巴", "default 主题 · 1032 字"),
    ("art-002", "art-002.wx.html", "《还珠格格》第三部为什么像另一部剧", "default 主题 · 935 字"),
    ("art-001-pie", "art-001.pie.html", "《让子弹飞》之后，姜文为什么一部比一部拧巴", "pie 主题（备选） · 1032 字"),
]

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 公众号复制版</title>
<style>
 body{{margin:0;background:#f4f4f2;font-family:-apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif}}
 .bar{{position:sticky;top:0;z-index:9;display:flex;gap:.6em;align-items:center;flex-wrap:wrap;
   padding:.7em 1em;background:#1f2023;color:#fff;font-size:14px}}
 .bar b{{font-weight:600}}
 .bar span{{color:#aaa}}
 button{{font:inherit;font-size:14px;padding:.45em 1em;border-radius:6px;border:0;cursor:pointer;
   background:#07c160;color:#fff}}
 button.ghost{{background:#3a3b3f;color:#ddd}}
 button:active{{transform:translateY(1px)}}
 .hint{{padding:.6em 1em;background:#fffbe6;color:#7a5b00;font-size:13px;border-bottom:1px solid #f0e6c8}}
 .hint code{{background:#f4ecd8;padding:.1em .35em;border-radius:3px}}
 .sheet{{max-width:720px;margin:1.4em auto 4em;background:#fff;border-radius:10px;
   box-shadow:0 1px 3px rgba(0,0,0,.08);padding:2.2em 1.6em}}
 .toast{{position:fixed;left:50%;bottom:2em;transform:translateX(-50%);background:#1f2023;color:#fff;
   padding:.6em 1.2em;border-radius:20px;font-size:14px;opacity:0;transition:opacity .25s;pointer-events:none}}
 .toast.on{{opacity:.95}}
 @media (max-width:600px){{.sheet{{margin:0;border-radius:0;padding:1.2em 1em}}}}
</style></head>
<body>
<div class="bar">
  <b>{label}</b><span>{note}</span>
  <button onclick="copyArticle()">复制全文（含样式）</button>
  <button class="ghost" onclick="location.href='/wx/'">← 返回列表</button>
  <button class="ghost" onclick="location.href='{md_editor}'">用 doocs/md 编辑器改</button>
</div>
<div class="hint">点「复制全文」后，直接到公众号后台正文里 <code>Cmd/Ctrl+V</code> 粘贴即可（样式已内联）。
若浏览器拦截剪贴板，就在下面文章区域 <code>Cmd/Ctrl+A</code> 全选、<code>Cmd/Ctrl+C</code> 复制。</div>
<div class="sheet"><div id="wx-article">{body}</div></div>
<div class="toast" id="toast">已复制，去公众号后台粘贴吧</div>
<script>
function toast(msg){{
  const t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('on'); setTimeout(()=>t.classList.remove('on'),1800);
}}
function copyArticle(){{
  const node=document.getElementById('wx-article');
  const range=document.createRange(); range.selectNodeContents(node);
  const sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
  let ok=false;
  try{{ ok=document.execCommand('copy'); }}catch(e){{ ok=false; }}
  sel.removeAllRanges();
  if(ok){{ toast('已复制，去公众号后台粘贴吧'); }}
  else if(navigator.clipboard && window.isSecureContext){{
    const blob=new Blob([node.innerHTML],{{type:'text/html'}});
    navigator.clipboard.write([new ClipboardItem({{'text/html':blob}})]).then(
      ()=>toast('已复制，去公众号后台粘贴吧'), ()=>toast('浏览器拦截了剪贴板，请手动全选复制'));
  }} else {{
    toast('浏览器拦截了剪贴板，请手动 Cmd/Ctrl+A 全选复制');
  }}
}}
</script>
</body></html>
"""

INDEX = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>公众号复制版 · daily-008</title>
<style>
 body{{max-width:760px;margin:2.5em auto;padding:0 1.2em;font-family:-apple-system,"PingFang SC",sans-serif;line-height:1.9}}
 a{{color:#0a58ca}} li{{margin:.5em 0}} .meta{{color:#777;font-size:.88em;margin-top:3em}}
</style></head><body>
<h1>公众号复制版 · daily-008</h1>
<p>打开任一链接 → 点「复制全文（含样式）」→ 到公众号后台正文粘贴。样式已内联，链接自动转脚注。</p>
<ul>
{items}
</ul>
<p class="meta">渲染：文颜 CLI（Apache-2.0，内置主题）· 未发布，publication_authorization: not_authorized</p>
</body></html>
"""


def main() -> None:
    WX.mkdir(parents=True, exist_ok=True)
    items = []
    for slug, source, label, note in PAGES:
        src = WX / source
        if not src.exists():
            # 缺源不阻断：pie 备选主题的 .pie.html 会被 sync_wx.sh 的 rm -f 清掉，
            # 从未渲染过时也必须能出页面。
            print(f"note: {src} 不存在，跳过 {slug}（需先跑 render_wx.sh 生成文颜版）")
            continue
        body = src.read_text(encoding="utf-8")
        page = TEMPLATE.format(title=html.escape(label), label=html.escape(label),
                               note=html.escape(note), md_editor=MD_EDITOR_URL, body=body)
        (WX / f"{slug}.html").write_text(page, encoding="utf-8")
        items.append(f'<li><a href="/wx/{slug}.html">{html.escape(label)}</a> — {html.escape(note)}</li>')
        print("written", WX / f"{slug}.html")
    (WX / "index.html").write_text(INDEX.format(items="\n".join(items)), encoding="utf-8")
    print("written", WX / "index.html")


if __name__ == "__main__":
    main()
