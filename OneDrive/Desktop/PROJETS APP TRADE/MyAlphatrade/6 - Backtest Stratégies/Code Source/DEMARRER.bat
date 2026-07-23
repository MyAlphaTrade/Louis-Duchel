@echo off
chcp 65001 >nul
echo ================================================
echo  Strategie Lab A.T - Lancement local
echo ================================================
echo.

cd /d "%~dp0backend"
if not exist ".venv" (
    echo [Backend] Environnement virtuel introuvable — creation...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
)

echo [Backend] Demarrage sur http://localhost:8010 ...
start "Strategie Lab - Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe main.py"

cd /d "%~dp0frontend"
if not exist "node_modules" (
    echo [Frontend] Dependances Node absentes — installation...
    call npm install
)

echo [Frontend] Demarrage sur http://localhost:5173 ...
start "Strategie Lab - Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo Les deux fenetres vont s'ouvrir (backend + frontend).
echo Une fois pretes, ouvre ton navigateur sur : http://localhost:5173
echo.
timeout /t 6 >nul
start "" "http://localhost:5173"
