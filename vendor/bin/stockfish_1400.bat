@echo off
set "SF=C:\Users\micha\AppData\Local\Microsoft\WinGet\Packages\Stockfish.Stockfish_Microsoft.Winget.Source_8wekyb3d8bbwe\stockfish\stockfish-windows-x86-64-avx2.exe"
(
echo setoption name Hash value 256
echo setoption name Threads value 2
echo setoption name UCI_LimitStrength value true
echo setoption name UCI_Elo value 1400
more
) | "%SF%"
