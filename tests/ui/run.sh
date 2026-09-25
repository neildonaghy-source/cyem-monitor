#!/bin/sh
# EMO browser smoke test against the running box (private workspace uitest1). ~3 min.
cd "$(dirname "$0")" && mkdir -p out && docker run --rm --network host -v "$PWD":/t -v "$PWD/out":/out -w /t mcr.microsoft.com/playwright/python:v1.47.0-jammy sh -c "pip install -q playwright==1.47.0 >/dev/null 2>&1; python emo_smoke.py"
