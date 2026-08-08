# 手机视频批量压缩项目 — 最终交付报告

- 完成时间：2026-08-07
- 执行主机：VM101（飞牛 fnOS NAS，192.168.100.123）
- 控制路径：PVE（192.168.100.254）`qm guest exec 101` → 宿主 python3 + ffmpeg/ffprobe 7.1.3
- 项目状态：**全部完成（压缩 + 三批隔离移动）**

---

## 1. 任务目标

将 `Photos/MobileBackup` 下 7,611 个手机视频（MOV/MP4/M4V）按顶层文件夹顺序、一次一个串行压缩为 H.265（CPU libx265），输出到 `Video-Optimized/Compressed-Videos/`；跳过 Apple Live Photo；manifest 断点续跑；已转成功的源视频经独立审查后移入可恢复隔离区；失败的视频保留。

## 2. 压缩结果（manifest 全量统计）

| 指标 | 数值 |
|---|---|
| 成功转码（completed） | **4,882 条** |
| Live Photo 跳过 | 2,782 条（源目录现存） |
| 失败（保留原位） | **1 条**：`iPhone 17/2026/7/IMG_1401.mov`（11.3 MB，2026-07-12，3 次 failed 事件） |
| 源视频累计大小 | 283.41 GiB |
| 压缩输出大小 | 76.90 GiB |
| **节省** | **206.51 GiB（72.9%）** |
| 批处理运行时长 | 2026-08-06 07:20 → 2026-08-07 01:41（约 18.3 小时，含多次重启/暂停恢复） |

FFmpeg 参数：`-c:v libx265 -crf 25 -preset medium -c:a copy -map 0:v:0? -map 0:a:0? -map_metadata 0 -movflags +faststart -n`

输出命名：`sha256(相对路径)[:16] + '__' + 原文件名`（中文路径全程在 VM101 内处理，不经过 PVE 命令行）

## 3. 三批源视频隔离（可恢复移动，非删除）

| 批次 | 日期 | run-id | 数量 | 大小 | 冻结清单 SHA-256 | L2 审查 |
|---|---|---|---|---|---|---|
| 1 | 08-03 | `delete-557-20260803` | 557 | ~31 GiB | `6739fe67…` | deleg_6c48cbff APPROVE |
| 2 | 08-06 | `delete-completed-20260806` | 3,117 | 186.5 GiB | （同模式） | 同模式执行 |
| 3 | 08-07 | `delete-completed-20260807` | 1,154 | 62.64 GiB | `e58dddcb…` | deleg_6042689b APPROVE |
| **合计** | | | **4,828** | **~280 GiB** | | |

每批模式：预检生成冻结清单（仅 manifest `completed` 且输出 ffprobe 可读，`action=PREVIEW_ONLY_NO_DELETION`）→ SHA-256 锁定 → 独立 L2 审查 → 清单驱动逐条：移动前再验证输出 → `os.replace` 同卷原子移动 → 账本 `movement-ledger.jsonl` + `summary.json` → 核验（隔离缺失 0、大小不符 0、源残留 0、失败文件保留）。

第三批核验实测：ledger_rows=1154 / missing=0 / size_mismatch=0 / source_leftovers=0；源目录剩余 2,783 视频（2,782 Live Photo + 1 失败）✓

## 4. 当前保留在源目录的内容（2,783 条，未动）

- 2,782 条 Live Photo（跳过，未压缩）
- 1 条失败文件：`iPhone 17/2026/7/IMG_1401.mov`

## 5. 关键路径

```
/vol2/1000/Photos/MobileBackup/                    源目录（剩余 2,783 条）
/vol2/1000/Video-Optimized/Compressed-Videos/      输出（4,882 个 .mp4 + manifest/日志/冻结清单）
/vol2/1000/Video-Optimized/scripts/                batch_compress_by_folder_v2.py 等脚本（NAS 持久）
/vol2/1000/Video-Optimized/_source-video-quarantine/
├── delete-557-20260803/          第一批隔离区（557 条）
├── delete-completed-20260806/    第二批隔离区（3,117 条）
└── delete-completed-20260807/    第三批隔离区（1,154 条）
```
本地脚本镜像：`/home/allen/Projects/ruoyu-film-daily/scripts/`

## 6. 空间说明

- 隔离区共约 **280 GiB 未释放**：空间仅在手动清空三个隔离目录后回收（设计内，可恢复）
- NAS 当前可用：~659 GB（阈值 100 GB）

## 7. 遗留事项与提示

1. **失败文件** `IMG_1401.mov` 若需修复：检查源文件完整性后重新跑批处理即可（manifest 断点续跑，`-n` 防覆盖）
2. **NAS 地址变更**：2026-08-07 审查确认 NAS 现为 **192.168.100.123**（旧 .223 已失效）；本项目 memory 已更新，活跃配置无旧地址引用；`ruoyu-content` 等文档中的 `.223` 为历史陈述，未改动
3. **VM101 稳定性**：8-06 曾 1 小时内重启 3 次（`/tmp` 被清导致脚本丢失）→ 已解决：脚本部署至 NAS 持久路径；`hermes-gateway` 服务曾失败循环（203/EXEC），需留意
4. **隔离区空间**：确认无误后清空三个 `_source-video-quarantine/delete-*/` 目录即回收 ~280 GiB（清空前请保留审计文件或确认压缩副本可读）
5. 压缩副本 4,882 个 `.mp4` 全部独立 ffprobe 验证可读（每批预检 verify_fail=0）

## 8. 审计文件

- 冻结清单：`Compressed-Videos/_deletion-preflight-completed-20260807.json`（SHA-256 `e58dddcb…`）
- 移动账本：`delete-completed-20260807/movement-ledger.jsonl`（每行：at/event/source/destination/source_bytes）
- 批处理日志：`Compressed-Videos/_batch-run.log`（含 summary 块）
- 审查记录：`/home/allen/Projects/ruoyu-film-daily/independent-l2-review.md`（第一批）；deleg_6042689b（第三批，transcript: `/home/allen/.hermes/cache/delegation/live/deleg_6042689b/task-0.log`）
