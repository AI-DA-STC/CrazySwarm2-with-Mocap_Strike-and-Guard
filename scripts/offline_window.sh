#!/usr/bin/env bash
#
# Run a probe on the mocap Wi-Fi (no internet) and ALWAYS come back.
#
# WHY THIS EXISTS
# ---------------
# Motive lives on its own subnet with no internet. With the wired port taken,
# the laptop is on ONE Wi-Fi at a time: mocap or internet, never both. Anything
# that must be tested on the mocap network (the network switch itself, Motive
# discovery, /poses) therefore runs while Claude Code -- and any remote help --
# is cut off. This wrapper makes that window safe and reviewable:
#
#   * the probe is syntax-checked BEFORE the network is touched;
#   * everything is logged to log/offline/<stamp>/run.log, and a terminal
#     window follows that log live, so the operator sees errors as they happen;
#   * the internet Wi-Fi is restored by the EXIT trap, and independently by a
#     watchdog process at MAX+90 s even if this script is killed outright;
#   * every process the probe starts runs on a private ROS_DOMAIN_ID and is
#     killed by domain at the end -- nothing on the operator's domain is touched;
#   * it REFUSES to run while a crazyflie server or mocap node is up on any
#     domain: switching networks under a live stack starves /poses mid-flight.
#
# Usage:
#   scripts/offline_window.sh [options] PROBE
#     PROBE        a name in scripts/offline_probes/ (with or without .sh) or a path
#     --dry-run    run every phase but never switch networks (do this first)
#     --max S      hard limit for the offline phase, seconds (default 240)
#     --off NAME   NetworkManager connection to switch to (default: motive)
#     --home NAME  connection to come back to (default: the Wi-Fi active now)
#     --domain N   private ROS_DOMAIN_ID for the probe (default 77)
#
# A probe is a bash script called once per phase, with ROS_DOMAIN_ID set and
# OUT pointing at the run's output directory:
#   PROBE pre      still online -- start whatever must predate the switch
#   PROBE offline  on the mocap Wi-Fi, under `timeout MAX`
#   PROBE post     back online, after every probe process was killed
# See scripts/offline_probes/console_network.sh for a worked example.
set -uo pipefail

REPO="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
OFF_NET='motive'
HOME_NET=''
DOMAIN=77
MAX=240
DRY=0
while [[ $# -gt 1 ]]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --max) MAX="$2"; shift 2 ;;
    --off) OFF_NET="$2"; shift 2 ;;
    --home) HOME_NET="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
