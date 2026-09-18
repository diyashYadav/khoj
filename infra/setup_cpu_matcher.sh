#!/bin/sh
set -eu
mkdir -p "$HOME/Khoj/matching" "$HOME/Khoj/cache"
python3 -m venv "$HOME/Khoj-cpu312"
. "$HOME/Khoj-cpu312/bin/activate"
python -m pip install --upgrade pip
python -m pip install boto3 numpy sentence-transformers fastapi uvicorn

