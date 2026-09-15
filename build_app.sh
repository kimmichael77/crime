#!/usr/bin/env bash
# py2app으로 macOS 독립 실행 앱(.app) 빌드.
# 빌드 후 dist/박사논문워크벤치.app 을 더블클릭하면 바로 실행.
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[error] 먼저 ./run.sh 을 한 번 실행해 가상환경을 생성하세요."
    exit 1
fi

source .venv/bin/activate

echo "[build] py2app 설치 중..."
pip install py2app

# setup.py 생성
cat > setup_app.py << 'PYEOF'
from setuptools import setup

setup(
    app=["paper_writer/__main__.py"],
    name="박사논문워크벤치",
    options={
        "py2app": {
            "argv_emulation": False,
            "packages": ["paper_writer"],
            "includes": [
                "paper_writer.codebook",
                "paper_writer.analyzer",
                "paper_writer.extractor",
                "paper_writer.xlsx_io",
                "paper_writer.pdf_reader",
                "paper_writer.library",
                "paper_writer.notebook",
                "paper_writer.data_summary",
                "paper_writer.writing_project",
                "paper_writer.drafter",
                "paper_writer.paper_cli",
            ],
        }
    },
    setup_requires=["py2app"],
)
PYEOF

echo "[build] macOS 앱 빌드 중 (2~3분 소요)..."
python setup_app.py py2app

rm -f setup_app.py

echo ""
echo "========================================"
echo "  빌드 완료!"
echo "  dist/박사논문워크벤치.app"
echo "  이 앱을 더블클릭하면 바로 실행됩니다."
echo "  Applications 폴더에 복사해두면 편리합니다."
echo "========================================"
echo ""
