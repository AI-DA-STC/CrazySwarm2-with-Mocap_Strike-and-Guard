#!/bin/bash
# Replay a take's bag into the console at half speed and film the 3D scene, then speed the
# capture back up. Chrome on Xvfb renders ~7.6 fps however it is set up (the GPU frame's
# copy back to the X server is single-threaded), so half speed gives ~15 fps of match time
# and in practice ~30. Re-run it alone to re-film a take (new camera, console fix) without
# flying it again.
#
#   scripts/footage/film.sh <name>          RATE=0.5 by default
source "$(dirname "$0")/common.sh"
name=$1; RATE=${RATE:-0.5}
[ -d "$WORK/bags/$name" ] || { echo "no bag $WORK/bags/$name"; exit 1; }
sed -i '/^PLAY0 \|^RATE /d' "$WORK/takes/$name.out" 2>/dev/null

"$(dirname "$0")/camera.sh"
setsid ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 -framerate 30 -video_size $SCENE_SIZE \
  -i "$DISPLAY$SCENE_AT" -c:v libx264 -preset veryfast -crf 16 -pix_fmt yuv420p \
  "$WORK/takes/$name.slow.mp4" < /dev/null > "$L/ffmpeg.$name.log" 2>&1 &
cap=$!
sleep 1.0
echo "PLAY0 $(date +%s.%N)" >> "$WORK/takes/$name.out"
ros2 bag play "$WORK/bags/$name" --rate "$RATE" < /dev/null > "$L/play.$name.log" 2>&1
sleep 1
stop_group $cap
echo "RATE $RATE" >> "$WORK/takes/$name.out"
ffmpeg -loglevel error -y -i "$WORK/takes/$name.slow.mp4" -vf "setpts=$RATE*PTS" -r 30 \
  -c:v libx264 -crf 16 -preset veryfast -pix_fmt yuv420p "$WORK/takes/$name.mp4"
