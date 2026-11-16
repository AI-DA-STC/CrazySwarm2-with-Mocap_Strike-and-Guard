#!/bin/bash
# One take, two passes (needs `rig.sh up`):
#  1. FLY: a fresh simulator stack, the guard show started through the console's own Run API
#     (so it runs exactly as from the mission window), /tf + /guard/markers bagged.
#  2. FILM: film.sh replays the bag into the console and captures the scene.
#
#   scripts/footage/take.sh <name> '<mission values as JSON>'
#   scripts/footage/take.sh shell '{"rules":"tag","defense":"shell","attack":"coordinated","seed":0}'
#
# Values are the guard mission window's options (missions/guard.yaml); "extra" carries any
# other guard_show parameter, e.g. "extra":"rules_params:=duration=30".
# Output: $FOOTAGE_DIR/bags/<name>, takes/<name>.out (the show's output) and takes/<name>.mp4.
source "$(dirname "$0")/common.sh"
name=$1; values=$2
[ -n "$name" ] && [ -n "$values" ] || { sed -n 2,13p "$0"; exit 2; }
curl -sf "$CONSOLE/api/procs" >/dev/null || { echo "no console at $CONSOLE: run rig.sh up"; exit 1; }
rm -rf "$WORK/bags/$name"

setsid ros2 launch crazyflie launch.py backend:=sim rviz:=False foxglove:=False mocap:=False \
  teleop:=False preflight:=False gui:=False > "$L/sim.$name.log" 2>&1 &
sim=$!
for _ in $(seq 60); do ros2 topic list 2>/dev/null | grep -q '/cmd_full_state$' && break; sleep 1; done
sleep 2
setsid ros2 bag record -s mcap -o "$WORK/bags/$name" /tf /guard/markers > "$L/bag.$name.log" 2>&1 &
bag=$!
sleep 3

body=$(python3 -c "
import json, sys
v = json.loads(sys.argv[1])
v.setdefault('paced', False)
v.setdefault('defenders', 'cf1,cf2,cf3,cf4')
v.setdefault('attackers', 'cf10,cf11,cf12')
print(json.dumps({'id': 'crazyflie_shows/guard', 'role': 'main', 'values': v, 'sim': True}))" "$values")
pid=$(curl -s -X POST -H 'Content-Type: application/json' -d "$body" "$CONSOLE/api/mission/start" \
      | python3 -c "import json, sys; d = json.load(sys.stdin); print(d.get('id') or d)")
for _ in $(seq 400); do
  st=$(curl -s "$CONSOLE/api/procs" | python3 -c "
import json, sys
p = [x for x in json.load(sys.stdin)['procs'] if x['id'] == '$pid']
print(p[0]['state'] if p else 'gone')")
  [ "$st" = running ] || break
  sleep 1.5
done
curl -s "$CONSOLE/api/proc/$pid" | python3 -c "
import json, sys
print('\n'.join(f\"{l['ts']:.2f} {l['text']}\" for l in json.load(sys.stdin)['lines']))" \
  > "$WORK/takes/$name.out"
sleep 2

stop_group $bag || { echo "RECORDER WOULD NOT STOP (pgid $bag)"; exit 1; }
[ -f "$WORK/bags/$name/metadata.yaml" ] || ros2 bag reindex "$WORK/bags/$name" -s mcap >/dev/null 2>&1
stop_group $sim || echo "WARNING: the sim stack (pgid $sim) would not stop"

"$(dirname "$0")/film.sh" "$name"
echo "take $name: $st"
grep -E " WINS --|ABORT|REFUSED|Traceback" "$WORK/takes/$name.out" | head -3
