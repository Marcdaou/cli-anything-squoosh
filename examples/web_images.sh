#!/usr/bin/env bash
# Example: prepare web-ready images from a folder of PNGs.
# Usage: ./web_images.sh <input-dir> <output-dir>
set -euo pipefail
IN=${1:?input dir}; OUT=${2:?output dir}
C=cli-anything-squoosh
P="--project $OUT/web.squoosh.json"
mkdir -p "$OUT"

first=$(ls "$IN"/*.png | head -1)
$C $P project new -n web -e webp -s "$first"
$C $P edit resize -w 1280 -m lanczos3
$C $P encoder set webp quality=75 method=6

# Which codec is smallest on a representative image?
$C --json $P compare -d "$OUT/shootout" -e mozjpeg,webp,avif,jxl | python3 -c \
  'import json,sys; r=json.load(sys.stdin); print("smallest:", r["smallest"])'

# Publish a before/after preview bundle, then process everything.
$C $P preview capture
$C $P batch "$IN/*.png" -d "$OUT/webp" --overwrite
