@echo off
setlocal
set "PROJECT_ROOT=C:\Users\micha\PycharmProjects\cognitive-agent"
set "OUTDIR=%PROJECT_ROOT%\experiment_results\chess_e1"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

pushd "%PROJECT_ROOT%"

echo [%time%] Launching BASELINE (resume from G1, elo=600, 9 games left)...
start /b cmd /c "python scripts\run_chess_experiment.py --group baseline --games 10 --resume "%OUTDIR%\baseline\snapshots\snapshot_001" --out-dir "%OUTDIR%" > "%OUTDIR%\baseline_stdout.log" 2>&1"

echo [%time%] Waiting 60 seconds before LEARNING launch...
ping -n 61 127.0.0.1 >nul

echo [%time%] Launching LEARNING (resume from G1, elo=600, 19 games left, with L1+1/L2+5)...
start /b cmd /c "python scripts\run_chess_experiment.py --group learning --games 20 --resume "%OUTDIR%\learning\snapshots\snapshot_001" --out-dir "%OUTDIR%" > "%OUTDIR%\learning_stdout.log" 2>&1"

popd

echo [%time%] Both experiments launched in background.
echo Logs:
echo   %OUTDIR%\baseline_stdout.log
echo   %OUTDIR%\learning_stdout.log
echo Monitor:
echo   python scripts\monitor_chess.py --out-dir "%OUTDIR%"
