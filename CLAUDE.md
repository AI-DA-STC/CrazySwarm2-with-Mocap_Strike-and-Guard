# CLAUDE.md: Strike and Guard

Guidance for Claude Code in this repository.

## What this repo is

A ROS 2 workspace for two Crazyflie 2.1 demos of one problem, defending against
attackers:

- **Escort**: three defenders hold a ring around a VIP (a hand-flown DJI, or a fixed
  point) and turn it to block a fourth Crazyflie. Reactive, closed loop on mocap.
- **STL game**: five defenders stop five intruders (cf10-cf14, on a second Crazyradio)
  reaching a goal line. A colleague's algorithm, open loop: the seed fixes the flight,
  which is checked before arming.

OptiTrack/Motive gives every position; one laptop commands every drone. All source is
vendored in `src/` and committed; `build/`, `install/`, `log/` are generated and
git-ignored.

```
Motive ──NatNet multicast 50 Hz──► motion_capture_tracking ──/poses──► crazyflie_server ──Crazyradio(s)──► drones
                                                              │                ▲
                                                              ▼                │
                     escort_show (reads /poses every tick) ── cmd_full_state ──┤ 20 Hz per drone
                     stl_show (reads /poses only for the preflight checks) ── goTo
```

## Where things are

- `src/crazyswarm2/crazyflie_shows/crazyflie_shows/`:
  - `escort.py` is the escort's whole control law, pure Python; `plan_escort.py` verifies
    the same objects offline; `escort_show.py` flies them.
  - `stl_game.py` is the colleague's v3 algorithm, ported line for line (`play()` /
    `verify()` / `fly()`); `plan_stl.py` checks seeds and, with `--against`, must report
    the port IDENTICAL to the original in `crazyflie_examples/`, which stays unchanged.
  - `abort.py`, `preflight.py`, `safety.py` are the shared safety machinery.
  - `swarm_show`, `constellation*`, `choreography`, `figures`, `demo_show`, `plan_show`
    belong to two older shows; the demos import a few helpers from them, so they stay.
- `src/crazyswarm2/crazyflie/config/`: `crazyflies.yaml` is the ONLY fleet roster
  (cf10-cf14 committed `enabled: false`); `arena.yaml` is the measured room
  (`measured: false` makes the escort planner refuse; the STL game ignores it).
- `src/crazyswarm2/crazyflie/src/crazyflie_server.cpp`: heavily patched; read
  `docs/details/server-changes.md` before touching it.
- `console/`: optional web GUI, removable (`rm -rf console/` changes nothing else).
  Drives the `ros2` CLI as subprocesses, never in-process rclpy. Each demo's window is
  `src/crazyswarm2/crazyflie_shows/missions/<demo>.yaml`. Read `console/README.md` first.
- `docs/01-setup.md`, `docs/02-flight-day.md`, `docs/escort/`, `docs/stl/`,
  `docs/troubleshooting.md`: beginner guides. `docs/details/`: everything
  implementation-specific. `docs/diagrams/strike-and-guard-diagrams.pptx`: the source of
  every diagram (no mermaid); `docs/diagrams/export_png.sh` regenerates the PNGs.

## Build and run

```bash
./scripts/setup.sh                      # once: deps + build (needs internet: NatNet SDK)
./scripts/build.sh [package]            # after editing src/, then re-source install/setup.bash
ros2 launch crazyflie launch.py backend:=sim
ros2 run crazyflie_shows plan_escort
ros2 run crazyflie_shows escort_show --ros-args -p use_sim_time:=true -p vip_mode:=point -p paced:=true
ros2 run crazyflie_shows plan_stl       # refuses v3 at the default 0.15 m floor; that is known
```

## Rules that prevent real accidents

The evidence for each is in `docs/details/known-issues.md`; read the entry before
re-investigating any of these.

- **Scan before every launch** (`./scripts/scan_fleet.sh`). The server hangs silently
  forever on the first enabled drone that does not answer.
- **Never `apt install ros-<distro>-motion-capture-tracking`.** The vendored copy is the
  fixed one; the apt one silently receives nothing here.
- **`initial_position` comes from `/poses`** (`scripts/sync_initial_positions.py`),
  never from `/cfX/pose`. Re-run the demo's planner after every sync.
- **`use_sim_time:=true` in the simulator, never on hardware.** Restart the sim launch
  between runs.
- **Set `ROS_DOMAIN_ID`.** Domain 0 is shared with the rest of the lab.
- **After an E-STOP, every drone needs a battery re-plug** (supervisor LOCKED).
- **Shows must use `abort.take_signals()`** and set `armed = True` before the arm loop;
  `ShowAborted` is a `BaseException`, so never wrap a gate in a bare `except Exception`.
- **Do not edit the STL algorithm in place.** It is a port; a new version arrives as a
  new file and is re-ported (`docs/details/stl-design-notes.md`, "When v4 arrives").
  Questions about its behaviour go to the colleague, not into a patch.
- **Any new compiler warning in `src/crazyswarm2` or `src/natnet_ros2` is a regression.**
  The ~25 remaining warnings are in third-party deps and were reviewed; do not silence them.
- **Never `stop_stack.sh`** while the user may have a stack up: it stops every stack on
  the machine. For test stacks use a private `ROS_DOMAIN_ID` and stop them by PID.

## Writing docs here

Beginner guides stay short, plain and free of implementation detail; anything that
needs code names, history or maths goes in `docs/details/`. Shared steps live in
`docs/02-flight-day.md`, demo-specific ones in `docs/<demo>/`. Never write the fleet
roster, marks or arena numbers into prose: print them (`scan_fleet.sh --list`,
`plan_escort --marks`, `plan_stl`). New diagrams go into the PowerPoint deck, not mermaid.
