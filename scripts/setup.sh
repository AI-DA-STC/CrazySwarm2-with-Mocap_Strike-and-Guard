#!/usr/bin/env bash
# One-shot setup for the CrazySwarm2 workspace.
#
# The source is VENDORED in this repo (src/), so setup only needs to:
#   1. detect distro (Ubuntu 22.04/Humble or 24.04/Jazzy)
#   2. install apt + rosdep deps   -> scripts/install_deps.sh
#   3. build                       -> scripts/build.sh
#
# For the simulator (backend:=sim) also run scripts/setup_sim_firmware.sh once.
# Idempotent: safe to re-run.
set -euo pipefail

WS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WS_ROOT}"

. /etc/os-release
ROS_DISTRO="${ROS_DISTRO:-}"
if [[ -z "${ROS_DISTRO}" ]]; then
  case "${VERSION_ID}" in
    22.04) ROS_DISTRO=humble ;;
    24.04) ROS_DISTRO=jazzy  ;;
    *) echo "ERROR: Unsupported Ubuntu ${VERSION_ID} (need 22.04 or 24.04)." >&2; exit 1 ;;
  esac
fi
if [[ ! -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]]; then
  echo "ERROR: ROS 2 ${ROS_DISTRO} not installed at /opt/ros/${ROS_DISTRO}." >&2
  echo "       See README 'Setup Step 1' for the ROS 2 install steps, then re-run." >&2
  exit 1
fi
echo "=================================================================="
echo " CrazySwarm2 setup  |  Ubuntu ${VERSION_ID}  |  ROS 2 ${ROS_DISTRO}"
echo "=================================================================="

if [[ ! -d src/crazyswarm2 ]]; then
  echo "ERROR: src/crazyswarm2 not found. This repo should contain the vendored" >&2
  echo "       source — did the clone complete?" >&2
  exit 1
fi

# --- 1. dependencies ----------------------------------------------------------
echo "==> [1/3] Installing dependencies"
ROS_DISTRO="${ROS_DISTRO}" bash "${WS_ROOT}/scripts/install_deps.sh"

# --- 2. build -----------------------------------------------------------------
echo "==> [2/3] Building workspace"
bash "${WS_ROOT}/scripts/build.sh"

# --- 3. verify the vendored mocap driver -------------------------------------
# The apt release ros-<distro>-motion-capture-tracking 1.0.9 hard-codes a foreign
# interface IP (141.23.110.162) and never receives NatNet frames, so this repo
# vendors the driver in src/motion_capture_tracking. Refuse to call the setup
# "done" unless the workspace build is the copy that will actually run.
echo "==> [3/3] Verifying the mocap driver"
if [[ ! -f "${WS_ROOT}/install/setup.bash" ]]; then
  echo "ERROR: ${WS_ROOT}/install/setup.bash does not exist — the build did not complete." >&2
  echo "       Scroll up for the first colcon error, fix it, and re-run ./scripts/setup.sh." >&2
  exit 1
fi
set +u
# shellcheck disable=SC1090,SC1091
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "${WS_ROOT}/install/setup.bash"
set -u
EXPECTED_PREFIX="${WS_ROOT}/install/motion_capture_tracking"
ACTUAL_PREFIX="$(ros2 pkg prefix motion_capture_tracking 2>/dev/null || true)"
if [[ "${ACTUAL_PREFIX}" != "${EXPECTED_PREFIX}" ]]; then
  echo "ERROR: motion_capture_tracking resolves to '${ACTUAL_PREFIX:-<not found>}'," >&2
  echo "       expected ${EXPECTED_PREFIX}." >&2
  echo "       The vendored driver did not build, or an apt copy shadows it." >&2
  echo "       See src/motion_capture_tracking/VENDORED.md." >&2
  exit 1
fi
NODE_BIN="${ACTUAL_PREFIX}/lib/motion_capture_tracking/motion_capture_tracking_node"
if [[ ! -x "${NODE_BIN}" ]]; then
  echo "ERROR: ${NODE_BIN} is missing — the vendored driver did not build." >&2
  exit 1
fi
if grep -q 141.23.110.162 "${NODE_BIN}"; then
  echo "ERROR: ${NODE_BIN} contains the hard-coded apt-1.0.9 interface IP." >&2
  echo "       src/motion_capture_tracking is not the pinned vendored copy." >&2
  exit 1
fi
if dpkg -s "ros-${ROS_DISTRO}-motion-capture-tracking" >/dev/null 2>&1; then
  echo "WARN: apt ros-${ROS_DISTRO}-motion-capture-tracking is still installed. It is" >&2
  echo "      shadowed by the workspace build, but remove it so it cannot come back:" >&2
  echo "      sudo apt remove ros-${ROS_DISTRO}-motion-capture-tracking ros-${ROS_DISTRO}-motion-capture-tracking-interfaces" >&2
fi
echo "    OK: motion_capture_tracking from ${ACTUAL_PREFIX} (vendored, no hard-coded IP)"

cat <<EOF

==================================================================
 Done. To use the workspace in a new shell:

   source /opt/ros/${ROS_DISTRO}/setup.bash
   source ${WS_ROOT}/install/setup.bash

 Simulator (one-time extra step for backend:=sim):
   ./scripts/setup_sim_firmware.sh        # builds the cffirmware bindings
   ros2 launch crazyflie launch.py backend:=sim rviz:=True

 Next: docs/02-flight-day.md.
==================================================================
EOF
