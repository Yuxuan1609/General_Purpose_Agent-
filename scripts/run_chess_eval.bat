@echo off
setlocal
set "PROJECT_ROOT=C:\Users\micha\PycharmProjects\cognitive-agent"
set "OUTDIR=%PROJECT_ROOT%\experiment_results\chess_tools_eval"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

pushd "%PROJECT_ROOT%"

echo [%time%] Launching 5 eval sessions (1000/1200/1400/1600/1800)...

start /b cmd /c "python scripts\run_chess_experiment.py --group eval --eval-elo 1000 --games 1 --out-dir "%OUTDIR%" > "%OUTDIR%\elo_1000.log" 2>&1"
echo   launched elo_1000
ping -n 11 127.0.0.1 >nul

start /b cmd /c "python scripts\run_chess_experiment.py --group eval --eval-elo 1200 --games 1 --out-dir "%OUTDIR%" > "%OUTDIR%\elo_1200.log" 2>&1"
echo   launched elo_1200
ping -n 11 127.0.0.1 >nul

start /b cmd /c "python scripts\run_chess_experiment.py --group eval --eval-elo 1400 --games 1 --out-dir "%OUTDIR%" > "%OUTDIR%\elo_1400.log" 2>&1"
echo   launched elo_1400
ping -n 11 127.0.0.1 >nul

start /b cmd /c "python scripts\run_chess_experiment.py --group eval --eval-elo 1600 --games 1 --out-dir "%OUTDIR%" > "%OUTDIR%\elo_1600.log" 2>&1"
echo   launched elo_1600
ping -n 11 127.0.0.1 >nul

start /b cmd /c "python scripts\run_chess_experiment.py --group eval --eval-elo 1800 --games 1 --out-dir "%OUTDIR%" > "%OUTDIR%\elo_1800.log" 2>&1"
echo   launched elo_1800

popd

echo [%time%] All 5 eval sessions launched in background.
echo Logs:
echo   %OUTDIR%\elo_1000.log
echo   %OUTDIR%\elo_1200.log
echo   %OUTDIR%\elo_1400.log
echo   %OUTDIR%\elo_1600.log
echo   %OUTDIR%\elo_1800.log
