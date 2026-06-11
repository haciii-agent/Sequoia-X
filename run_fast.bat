@echo off
cd /d D:\hermes\seq-tmp
echo [%date% %time%] Starting fast backfill...
uv run python fast_backfill.py > backfill_result.log 2>&1
echo [%date% %time%] Done! >> backfill_result.log
type backfill_result.log