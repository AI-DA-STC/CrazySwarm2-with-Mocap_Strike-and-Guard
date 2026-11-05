#!/usr/bin/env bash
# Probe for scripts/offline_window.sh: does the mission console go blind when it
# was started BEFORE a Wi-Fi switch?  Plus a read-only Motive check.
#
#   scripts/offline_window.sh --dry-run console_network   # first, online
#   scripts/offline_window.sh console_network
#
# Sim backend only, on the wrapper's private ROS_DOMAIN_ID; never touches a radio.
# Found 2026-11-05 (docs/details/known-issues.md, "console blind after a Wi-Fi
# switch"): the ros2 daemon started before the switch lists NO nodes afterwards,
# so console health says "crazyflie_server not running" while RViz works.
#
#   pre      start the console (and so its ros2 daemon + /rosout journal) online
#   offline  sim stack on the mocap Wi-Fi; old daemon vs fresh CLI; console
#            health; journal; foxglove decode; daemon restart; Motive + /poses
#   post     summary
set -uo pipefail
REPO="$(cd "$(dirname "$(realpath "$0")")/../.." && pwd)"
HERE="$(dirname "$(realpath "$0")")"
PORT=8098
set +u; source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"; source "$REPO/install/setup.bash"; set -u
NODE=''
if [[ -s ${NVM_DIR:=$HOME/.nvm}/nvm.sh ]]; then set +u; . "$NVM_DIR/nvm.sh"; nvm use default >/dev/null 2>&1; set -u; fi
command -v node >/dev/null && NODE=node
: "${OUT:=$REPO/log/offline/manual}"; mkdir -p "$OUT"
say() { printf '\n[%s] --- %s\n' "$(date +%T)" "$*"; }
dkill() {    # SIGINT processes matching $1 -- only those on OUR domain
  local p
  for p in $(pgrep -f -- "$1"); do
    [[ $p == "$$" ]] && continue
    tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -qx "ROS_DOMAIN_ID=$ROS_DOMAIN_ID" && kill -INT "$p"
  done
}
health() {   # $1 = label: refresh console health, print the ROS-side verdicts
  curl -s --max-time 60 "localhost:$PORT/api/health?refresh=1" > "$OUT/health-$1.json"
  python3 - "$OUT/health-$1.json" <<'EOF'
import json, sys
try:
    nodes = json.load(open(sys.argv[1]))['nodes']
except Exception as e:
    print('  console health unreadable:', e); sys.exit()
for n in nodes:
    if n['id'].split('.')[0] in ('mocap', 'server', 'drone'):
        print(f"  {n['id']:16} {n['status']:8} {n.get('summary', '')[:80]}")
EOF
}
journal_lands() {   # how many `land` commands the console's journal has heard
  curl -s --max-time 10 "localhost:$PORT/api/journal" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(sum(1 for e in d.get("events", []) if "land" in json.dumps(e)), "| listener:", d.get("state"))'
}
sim_land() {
  timeout 20 ros2 service call /cf1/land crazyflie_interfaces/srv/Land \
    "{height: 0.0, duration: {sec: 1}}" >/dev/null 2>&1 && echo "  sent /cf1/land (sim)"
  sleep 3
}

case "${1:?phase: pre|offline|post}" in
pre)
  say "network before the switch"; ip -br addr | grep -v '^lo'
  say "starting the console on :$PORT (domain $ROS_DOMAIN_ID)"
  setsid "$REPO/console/run.sh" --no-browser --port $PORT > "$OUT/console.log" 2>&1 < /dev/null &
  for _ in $(seq 30); do curl -s -o /dev/null "localhost:$PORT/" && break; sleep 1; done
  sleep 5   # the journal's `ros2 topic echo /rosout` spawns the daemon
  echo "console HTTP $(curl -s -o /dev/null -w '%{http_code}' "localhost:$PORT/")"
  pgrep -af "ros2cli.daemon" | grep -- "--ros-domain-id $ROS_DOMAIN_ID" | cut -c1-110 || echo "no daemon yet"
  ;;

