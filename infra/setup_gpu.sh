#!/bin/sh
set -eu
mkdir -p "$HOME/Khoj/automation" "$HOME/Khoj/matching" "$HOME/Khoj/ai" "$HOME/Khoj/cache"
python3 -m venv "$HOME/Khoj-gpu"
. "$HOME/Khoj-gpu/bin/activate"
python -m pip install --upgrade pip
python -m pip install boto3 numpy sentence-transformers fastapi uvicorn

