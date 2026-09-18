#!/bin/sh
set -eu
mkdir -p "$HOME/bharat-talaash/matching" "$HOME/bharat-talaash/cache"
python3 -m venv "$HOME/bharat-talaash-cpu312"
. "$HOME/bharat-talaash-cpu312/bin/activate"
python -m pip install --upgrade pip
python -m pip install boto3 numpy sentence-transformers fastapi uvicorn