offline)
  say "network now"; ip -br addr | grep -v '^lo'; ip route | head -2
  if ss -ltn | grep -q ':8765 '; then FOX=False; echo "port 8765 busy -> no foxglove"; else FOX=True; fi
  say "SIM stack (no rviz/preflight/teleop windows)"
  ros2 launch crazyflie launch.py backend:=sim rviz:=False preflight:=False teleop:=False \
    foxglove:=$FOX > "$OUT/sim.log" 2>&1 < /dev/null &
  sleep 15

  say "TEST 1: node list through the daemon started BEFORE the switch"
  timeout 15 ros2 node list 2>&1 | sed 's/^/  /'
  say "TEST 1b: node list from a fresh participant (--no-daemon)"
  timeout 15 ros2 node list --no-daemon --spin-time 3 2>&1 | sed 's/^/  /'
  say "TEST 2: console health"
  health before-restart
  say "TEST 2b: does the console journal hear a command? (lands heard before/after)"
  echo "  before: $(journal_lands)"; sim_land; echo "  after:  $(journal_lands)"

  if [[ $FOX == True && -n $NODE ]]; then
    say "TEST 3: console preview decoder (ros.mjs) on /tf via the bridge"
    timeout 20 node "$HERE/foxglove_decode.mjs" "$REPO/console/mission_console/static/mission/ros.mjs" \
      ws://localhost:8765 /tf 2>&1 | sed 's/^/  /'
  else
    say "TEST 3 skipped (foxglove=$FOX, node=${NODE:-missing: install via nvm})"
  fi

  if [[ $FOX == True && -n $NODE ]] && command -v google-chrome >/dev/null; then
    say "TEST 6: the mission window in headless Chrome (fake best-effort /poses: cf2 at 0.77 m)"
    ros2 topic pub -r 50 --qos-reliability best_effort --qos-depth 1 /poses \
      motion_capture_tracking_interfaces/msg/NamedPoseArray \
      "{header: {frame_id: world}, poses: [{name: cf2, pose: {position: {x: 0.5, y: 0.5, z: 0.77}, orientation: {w: 1.0}}}]}" \
      > /dev/null 2>&1 < /dev/null &
    google-chrome --headless=new --remote-debugging-port=9333 --user-data-dir="$OUT/chrome" \
      --no-first-run --enable-unsafe-swiftshader about:blank > "$OUT/chrome.log" 2>&1 < /dev/null &
    sleep 4
    timeout 40 node "$HERE/mission_view.mjs" 9333 \
      "http://localhost:$PORT/mission?m=crazyflie_shows%2Fguard" 12 2>&1 | sed 's/^/  /'
    dkill "remote-debugging-port=9333"; dkill "ros2 topic pub -r 50"; sleep 2
  else
    say "TEST 6 skipped (needs foxglove, node and google-chrome)"
  fi

  say "TEST 4: restart the ros2 daemon, repeat 1, 2 and 2b"
  ros2 daemon stop 2>&1 | sed 's/^/  /'; ros2 daemon start 2>&1 | sed 's/^/  /'; sleep 4
  timeout 15 ros2 node list 2>&1 | sed 's/^/  /'
  health after-restart
  echo "  journal before: $(journal_lands)"; sim_land; echo "  journal after:  $(journal_lands)"

  say "stopping the sim stack"
  dkill "launch.py backend:=sim rviz:=False preflight:=False"; sleep 5

  say "TEST 5: Motive, read-only (vendored driver alone; /poses needs cameras on)"
  if ss -lun | grep -q ':1511 '; then echo "  UDP 1511 already bound -- skipping"; else
    HOST=$(cd "$OUT" && timeout 10 python3 -c '
import sys, importlib.util as u
s = u.spec_from_file_location("cfl", sys.argv[1]); m = u.module_from_spec(s); s.loader.exec_module(m)
h = m.discover_motive_host()
print((h[0] if isinstance(h, (list, tuple)) and h else h) or "")' \
      "$REPO/src/crazyswarm2/crazyflie/launch/launch.py" 2>>"$OUT/discovery.err" | tail -1)
    echo "  NatNet discovery: ${HOST:-no Motive answered}"
    if [[ -n $HOST ]]; then
      ros2 run motion_capture_tracking motion_capture_tracking_node --ros-args \
        -r __node:=motion_capture_tracking \
        --params-file "$REPO/install/crazyflie/share/crazyflie/config/motion_capture.yaml" \
        -p hostname:="$HOST" \
        > "$OUT/mocap.log" 2>&1 < /dev/null &
      sleep 6
      timeout 8 ros2 topic hz /poses 2>&1 | tail -3 | sed 's/^/  /'
      timeout 6 ros2 topic echo /poses --once 2>&1 | grep -E "name:" | head -8 | sed 's/^/  /'
      dkill motion_capture_tracking_node; sleep 2
      tail -4 "$OUT/mocap.log" | sed 's/^/  mocap.log: /'
    fi
  fi
  ;;

post)
  say "summary (back online)"
  ls "$OUT"/health-*.json 2>/dev/null | sed 's/^/  /'
  grep -iE "error|traceback" "$OUT/sim.log" 2>/dev/null | grep -vE "LaunchConfigurationEquals|context is invalid|Connection reset|Traceback|has died" \
    | head -5 | sed 's/^/  sim.log: /'
  echo "  (shutdown noise from SIGINT -- 'context is invalid', 'Connection reset' -- is filtered out)"
  ;;
esac
