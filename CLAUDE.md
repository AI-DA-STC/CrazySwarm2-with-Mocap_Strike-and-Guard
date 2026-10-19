# CLAUDE.md: Escort Demo

Guidance for Claude Code in this repository.

## What this repo is

A ROS 2 workspace for one demo: three Crazyflie 2.1 defenders hold a ring around a
VIP (a hand-flown DJI, or a fixed point) and turn it to block a fourth Crazyflie, the
attacker. OptiTrack/Motive gives every position; one laptop commands every drone over
one Crazyradio. All source is vendored in `src/` and committed; `build/`, `install/`,
`log/` are generated and git-ignored.

```
Motive ──NatNet multicast 50 Hz──► motion_capture_tracking ──/poses──► escort_show
   ──cmd_full_state 20 Hz/drone──► crazyflie_server ──Crazyradio──► 4 Crazyflies
```

## Where things are

- `src/crazyswarm2/crazyflie_shows/crazyflie_shows/escort.py`: the whole control law, pure
  Python, no ROS. `plan_escort.py` verifies the same objects offline; `escort_show.py`
  flies them. `abort.py`, `preflight.py`, `safety.py` are the shared safety machinery.
  `swarm_show`, `constellation*`, `choreography`, `figures`, `demo_show`, `plan_show` belong
  to two older shows; the escort imports a few helpers from them, so they stay.
- `src/crazyswarm2/crazyflie/config/`: `crazyflies.yaml` is the ONLY fleet roster;
  `arena.yaml` is the measured room (`measured: false` makes every planner refuse).
- `src/crazyswarm2/crazyflie/src/crazyflie_server.cpp`: heavily patched; read
  `docs/details/server-changes.md` before touching it.
- `console/`: optional web GUI, removable (`rm -rf console/` changes nothing else).
  Drives the `ros2` CLI as subprocesses, never in-process rclpy. Its escort screen is
  `src/crazyswarm2/crazyflie_shows/missions/escort.yaml`. Read `console/README.md` first.
- `docs/01-…05-*.md`: beginner guides. `docs/details/`: everything implementation-specific.
  `docs/diagrams/escort-diagrams.pptx`: the source of every diagram (no mermaid);
  `docs/diagrams/export_png.sh` regenerates the PNGs.

## Build and run

```bash
./scripts/setup.sh                      # once: deps + build
./scripts/build.sh [package]            # after editing src/, then re-source install/setup.bash
ros2 launch crazyflie launch.py backend:=sim
ros2 run crazyflie_shows plan_escort
ros2 run crazyflie_shows escort_show --ros-args -p use_sim_time:=true -p vip_mode:=point -p paced:=true
```

## Rules that prevent real accidents

The evidence for each is in `docs/details/known-issues.md`; read the entry before
re-investigating any of these.

- **Scan before every launch** (`./scripts/scan_fleet.sh`). The server hangs silently
  forever on the first enabled drone that does not answer.
- **Never `apt install ros-<distro>-motion-capture-tracking`.** The vendored copy is the
  fixed one; the apt one silently receives nothing here.
- **`initial_position` comes from `/poses`** (`scripts/sync_initial_positions.py`),
  never from `/cfX/pose`. Re-run `plan_escort --marks` after every sync.
- **`use_sim_time:=true` in the simulator, never on hardware.** Restart the sim launch
  between escort runs.
- **Set `ROS_DOMAIN_ID`.** Domain 0 is shared with the rest of the lab.
- **After an E-STOP, every drone needs a battery re-plug** (supervisor LOCKED).
- **Shows must use `abort.take_signals()`** and set `armed = True` before the arm loop;
  `ShowAborted` is a `BaseException`, so never wrap a gate in a bare `except Exception`.
- **Any new compiler warning in `src/crazyswarm2` or `src/natnet_ros2` is a regression.**
  The ~25 remaining warnings are in third-party deps and were reviewed; do not silence them.
- **Never `stop_stack.sh`** while the user may have a stack up: it stops every stack on
  the machine. For test stacks use a private `ROS_DOMAIN_ID` and stop them by PID.

## Writing docs here

Beginner guides stay short, plain and free of implementation detail; anything that
needs code names, history or maths goes in `docs/details/`. Never write the fleet
roster, marks or arena numbers into prose: print them (`scan_fleet.sh --list`,
`plan_escort --marks`). New diagrams go into the PowerPoint deck, not mermaid.
