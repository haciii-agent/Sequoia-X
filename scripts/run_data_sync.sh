#!/usr/bin/env bash
set -euo pipefail

cd /d/hermes/seq-tmp
python scripts/repair_gap_60d_qq.py
uv run python scripts/check_data_health.py
