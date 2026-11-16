# Sourced by every scripts/footage/ script: one private, isolated recording setup.
# Read docs/details/guard-footage.md first. Everything is overridable:
#
#   FOOTAGE_DIR      work folder: bags, raw takes, clips, logs   (~/.cache/guard-footage)
#   FOOTAGE_DOMAIN   ROS_DOMAIN_ID of the sim, NEVER the lab's    (87)
#   FOOTAGE_DISPLAY  the off-screen X display (Xvfb)              (:99)
#   CONSOLE_PORT     the recording's own mission console          (8178)
#   BRIDGE_PORT      its own foxglove_bridge, on 127.0.0.1        (8799)
#   CDP_PORT         the recording Chrome's DevTools port         (9333)

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"
set +u; source install/setup.bash
WORK=${FOOTAGE_DIR:-$HOME/.cache/guard-footage}
L=$WORK/logs
mkdir -p "$WORK"/{bags,takes,clips,logs}

export ROS_DOMAIN_ID=${FOOTAGE_DOMAIN:-87}
export DISPLAY=${FOOTAGE_DISPLAY:-:99}
CONSOLE_PORT=${CONSOLE_PORT:-8178}
BRIDGE_PORT=${BRIDGE_PORT:-8799}
export CDP_PORT=${CDP_PORT:-9333}
CONSOLE=http://127.0.0.1:$CONSOLE_PORT
# keep the operator's console usage log and ~/.ros/flight_logs free of recording runs
export MISSION_CONSOLE_USAGE_DIR=$WORK/console-usage
export FLIGHT_LOG_ROOT=$WORK/flightlogs FLIGHT_LOG_DIR=$WORK/flightlogs

#: the 3D scene inside the 1600x1000 kiosk window (mission window layout)
SCENE_SIZE=1200x720
SCENE_AT=+10,66

# Stop a process group: SIGINT, wait, then TERM and KILL. `ros2 bag record` started
# under setsid has been seen to ignore SIGINT and record for 25 minutes.
stop_group() {
  local g=$1
  [ -n "$g" ] || return 0
  kill -INT -- -"$g" 2>/dev/null
  for _ in $(seq 20); do pgrep -g "$g" >/dev/null || return 0; sleep 0.5; done
  kill -TERM -- -"$g" 2>/dev/null; sleep 3
  pgrep -g "$g" >/dev/null && { kill -KILL -- -"$g" 2>/dev/null; sleep 1; }
  ! pgrep -g "$g" >/dev/null
}
