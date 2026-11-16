#!/bin/bash
# Cut a filmed take to its match (from MATCH LIVE to a few seconds into the finale), stack
# a title bar above and the legend below, and write the WebP for the docs, an MP4 and a
# contact sheet to check it by eye.
#
#   scripts/footage/cut.sh <name> <out> "<headline>" "<one line>" [seconds of finale, 7]
#   FPS=12 Q=55 (WebP frame rate and quality)
source "$(dirname "$0")/common.sh"
name=$1; out=$2; head=$3; line=$4; tail=${5:-7}
T=$WORK/takes/$name.out
B0=$(ros2 bag info "$WORK/bags/$name" 2>/dev/null | sed -n 's/^Start: .*(\([0-9.]*\))/\1/p')
RATE=$(awk '/^RATE/{print $2}' "$T" | tail -1)
ML=$(grep -m1 "MATCH LIVE" "$T" | awk '{print $1}')
WIN=$(grep -m1 -E " WINS --" "$T" | awk '{print $1}')
[ -n "$B0" ] && [ -n "$ML" ] && [ -n "$WIN" ] || { echo "$name: no bag start, MATCH LIVE or result"; exit 1; }
# film.sh starts the capture 1 s before the replay, i.e. RATE s of real time
read -r ss dur < <(python3 -c "o = $RATE; s = o + ($ML - $B0) - 0.2; e = o + ($WIN - $B0) + $tail; print(f'{s:.2f} {e - s:.2f}')")

C=$WORK/clips
python3 -I "$(dirname "$0")/overlay.py" title "$C/$out.title.png" "$head" "$line"
[ -f "$WORK/legend.png" ] || python3 -I "$(dirname "$0")/overlay.py" legend "$WORK/legend.png"
FC="[0]scale=1080:-2:flags=lanczos[s];[1][s][2]vstack=inputs=3:shortest=1"
IN=(-ss "$ss" -t "$dur" -i "$WORK/takes/$name.mp4" -loop 1 -i "$C/$out.title.png" -loop 1 -i "$WORK/legend.png")
ffmpeg -loglevel error -y "${IN[@]}" -filter_complex "$FC,fps=${FPS:-12}" \
  -c:v libwebp_anim -lossless 0 -q:v "${Q:-55}" -compression_level 6 -loop 0 "$C/$out.webp"
ffmpeg -loglevel error -y "${IN[@]}" -filter_complex "$FC" \
  -c:v libx264 -crf 23 -preset slow -pix_fmt yuv420p -an "$C/$out.mp4"
ffmpeg -loglevel error -y -i "$C/$out.mp4" -vf "fps=8/$dur,scale=540:-1,tile=4x2" -frames:v 1 \
  "$C/$out.sheet.png"
echo "$out: $(grep -m1 ' WINS --' "$T" | sed 's/^[0-9.]* *//'); clip $dur s, $(du -h "$C/$out.webp" | cut -f1)"
