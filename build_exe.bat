@echo off
REM PyInstaller로 독립 실행 파일(.exe) 빌드.
REM 빌드 후 dist\박사논문워크벤치\박사논문워크벤치.exe 를 더블클릭하면 바로 실행.

setlocal
cd /d "%~dp0"

if not exist ".venv" (
    echo [error] 먼저 run.bat 을 한 번 실행해 가상환경을 생성하세요.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo [build] PyInstaller 설치 중...
python -m pip install pyinstaller

echo [build] 실행 파일 빌드 중 (2~3분 소요)...
pyinstaller --noconfirm --windowed --name "박사논문워크벤치" ^
    --add-data "paper_writer;paper_writer" ^
    --hidden-import paper_writer.codebook ^
    --hidden-import paper_writer.analyzer ^
    --hidden-import paper_writer.extractor ^
    --hidden-import paper_writer.xlsx_io ^
    --hidden-import paper_writer.pdf_reader ^
    --hidden-import paper_writer.library ^
    --hidden-import paper_writer.notebook ^
    --hidden-import paper_writer.data_summary ^
    --hidden-import paper_writer.writing_project ^
    --hidden-import paper_writer.drafter ^
    --hidden-import paper_writer.paper_cli ^
    paper_writer\__main__.py

if errorlevel 1 (
    echo 빌드 실패.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   빌드 완료!
echo   dist\박사논문워크벤치\박사논문워크벤치.exe
echo   이 파일을 더블클릭하면 바로 실행됩니다.
echo ========================================
echo.
pause

endlocal
