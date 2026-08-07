# NOT_COPIED — 未随仓库备份的文件清单

本目录是 `media-intel-aios` 的代码/测试/文档备份（2026-08-07 复制）。
以下文件**有意未复制**，仅保留在原工程目录 `/home/allen/Projects/media-intel-aios/`：

## 真实抓取样本（版权/隐私：不进入公开 GitHub 仓库）

| 文件 | 大小 | 内容 |
|---|---|---|
| `article-vault/samples/douban/douban_review_sample_01.html` | 100K | 真实豆瓣影评全文 |
| `article-vault/samples/wechat/wechat_review_sample_02.html` | 3.2M | 真实微信文章 |
| `article-vault/samples/wechat/wechat_grayzone_sample_03.html` | 4.5M | 真实微信灰区样本 |
| `article-vault/samples/vocus/vocus_grayzone_sample_05.html` | 664K | 真实 Vocus 文章 |
| `article-vault/samples/zhihu/zhihu_analysis_sample_01.html` | 192K | 真实知乎回答 |
| `article-vault/samples/toutiao/toutiao_grayzone_sample_03.html` | 80K | 真实头条文章 |
| `story-vault/samples/douban/douban_group_story_sample_02.html` | 336K | 真实豆瓣小组帖 |
| `samples/guduo/index.html` | 72K | 骨朵平台页面快照 |
| `article-vault/samples/douban/douban_user_review_1507540.html` | 3K | 豆瓣风控拦截空页面（无内容） |
| `article-vault/samples/wechat/wechat_user_sample_Z8C4GRoQRS2RAurT9eZkew.html` | 20K | 真实微信用户页面 |
| `article-vault/samples/toutiao/toutiao_review_sample_02.html` | 4K | 真实头条文章《主角》全文快照 |
| `story-vault/samples/netease-renjian/renjian_story_sample_01.html` | 4K | 真实网易人间文章《一个"神探辅警"的堕落》 |
| `samples/xiniu-yule/xiniu_article_sample_01.html` | 1K | 犀牛娱乐真实文章节选（含作者/编辑信息） |
| `article-vault/samples/xhs/xhs_note_raw_real_01.jsonl` | 194B | 真实小红书笔记样本 |
| `article-vault/samples/bilibili/bilibili_video_article_leads_real_01.jsonl` | 1.5K | 真实 B 站视频线索（含作者名与 URL） |
| `article-vault/samples/douyin/douyin_video_article_leads_real_01.jsonl` | 1.9K | 真实抖音视频线索（含作者名与 URL） |

## 排除的目录（运行产物 / 敏感 / 环境）

- `config/`（含 `config/private/zhihu_cookie.txt` 登录凭据，绝不入库）
- `.venv/`、`outputs/`、`tmp/`、`archive/`、`handover-hotspot/`、`deliveries/`
- `e2-current-20260720/`、`e2r-active-20260720/`、`projects/`、`.codegraph/`
- `.pytest_cache/`、`.DS_Store`、`__pycache__/`

## 恢复说明

需要真实样本时，从原目录对应路径复制，或重新抓取。
