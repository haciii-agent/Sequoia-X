@echo off
cd /d D:\hermes\seq-tmp
echo [%date% %time%] Starting backfill...
"uv" run python main.py --backfill >> backfill_full.log 2>&1
echo [%date% %time%] Backfill finished with exit code %ERRORLEVEL% >> backfill_full.log
