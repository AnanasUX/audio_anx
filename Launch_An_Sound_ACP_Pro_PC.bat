@echo off
chcp 65001 >nul
title An Sound ACP Pro PC — Đồng Bộ ACPWorkbench_V2.44.2.exe
echo ==============================================================================
echo   AN SOUND ACP PRO PC — MVSILICON BP1048B2 (ACPWORKBENCH V2.44.2 COMPANION)
echo ==============================================================================
echo [*] Luu y: Bat nguon pin loa truoc khi cam cap Type-C vao PC (khong co 5V VBUS).
echo.
python "%~dp0An_Sound_ACP_Pro_PC.py"
if %errorlevel% neq 0 (
    echo.
    echo [!] Co loi khi khoi chay ung dung.
    pause
)
