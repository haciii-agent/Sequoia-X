cd /d D:\hermes\seq-tmp
echo [%date% %time%] 启动快速回填...
uv run python fast_backfill.py
echo.
echo [%date% %time%] 完成！
pause