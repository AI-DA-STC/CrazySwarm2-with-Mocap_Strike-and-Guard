#!/bin/bash
# The recording setup: an off-screen display, the console's guard mission window in a
# kiosk Chrome on it (GPU, clean view, DevTools port for the camera), its own foxglove
# bridge and its own console -- all on a private ROS domain.
#
#   scripts/footage/rig.sh up      # start whatever is not running
#   scripts/footage/rig.sh down    # stop what `up` started (by process group), nothing else
#   scripts/footage/rig.sh chrome  # restart only the Chrome (after a console code change)
source "$(dirname "$0")/common.sh"

start() { local name=$1; shift; setsid "$@" > "$L/$name.log" 2>&1 & echo $! > "$L/$name.pgid"; }
up() { [ -f "$L/$1.pgid" ] && pgrep -g "$(cat "$L/$1.pgid")" >/dev/null; }

chrome() {
  local old; old=$(cat "$L/chrome.pgid" 2>/dev/null)
  [ -n "$old" ] && stop_group "$old"
  # The wrapper forks, so $! is not Chrome: record the real browser's process group.
  # Software WebGL on Xvfb manages ~3 fps; ANGLE on Vulkan puts it on the GPU.
  setsid google-chrome --user-data-dir="$WORK/chrome" --no-first-run --no-default-browser-check \
    --use-gl=angle --use-angle=vulkan --enable-features=Vulkan,VulkanFromANGLE,DefaultANGLEVulkan \
    --ignore-gpu-blocklist --remote-debugging-port="$CDP_PORT" \
    --window-position=0,0 --window-size=1600,1000 --kiosk \
    "$CONSOLE/mission?m=crazyflie_shows/guard&bridge=ws://127.0.0.1:$BRIDGE_PORT&clean=1" \
    > "$L/chrome.log" 2>&1 &
  sleep 5
  pgrep -o -f "^/opt/google/chrome/chrome --user-data-dir=$WORK/chrome" > "$L/chrome.pgid"
}

case "${1:-}" in
  up)
    command -v Xvfb >/dev/null || { echo "needs Xvfb: sudo apt install xvfb"; exit 1; }
    if ! xwininfo -display "$DISPLAY" -root >/dev/null 2>&1; then
      start xvfb Xvfb "$DISPLAY" -screen 0 1600x1000x24 -nolisten tcp; sleep 2
    fi
    up foxglove || start foxglove ros2 run foxglove_bridge foxglove_bridge --ros-args \
      -p port:="$BRIDGE_PORT" -p address:=127.0.0.1
    up console || start console ./console/run.sh --port "$CONSOLE_PORT" --no-browser
    sleep 4
    up chrome || chrome
    echo "rig up: display $DISPLAY, console $CONSOLE, ROS_DOMAIN_ID $ROS_DOMAIN_ID, work $WORK"
    ;;
  chrome) chrome; echo "chrome restarted" ;;
  down)
    for n in chrome console foxglove xvfb; do
      [ -f "$L/$n.pgid" ] || continue
      stop_group "$(cat "$L/$n.pgid")" || echo "WARNING: $n would not stop"
      rm -f "$L/$n.pgid"
    done
    echo "rig down"
    ;;
  *) echo "usage: $0 up|down|chrome"; exit 2 ;;
esac
