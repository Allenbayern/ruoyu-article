# 社会话题五道门声明（social_topic 候选用）

**何时需要**：候选池里任一候选的 `topic_type` 为 `social` 时，该候选必须携带
`five_gates` 结构化声明；`article_group.run_gates` 会跑
`validate_pool_five_gates` 真校验（硬错误即阻断 run），`crosscheck_pool_five_gates`
关键词交叉核对只作警告、不阻断。影视日常候选不携带此声明，run 报告按
`compliance_gate: not_run` 显式记录。

**声明形状**（放在 candidate-pool 的该候选对象里）：

```json
{
  "candidate_id": "cand-xxx",
  "topic_type": "social",
  "five_gates": {
    "gate1_news_license": "PASS",
    "gate2_privacy": "PASS",
    "gate3_judicial": "PASS",
    "gate4_copyright": "PASS",
    "gate5_sensationalism": "PASS",
    "overall": "PASS"
  },
  "recommendation": "A",
  "compliant_angle": "仅在 overall=CONDITIONAL 且 recommendation 为 A/B/C 时必填"
}
```

**五门含义**（见 Vault《Hermes Article Group Operating Rules》"社会热点五道门"）：

1. `gate1_news_license` 新闻资质 —— 是否涉及新闻式复述，需新闻资质才能报道？
2. `gate2_privacy` 隐私 —— 涉及普通人悲剧隐私或隐私依赖题材？
3. `gate3_judicial` 司法 —— 涉及未决司法纠纷？
4. `gate4_copyright` 版权 —— 涉及媒体独家调查或版权保护内容？
5. `gate5_sensationalism` 猎奇 —— 以猎奇为导向，缺乏影视内容锚点？

**硬规则**（`validate_five_gates` 强制，违反即错误）：

- 每门取值只能是 `PASS` / `CONDITIONAL` / `FAIL`；
- `overall` 必须与逐门声明一致（任一 FAIL → overall FAIL；有 CONDITIONAL 无 FAIL
  → overall CONDITIONAL；全 PASS → overall PASS）；
- `recommendation` 必须是 `A/B/C/Archive/Reject/Wait` 之一；
- overall FAIL 时不得推荐 A/B/C；
- overall CONDITIONAL + A/B/C 必须给出 `compliant_angle`（可选角度库见
  `article_group/compliance_gate.py::PREDEFINED_ANGLES`）。

任何一道门亮红灯：宁降 H4 也不空泛凑数（Vault 原话）。S1 控制器的声明是权威；
关键词交叉核对只是辅助，绝不单独阻断。
