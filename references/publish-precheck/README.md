# 发布前审 · 项目规则数据（用户资产，tracked）

这里是 `third_party/yuwen-publish-precheck`（发布前审 skill）的 `data/` 目录内容，
**归属文章组、进 Git**，与 vendor 代码物理分离：

- vendor 代码（只读、可整目录升级）：`third_party/yuwen-publish-precheck/`
- 我们的规则与沉淀（本目录）：`references/publish-precheck/`

适配器 `article_group/publish_precheck.py` 调用时会建一个临时工作目录，把 vendor 的
`scripts/`（`scan.py` + `terms.json`）复制进去、把本目录挂成它的 `data/`，因此
`scan.py` 读到的是这里的规则，而 vendor 一个字节都不改。

## 为什么不用 vendor 自带的 data/

上游 `.gitignore` 把 `data/*` 排除在版本控制之外（它假设"用户数据只在本地、升级永不触碰"）。
在这里我们**要**跟踪规则，因为这是团队共用的合规沉淀，必须随仓库走、可被下一班次读到；
放在 vendor 里既不会进 Git，也会在升级时被覆盖。

## 文件

| 文件 | 是什么 | 谁写 |
|---|---|---|
| `profile.md` | 账号档案：常发平台 / 内容领域 / 是否强监管 / 商业模式 / 改法偏好 | 人确认；`商业模式` 与资质待 Allen 确认 |
| `my-rules.md` | 个人规则库四区：黑名单（scan 自动盯防）、语义规则（`MY-` 编号）、白名单、语义笔记 | 每次复盘后追加，**改动要留原因** |
| `expressions.md` | 安全表达库：实测可用的改写对（置信等级：实测 > 规则可解释 > 仅观察） | 有实测证据才写"实测"级 |
| `wordlists/*.md` | 大词表，一行一词 `词\|原因`，scan 自动读取 | 导入外部词表时用 |
| `cases/*.md` | 被平台处罚/限流的案例复盘（按 vendor `references/diagnose.md` 模板） | 真实事件，禁止编造 |
| `history/` | 每次审核报告存档 | 适配器/复核产出后落盘 |

## 硬边界（与 vendor 的 SKILL.md 一致，不许放宽）

1. 词面命中≠违规；**零候选≠安全**。候选必须过语义判定。
2. 白名单只降词面误报，**不豁免**法律与平台硬规则。
3. 不给谐音/错字/拼音/拆字/遮挡等绕审手法，也不把它写进 `expressions.md`。
4. 规则只能加严或降噪，不能放行官方规则拦下的内容。
5. 这里的每条规则都要能用 `scan.py` 用测试句实跑验证命中；**没验证过的规则等于没沉淀**。

## 平台覆盖的已知缺口

vendor 现在只有抖音 / 小红书 / 微信视频号三份 platform 规则包，**没有微信公众号、没有今日头条**。
文章组的主战场（公众号长文、头条）只能吃到 `rules-common` / `rules-commercial` 通用层。
这是已知缺口，别把通用层的通过当成平台层的通过。
