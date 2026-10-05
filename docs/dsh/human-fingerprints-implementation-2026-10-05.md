# 文章组人工特征注入与脱敏自愈工程实施落地记录

- **实施日期**：2026-10-05
- **实施依据**：Controller 质询（/grill-me）共识 + Vault《人工创作特征注入规范与解说小子文风迁移指南》（candidate）
- **核心目标**：根除微信公众平台“未发现明显人工创作特征/低创作度内容”拦截，确保腾讯朱雀全绿，将 Ulysses 解说小子 6 大人工指纹机械化注入日常产线。

---

## 一、 交付与变更清单

### 1. 骨架与前置台账层
- `article_group/article_skeleton.py`：
  - 新增 `opening_hook`（开篇极端反差动作钩子，≤30字 CJK）；
  - 新增 `realistic_stakes`（切肤现实账本，≥1项普通人饭碗生计/家庭/编制/违约金代价）；
  - `build_skeleton` 与 CLI 输出支持完整人工特征字段。
- `article_group/prewrite.py`：
  - 新增 `validate_opening_hook()`：防首段宏观套话（“近年来/随着...发展”），确保动作破题；
  - 新增 `validate_realistic_stakes()`：确保切肤现实利益账本真实在正文兑现；
  - 在 `validate_article_stage` 中闭环同步调用，与 `sensory_anchors` 保持同等强约束校验。

### 2. 题材自适应语料库 (Dynamic Few-Shot Registry)
- `article_group/prompts/human_fingerprints/registry.py`：
  - 沉淀四大题材 Ulysses 真实定稿语料卡片：
    - `crime_suspense`（《三大队》《迷宫游戏》）
    - `social_realism`（《第二十条》《老狐狸》）
    - `business_workplace`（《老狐狸》商战/利益算盘）
    - `female_literary`（《香魂女》《窗边的小豆豆》）
  - 提供 `get_human_fingerprints_instruction(topic_or_genre)` 动态注入接口。

### 3. 脱敏整形与朱雀靶向自愈流水线
- `article_group/humanize_pipeline.py`：
  - 阶段 1：确定性规则整形（切除文末客服互动套话、清除 AI 典型套话与公关黑话、打碎二元对仗句式、首段动作化重塑）；
  - 阶段 2：本地双门禁前置检验（`anti_ai_gate` < 45.0 + 台账兑现检查）；
  - 阶段 3：朱雀大模型检测与靶向自愈（调用 EdgeOne API 或自动回退至本地 Web Matrix CLI，对高危句子进行断句与口语重构，最多 2 轮自愈，熔断安全退出）。

### 4. 自动化测试与验证
- `tests/test_humanize_pipeline.py`：
  - 7 个完整测试用例 100% PASS；
  - `tests/test_prewrite_contract.py`（76 项向后兼容测试 100% PASS）。
- A/B 穿透测试报告：
  - 见 `/home/allen/dsh/experiments/humanize_test/HUMANIZE-EVALUATION-REPORT.md`；
  - 本地综合 AI 味从 28.3 降至 20.7，标点呼吸感从 85.0 改善至 10.0；
  - 真实朱雀检测 0 高危疑似 AI，达成全绿标杆。

### 5. 技能与 SOP 同步
- `~/.agents/skills/ruoyu-article-production/SKILL.md` 已加入 `Humanize Pipeline & Self-Healing Execution` 标准步骤。