ARG="${1:-}"
[[ -z $ARG || $ARG == -* ]] && { sed -n '/^# Usage:/,/^#   PROBE post/p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
if [[ -f $ARG ]]; then PROBE="$(realpath "$ARG")"
elif [[ -f $REPO/scripts/offline_probes/$ARG ]]; then PROBE="$REPO/scripts/offline_probes/$ARG"
elif [[ -f $REPO/scripts/offline_probes/$ARG.sh ]]; then PROBE="$REPO/scripts/offline_probes/$ARG.sh"
else echo "no probe '$ARG' (looked in scripts/offline_probes/)" >&2; exit 2; fi

# ---------------------------------------------------------------- preconditions
bash -n "$PROBE" || { echo "SYNTAX ERROR in $PROBE -- nothing was run" >&2; exit 3; }
if [[ -z $HOME_NET ]]; then
  HOME_NET="$(nmcli -t -f NAME,TYPE con show --active | awk -F: '$2 ~ /wireless/ {print $1; exit}')"
fi
[[ -n $HOME_NET ]] || { echo "cannot tell which Wi-Fi to come back to; pass --home NAME" >&2; exit 2; }
[[ $HOME_NET != "$OFF_NET" ]] || { echo "already on '$OFF_NET'; pass --home NAME (the internet Wi-Fi)" >&2; exit 2; }
nmcli -t -f NAME con show | grep -qxF "$OFF_NET" || { echo "no saved connection '$OFF_NET'" >&2; exit 2; }
LIVE="$(pgrep -af 'crazyflie_server|motion_capture_tracking_node' | grep -v pgrep || true)"
if [[ -n $LIVE && $DRY == 0 ]]; then
  echo "REFUSING: a crazyflie server or mocap node is running -- switching networks" >&2
  echo "would starve it. Stop the stack first:" >&2; echo "$LIVE" >&2; exit 4
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
export OUT="$REPO/log/offline/$STAMP"
LOG="$OUT/run.log"
mkdir -p "$OUT"; : > "$LOG"; ln -sfn "$OUT" "$REPO/log/offline/latest"

# live view for the operator
if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v gnome-terminal >/dev/null; then
  gnome-terminal --title "offline probe $STAMP" -- bash -c \
    "tail --pid=$$ -n +1 -F '$LOG'; echo; echo '--- finished; close this window ---'; read -r" \
    >/dev/null 2>&1 || true
fi
exec >>"$LOG" 2>&1

say() { printf '\n[%s] === %s\n' "$(date +%T)" "$*"; }
domain_pids() {
  local p
  for p in $(pgrep -u "$USER"); do
    [[ $p == "$$" || $p == "$BASHPID" ]] && continue
    tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -qx "ROS_DOMAIN_ID=$DOMAIN" && echo "$p"
  done
}
kill_domain() {
  local l; l=$(domain_pids); [[ -z $l ]] && return 0
  kill -INT $l 2>/dev/null; sleep 4
  l=$(domain_pids); [[ -n $l ]] && { kill -TERM $l 2>/dev/null; sleep 2; }
  l=$(domain_pids); [[ -n $l ]] && kill -KILL $l 2>/dev/null
  echo "processes left on domain $DOMAIN: $(domain_pids | wc -l)"
}
online() { timeout 5 curl -s -o /dev/null https://api.anthropic.com 2>/dev/null; }
switch_to() {
  [[ $DRY == 1 ]] && { echo "(dry run: would switch to '$1')"; return 0; }
  local i
  for i in 1 2 3; do
    timeout 40 nmcli con up "$1" && return 0
    echo "nmcli con up '$1' failed (attempt $i)"; sleep 3
  done
  return 1
}

WATCHDOG=''
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  say "cleanup (rc=$rc)"
  kill_domain
  if [[ $DRY == 0 ]]; then
    switch_to "$HOME_NET"
    for _ in $(seq 30); do online && break; sleep 2; done
    online && echo "internet: back on '$HOME_NET'" || echo "internet: STILL DOWN -- reconnect '$HOME_NET' by hand"
  fi
  [[ -n $WATCHDOG ]] && kill "$WATCHDOG" 2>/dev/null
  say "post phase"
  ROS_DOMAIN_ID=$DOMAIN timeout 60 bash "$PROBE" post
  kill_domain
  say "done -- $LOG"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

say "offline window $STAMP"
echo "probe=$PROBE  off='$OFF_NET'  home='$HOME_NET'  domain=$DOMAIN  max=${MAX}s  dry_run=$DRY"
if [[ -n $(domain_pids) ]]; then echo "domain $DOMAIN is busy -- refusing:"; domain_pids; exit 4; fi

say "pre phase (online)"
ROS_DOMAIN_ID=$DOMAIN timeout 90 bash "$PROBE" pre || echo "pre phase rc=$?"

if [[ $DRY == 0 ]]; then
  setsid nohup bash -c "sleep $((MAX + 90)); nmcli con up '$HOME_NET'" >/dev/null 2>&1 &
  WATCHDOG=$!
fi
say "switching to '$OFF_NET'"
switch_to "$OFF_NET" || { echo "could not join '$OFF_NET'"; exit 5; }
sleep 3; ip -br addr | grep -v '^lo'

say "offline phase (max ${MAX}s)"
ROS_DOMAIN_ID=$DOMAIN timeout --kill-after=10 "$MAX" bash "$PROBE" offline
echo "offline phase rc=$?"
