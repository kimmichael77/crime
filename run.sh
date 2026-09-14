#!/usr/bin/env bash
# macOS / Linux 실행 스크립트.
# 처음 실행 시 가상환경을 만들고 필요한 패키지를 설치한 후 GUI를 띄운다.
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[setup] Python 가상환경을 생성합니다 (.venv)"
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[setup] 필수 패키지 설치/업데이트 중..."
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo ""
    echo "  ⚠️  ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다."
    echo "      다음처럼 설정 후 다시 실행하세요:"
    echo "      export ANTHROPIC_API_KEY=\"sk-ant-...\""
    echo ""
fi

echo "[run] GUI 실행"
python -m paper_writer
