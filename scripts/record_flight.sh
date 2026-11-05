#!/usr/bin/env bash
# Record a flight started from a TERMINAL, the way the mission console records
# every flight it starts: one folder with the show's output, a ros2 bag, the
# config as it was, and a report at the end. docs/details/flight-logs.md.
#
#   ./scripts/record_flight.sh ros2 run crazyflie_shows guard_show --ros-args \
#       -p defenders:=cf1,cf2 -p attackers:=cf10 -p paced:=true
#
# The show runs in the foreground exactly as typed: Enter at its gates, and
# Ctrl-C still reaches it (and only it) -- its abort landing is not cut short.
# The bag runs in its own session, so the Ctrl-C does not stop the recording
# before the drones are down; it is stopped TAIL_S after the show exits.
#
#   FLIGHT_LOG_ROOT   where the folders go (default ~/.ros/flight_logs)
set -u

if [ $# -eq 0 ]; then
    sed -n '2,15p' "$0"
    exit 2
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${FLIGHT_LOG_ROOT:-$HOME/.ros/flight_logs}"
TAIL_S=2
TOPICS='^/(poses|rosout)$|^/cf[0-9]+/(cmd_full_state|cmd_position|cmd_hover|cmd_vel_legacy|pose|status|kalman_preflight|downwash)$|^/escort/vip$'

# the script's name: `ros2 run <pkg> <script> ...` -> <script>
slug="$(basename "$1")"
if [ "$(basename "$1")" = ros2 ] && [ "${2:-}" = run ] && [ -n "${4:-}" ]; then slug="$4"; fi
slug="$(printf '%s' "$slug" | tr -c 'A-Za-z0-9_.-' '_' | cut -c1-40)"
DIR="$ROOT/$(date +%Y%m%d_%H%M%S)_$slug"
mkdir -p "$DIR/config" || exit 1
for f in crazyflies.yaml arena.yaml; do
    cp -p "$HERE/src/crazyswarm2/crazyflie/config/$f" "$DIR/config/" 2>/dev/null
done

meta() {   # meta <returncode or empty>
    python3 - "$DIR" "$@" <<'PY'
import json, os, socket, subprocess, sys, time
d, rc, argv = sys.argv[1], sys.argv[2], sys.argv[4:]     # [3] is the '--'
p = os.path.join(d, 'meta.json')
m = json.load(open(p)) if os.path.exists(p) else {}
def git(*a):
    try:
        return subprocess.run(['git', *a], cwd=os.environ['HERE'], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return ''
now = time.time()
iso = lambda t: time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t))
if not m:
    m = {'argv': argv, 'cmdline': ' '.join(argv), 'cwd': os.getcwd(),
         'started': now, 'started_iso': iso(now), 'host': socket.gethostname(),
         'ros_domain_id': os.environ.get('ROS_DOMAIN_ID', ''),
         'sim': any('use_sim_time:=true' in a for a in argv),
         'git': {'head': git('rev-parse', '--short', 'HEAD'),
                 'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
                 'dirty': bool(git('status', '--porcelain'))},
         'recorder': 'scripts/record_flight.sh'}
if rc != '':
    m.update(ended=now, ended_iso=iso(now), returncode=int(rc),
             state='done' if rc == '0' else ('stopped' if rc in ('130', '-2') else 'failed'),
             bag=os.path.isdir(os.path.join(d, 'bag')))
json.dump(m, open(p, 'w'), indent=1)
PY
}
export HERE
meta "" -- "$@"

# the bag, in its own session: a Ctrl-C meant for the show must not stop it
setsid ros2 bag record -s mcap -o "$DIR/bag" --regex "$TOPICS" \
    > "$DIR/bag_record.log" 2>&1 < /dev/null &
BAG=$!
echo "[flight log] recording to $DIR"
sleep 1.5                      # let the recorder discover and subscribe

export FLIGHT_LOG_DIR="$DIR" PYTHONUNBUFFERED=1
# A HANDLER (not an ignore, which children would inherit): on Ctrl-C this
# script carries on to stop the bag and write the report once the show exits.
trap 'true' INT
# The show in the foreground; its output to the terminal AND, stamped, to
# output.log. The reader ignores SIGINT, so on Ctrl-C it keeps draining the
# show's abort-landing output instead of breaking the pipe under it.
"$@" 2>&1 | (
    trap '' INT
    while IFS= read -r line; do
        printf '%s\n' "$line"
        printf '%s %s\n' "$(date +%Y-%m-%dT%H:%M:%S.%3N)" "$line" >> "$DIR/output.log"
    done
)
rc=${PIPESTATUS[0]}

sleep "$TAIL_S"
kill -INT -- -"$BAG" 2>/dev/null || kill -INT "$BAG" 2>/dev/null
for _ in $(seq 1 30); do kill -0 "$BAG" 2>/dev/null || break; sleep 0.5; done
kill -0 "$BAG" 2>/dev/null && kill -TERM -- -"$BAG" 2>/dev/null
meta "$rc" -- "$@"
echo "[flight log] saved in $DIR"
if [ -d "$DIR/bag" ]; then
    ros2 run crazyflie_shows flight_report "$DIR" > /dev/null 2>"$DIR/report.err" \
        && echo "[flight log] report: $DIR/report.txt" \
        || echo "[flight log] report failed: $DIR/report.err"
fi
exit "$rc"
