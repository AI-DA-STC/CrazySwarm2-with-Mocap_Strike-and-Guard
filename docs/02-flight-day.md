# 2. Flight day: the steps every demo shares

Both demos ([escort](escort/run.md) and [STL](stl/run.md)) are flown the same way. This
page is the shared part; each demo's own page adds its checks and its fly command. Open
every terminal as shown in [setup step 5](01-setup.md#step-5-open-a-terminal-the-right-way).

## The simulator

Always run a demo in the simulator before flying it. It runs the same show script on
simulated drones.

```bash
ros2 launch crazyflie launch.py backend:=sim
```

RViz opens and shows the drones on the floor. A small "preflight" window also opens; in
the simulator you can ignore it. Then run the demo's show in a second terminal.

Three rules:

- Every show needs `use_sim_time:=true` in the simulator, and must **never** get it on
  real drones.
- **Restart the launch between runs.** The simulator cannot start a second run on the
  same drones.
- There are no lights and no camera data, so the simulator checks the logic, not the
  tracking.

## Choose the fleet

`src/crazyswarm2/crazyflie/config/crazyflies.yaml` lists every drone. Only those with
`enabled: true` connect, and **every enabled drone must be switched on and in the room**.

| Demo | Drones | Radios |
|---|---|---|
| Escort | 4 (3 defenders + 1 attacker) | one Crazyradio |
| STL | 10 (5 defenders + 5 intruders, cf10-cf14) | two: cf10-cf14 use a second Crazyradio |

Print what is enabled now: `./scripts/scan_fleet.sh --list`.

## Once, before the first flight

- **Motive:** create one rigid body per drone, named exactly as in `crazyflies.yaml`
  (`cf1`, `cf3`, ...). Point the drone's nose along the room's **+X** axis when you create
  it. How: [details/mocap.md](details/mocap.md#2-defining-rigid-bodies).
- **Motive:** set streaming to **Multicast** at **50 Hz**.

## 1. Place the drones and record where they are

Each demo's page says where its drones stand. Start the cameras **without** the drone
server, so nothing can arm, put the drones down, then record their real positions:

```bash
ros2 launch crazyflie launch.py server:=False                 # terminal 1
python3 scripts/sync_initial_positions.py --dry-run           # terminal 2: preview
python3 scripts/sync_initial_positions.py                     # write
```

Then re-run the demo's planner (it must pass) and stop terminal 1 (Ctrl-C).

## 2. Radio scan

```bash
./scripts/scan_fleet.sh          # every enabled drone must say GO
```

Do not skip this. If one enabled drone does not answer, the server hangs forever at
start, without any error message.

## 3. Launch

```bash
ros2 launch crazyflie launch.py
```

This starts the camera receiver, the drone server, RViz and the preflight window.

## 4. Preflight go / no-go

In the preflight window, check every drone (← / → switches drone):

| Check | Fly | Do not fly |
|---|---|---|
| Battery | green, above 3.8 V | red, below 3.7 V |
| `mocap [Hz]` | flat at about 50 | dropping, or 0 |
| Yaw error (`err.yaw`, dashed) | within ±5° | above 20°, or a red banner |

A yaw error means the Motive rigid body was created with the drone pointing the wrong
way. Recreate it. Screenshots of good and bad: [details/preflight-gui.md](details/preflight-gui.md).

## 5. Dry run, then fly

Every show has `-p dry_run:=true`: it runs every check and prints the plan, but arms
nothing. Then fly with the command on the demo's page.

## Stopping

| Situation | Do this |
|---|---|
| Waiting at a prompt (escort) | type `q`, press Enter: normal landing |
| Any time | **Ctrl-C**: every drone lands under control |
| A drone is misbehaving | **E-STOP** (`e` in the preflight window): motors off, drones drop |

After an E-STOP, unplug and re-plug **every** drone's battery. Until you do, the drones
refuse to arm, and there is no error message.

## The web console (optional)

Prefer buttons to terminals? Run `./console/run.sh`, open http://localhost:8077, and pick
the demo under **Missions**. Each demo gets its own window with a 3D view, its settings
and **Abort & land** (the same as Ctrl-C). Every button shows the exact command it runs.
More: [details/console.md](details/console.md) and
[details/mission-window.md](details/mission-window.md).
