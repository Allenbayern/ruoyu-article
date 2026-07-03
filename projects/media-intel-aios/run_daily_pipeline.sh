#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
run_daily_pipeline.sh has been archived/deprecated.

This project no longer uses the all-lane daily orchestration wrapper.
Use lane-specific entrypoints instead:
  - ./run_article_lane_pipeline.sh [YYYY-MM-DD]
  - ./run_video_lane_pipeline.sh [YYYY-MM-DD]

Refusing to run the old all-lane pipeline to avoid mixing article/video/manju outputs.
EOF
exit 64
