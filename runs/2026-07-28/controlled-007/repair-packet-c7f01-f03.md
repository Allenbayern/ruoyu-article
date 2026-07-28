# controlled-007 repair packet (C7-F01 / C7-F02 / C7-F03)

## Sol
- delegation: `deleg_5c7fa621`
- decision: `needs_changes`
- accepted IDs: C7-F01, C7-F02, C7-F03 (all major)

## Repairs
### C7-F01 (A 网友留言)
- Sol 认为留言无源；本地复核 **src-A01 北青网转述** 含“必须和搭子一起去看”“打工人的发疯图鉴”“笑到饮料都拿不稳了”。
- 修复：正文改为明确“北青网转述点映后的网友留言…媒体汇总样本，不是全网统计”；新增 **A13 attribution** → `src-A01` locator `必须和搭子`。

### C7-F02 (B 软因果 / 虚构观众路径)
- 删除“朋友说更好笑 / 二刷 / 安利两次以上”等无源行为路径。
- 将“口碑→上座→排片→冠军”改为：公开数据只并置评分/上座/票房，**无完整因果证明链**。
- 保留 B12 inference，limitation 写明边界。

### C7-F03 (C 最低票房纪录)
- 正文改为引号归属澎湃：“创下追光动画近年作品的最低票房纪录”。
- 新增 **C13 attribution** → `src-C03` locator `最低票房纪录`；evidence/brief 纳入 C03。

## Post-repair mechanical
- validate_batch []
- plain []
- source []
- claim inv/loc []
- chars A/B/C ≥1500（目标约 1800）
- state: **R7 mechanically-verified only**
- publication: **not_authorized**

## Recheck scope for Sol
**本轮只复核 C7-F01、C7-F02、C7-F03** 是否 fixed；禁止扩大 scope；不得授权发布。
