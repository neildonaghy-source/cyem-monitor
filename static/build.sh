#!/bin/sh
# Rebuild static/app.js from the section sources in static/src (edit those, then run this).
cd "$(dirname "$0")" && cat src/*.js > app.js && node --check app.js && echo "app.js built from $(ls src/*.js | wc -l) sections"
