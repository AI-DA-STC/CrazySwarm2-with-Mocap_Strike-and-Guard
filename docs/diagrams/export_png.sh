#!/usr/bin/env bash
# Re-export every slide of strike-and-guard-diagrams.pptx as the PNG the docs embed.
#
#   ./docs/diagrams/export_png.sh
#
# strike-and-guard-diagrams.pptx is the SOURCE of every diagram in docs/. Edit it in
# PowerPoint (or LibreOffice Impress), save, then run this. One slide = one
# diagram; the file names below are in slide order, so if you add, remove or
# reorder slides, update NAMES to match.
#
# Needs LibreOffice (soffice) and poppler-utils (pdftoppm).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMES=(
  01-at-a-glance 02-system 03-decision-loop 04-rotate-not-swap
  05-rest-vs-blocking 06-when-to-block 07-speed-budget 08-inside-track
  09-safety-layers 10-show-sequence 11-light-legend 12-flight-day
  13-safety-filter 14-command-modes 15-attacker 16-controller-step
  17-control-tick 18-verification 19-lessons 20-lab-network
  21-two-demos 22-stl-at-a-glance 23-stl-plan-then-fly 24-stl-sequence 25-stl-lights
)

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

soffice --headless --convert-to pdf --outdir "$TMP" "$HERE/strike-and-guard-diagrams.pptx" >/dev/null
pdftoppm -png -r 120 "$TMP/strike-and-guard-diagrams.pdf" "$TMP/slide"

shopt -s nullglob
slides=("$TMP"/slide-*.png)
if [ "${#slides[@]}" -ne "${#NAMES[@]}" ]; then
  echo "error: the deck has ${#slides[@]} slides but NAMES lists ${#NAMES[@]}" >&2
  exit 1
fi
for i in "${!slides[@]}"; do
  cp "${slides[$i]}" "$HERE/${NAMES[$i]}.png"
done
echo "wrote ${#slides[@]} PNGs to $HERE"
