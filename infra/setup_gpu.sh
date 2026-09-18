#!/bin/sh
set -eu
mkdir -p "$HOME/bharat-talaash/automation" "$HOME/bharat-talaash/matching" "$HOME/bharat-talaash/ai" "$HOME/bharat-talaash/cache"
python3 -m venv "$HOME/bharat-talaash-gpu"
. "$HOME/bharat-talaash-gpu/bin/activate"
python -m pip install --upgrade pip
python -m pip install boto3 numpy sentence-transformers fastapi uvicorn
