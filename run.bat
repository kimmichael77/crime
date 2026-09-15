@echo off
REM Windows 실행 스크립트.
REM 처음 실행 시 가상환경을 만들고 필요한 패키지를 설치한 후 GUI를 띄운다.

setlocal
cd /d "%~dp0"

if not exist ".venv" (
    echo [setup] Python 가상환경을 생성합니다 (.venv)
    python -m venv .venv
    if errorlevel 1 (
        echo Python 3가 설치되어 있는지 확인하세요. https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

echo [setup] 필수 패키지 설치/업데이트 중...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo 패키지 설치 실패. 인터넷 연결을 확인하세요.
    pause
    exit /b 1
)

echo [run] GUI 실행
start "" .venv\Scripts\pythonw.exe -m paper_writer

endlocal
