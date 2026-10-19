# Launching, checks and LEDs

General rig commands that are not specific to the escort: the launch, a one-drone
test flight, health checks, LEDs and every launch argument. The escort itself is in
[../02-run-the-demo.md](../02-run-the-demo.md).

Activate the workspace in every terminal first:

```bash
source /opt/ros/$ROS_DISTRO/setup.bash
source install/setup.bash          # from the repo folder
```

> Config files referred to below as `config/<name>.yaml` live at
> `src/crazyswarm2/crazyflie/config/<name>.yaml`. Edit them there and rebuild.

---

## A. Simulation (no hardware, no mocap)

The fastest way to verify the install. Uses the built-in `np` backend.

> **One-time prerequisite:** the sim imports the `cffirmware` bindings. If you see
> `ModuleNotFoundError: No module named 'cffirmware'`, run
> `./scripts/setup_sim_firmware.sh` once ([setup step 4](../01-setup.md#step-4-build-the-simulator-simulator-only)).

```bash
ros2 launch crazyflie launch.py backend:=sim
# in another terminal, run an example against the sim:
ros2 launch crazyflie_examples launch.py script:=hello_world
```

> Any script that streams setpoints or sleeps on a schedule (the escort included)
> **requires** `--ros-args -p use_sim_time:=true` in the sim: the sim clock runs
> ~4x slower than wall time and the script otherwise races ahead of the physics.

RViz opens by default (`rviz:=false` to disable) and shows the simulated drone.
The [preflight GUI](preflight-gui.md) also opens by default; in sim there is no mocap so
its mocap panels stay empty — pass `preflight:=False` if you don't want it.
Backend/controller/visualization options are in `config/server.yaml`
(`sim:` section).

## B. Hardware flight with OptiTrack

This is the real-world takeoff → hover → land flow for one drone.

The `motion_capture_tracking` node started by `launch.py` connects **directly** to
Motive over the network and publishes `/poses` — you do **not** start a separate
driver or bridge for this path.

### Prerequisites

1. Calibrate the cameras and define a rigid body per drone — see
   [mocap.md](mocap.md). The rigid-body name must match the robot key in
   `config/crazyflies.yaml` (e.g. `cf1`).
2. In **Motive → Settings → Streaming**, set the data signal type to
   **Multicast** and the rate to **50 Hz**. This **must match**
   `config/motion_capture.yaml` in the crazyswarm2 package
   (`type: "optitrack"` — the open parser, **required on Wi-Fi** and fine on
   LAN — and `poses.qos.deadline: 50.0`). A `type: "optitrack_closed_source"`
   option exists but hangs **permanently** after a Wi-Fi multicast stall — don't
   use it. A mismatch here is the most common reason the drone won't localize.

### Fly

```bash
# terminal 0 — go/no-go BEFORE the server. The server blocks silently and forever
# on the first enabled drone that does not answer; this scan derives its address
# list from crazyflies.yaml and prints GO or NO-GO per drone.
./scripts/scan_fleet.sh

# terminal 1 — start the Crazyflie server (also starts mocap tracking, RViz,
# the preflight GUI and the Foxglove bridge — all on by default)
ros2 launch crazyflie launch.py

# run the preflight checklist in the GUI — see preflight-gui.md

# terminal 2 — takeoff, hover, land
ros2 run crazyflie_examples hello_world
```

The drone arms, takes off, hovers, then lands and disarms. Don't skip the
preflight check: it is the only thing that catches a rotated Motive rigid body
before it becomes a fly-away ([preflight-gui.md](preflight-gui.md#the-orientation-warning-read-this)).

### Adjusting the flight (hello_world.py)

The behaviour is set by a few values at the top of and inside
`crazyflie_examples/hello_world.py`:

| What | Where in the script | Default |
|------|--------------------|---------|
| **Takeoff duration** (time to climb) | `TAKEOFF_DURATION` | `5.0` s |
| **Hover duration** (time held in the air) | `HOVER_DURATION` | `5.0` s |
| **Hover height** (target altitude) | `cf.takeoff(targetHeight=0.5, ...)` | `0.5` m |
| **Landing height** (touchdown target) | `cf.land(targetHeight=0.03, ...)` | `0.03` m |
| **Landing duration** (time to descend) | `cf.land(..., duration=3.0)` | `3.0` s |

Reading the script: it builds a `Crazyswarm()`, grabs the first drone, then
`arm(True)` → `takeoff(targetHeight, duration)` → `sleep(TAKEOFF + HOVER)` →
`land(targetHeight, duration)` → `arm(False)`. So raise `targetHeight` in
`takeoff()` to hover higher, increase `HOVER_DURATION` to hover longer, and tune
the `land()` arguments for a slower/softer or lower touchdown. Start low (≤0.5 m)
for first flights.

### Visualization

Two viewers, both optional:

- **RViz** — on by default (`rviz:=false` to disable). It shows two frames
  per drone: `cf1` (the **onboard EKF** state estimate) and `cf1_mocap` (the raw
  **mocap** pose). They should sit almost on top of each other; a large or growing
  gap means the estimator and mocap disagree (bad calibration, marker/rigid-body
  issue, or estimator not converged). Rotated axes between the two frames mean
  the rigid body was defined with a yaw offset — the [preflight GUI](preflight-gui.md)
  quantifies this as `err.yaw`.
- **Foxglove** — on by default (`foxglove:=True`), but needs the bridge package
  installed (`sudo apt install ros-$ROS_DISTRO-foxglove-bridge`). It's not a
  window: open the Foxglove Studio app and connect to `ws://localhost:8765` to
  inspect topics, poses, and TF live.

### Verifying the pose pipeline

```bash
ros2 topic hz /poses          # mocap tracking publishing? should be ~50 Hz
ros2 topic echo /cf1/pose --once   # onboard pose estimate (firmware logging)
ros2 topic echo /cf1/status --once # battery / supervisor / link health
```

If `/poses` is silent → fix Motive streaming (Multicast + 50 Hz, Broadcast Frame
on) or the hostname/IP in `config/motion_capture.yaml` — it must be the Motive
PC's **current** address, which changes when you switch between Wi-Fi and LAN
([mocap.md section 5](mocap.md#5-networking-mocap-over-a-router-lab-setup)). If `/poses` **was**
flowing and stopped, check `ros2 topic info /poses` — 0 publishers means the
mocap node is dead or starved (a leftover process on UDP 1511 is the confirmed
cause on this rig). See [troubleshooting.md](troubleshooting.md#mocap-pipeline).

> **Alternative (open NatNet driver).** If you stream via the open-source
> `natnet_ros2` driver instead of the closed-source direct client, start it and
> the bridge separately: `ros2 launch natnet_ros2 natnet_ros2.launch.py` then
> `python3 ~/CrazySwarm2-with-Mocap/scripts/pose_bridge.py` (republishes per-body poses to `/poses`
> at 50 Hz). The flight steps above are otherwise identical.

## F. Useful checks

```bash
ros2 node list
ros2 topic list
ros2 service list | grep -E 'takeoff|land|go_to|arm'

# battery / link health (status topic must be enabled in crazyflies.yaml)
ros2 topic echo /cf1/status --once
ros2 topic echo /cf1/connection_statistics --once
```

> **If the `/all/*` services (takeoff/land/arm/emergency) never appear**, the
> server is **blocked forever, silently, on the first enabled drone that
> doesn't answer radio** (it connects drones in lexicographic `std::map`
> order). Any cause counts: a dead drone (cf6 went silent 2026-08-04), a wrong
> address, or a **datarate mismatch** — learned the hard way with cf11 (a `2M`
> URI on a drone whose radio runs at `1M`). No error is printed, and the hung
> server needs SIGKILL. **Go/no-go rule: scan every enabled address before
> every launch** — `./scripts/scan_fleet.sh`, which derives the address list
> from `crazyflies.yaml` and reports GO/NO-GO. Do not scan a list written down
> here or anywhere else: the enabled set changes between shows, and the stale
> copies in this file used to name two drones that no longer exist while
> omitting one that flies. Then fix
> the URI or disable the drone in `config/crazyflies.yaml`. See
> [troubleshooting.md](troubleshooting.md#crazyradio--drones) and — when running
> two dongles — the rules in
> [mocap.md section 3c](mocap.md#3c-trim-drone-log-topics-to-protect-radio-bandwidth).

### Prop-spin ground test (`arming` example)

```bash
ros2 run crazyflie_examples arming   # server must be running
```

Arms every enabled drone and spins all four propellers at **low PWM**
(`SPIN_PWM = 10000`/65535, ~15% — hover needs roughly 38000+) for
`SPIN_SECONDS = 10.0` s, then stops and disarms. A brushed CF2.1 does **not**
idle-spin its props on arming (that's Bolt/brushless behavior), so this
drives the firmware's motor-test params (`motorPowerSet.*`, the same path as
cfclient's propeller test) for a visible motors-alive check. Motors are
always stopped in a `finally:` block, even on Ctrl-C.

> **Ground test only.** Props spin — keep the drone on the floor and fingers
> clear. The PWM is far below hover thrust, so the drone stays put.

### Color LED deck — status convention and manual control

Drones carrying the bottom Color LED deck (`colorLedBot`) double as a status
indicator. **Green LED = drone connected and ready for command. Red LED =
drones are in flight / a script is controlling them.** In detail:

- **Green** — connected and ready for command (the cpp server sets green on
  connect; the drone is idle, no script owns it).
- **Red** — in flight / under script control (`Crazyswarm()` turns the deck
  red for its lifetime; an `atexit` hook in `crazyswarm_py.py` restores green
  on exit — normal return, exception, or Ctrl-C).
- **Dark** — clean server shutdown (the server switches the LED off on
  disconnect; after a hard link loss it keeps its last color instead).

Manual control, two equivalent front-ends (number keys:
`0`=off `1`=green `2`=red `3`=yellow `4`=blue `5`=purple `9`=white):

```bash
./scripts/led.sh 3                        # one-shot: yellow, then exit
./scripts/led.sh                          # interactive: press number keys, q quits
ros2 run crazyflie_examples color_led 3   # same key map / color names
```

Both set the firmware param `colorLedBot.wrgb8888` (uint32 packed
`0xWWRRGGBB`) on every connected drone. They deliberately avoid
`Crazyswarm()`: `led.sh` goes through the **`ros2` CLI daemon** (`ros2 param
set`), which keeps the ROS graph warm, while `color_led` calls the server's
`/crazyflie_server/set_parameters` service directly — on this rig fresh rclpy
processes can stall in DDS discovery and `Crazyswarm()` hangs waiting on
`all/emergency` (see [troubleshooting.md](troubleshooting.md#ros-2--dds--parameters)).

### Runtime firmware parameters

`ros2 param set` now **reliably reaches the drones** — the vendored
`server.cpp` applies `<cf>.params.*` / `all.params.*` changes in an
on-set-parameters callback that runs synchronously inside the service call
(upstream's `/parameter_events` handler never saw the node's own events on
this rig, so runtime changes silently never left the PC). With
`firmware_params.query_all_values_on_connect: True` in `config/server.yaml`,
every firmware param is exposed at connect:

```bash
ros2 param set /crazyflie_server cf1.params.ring.effect 7   # per drone
ros2 param set /crazyflie_server all.params.kalman.resetEstimation 1   # broadcast
```

### Viewing a drone's topics (ROS_DOMAIN_ID)

In this setup **all drones share the same ROS domain** — they are **not** separated
by `ROS_DOMAIN_ID`. Each drone is separated by its **namespace** instead, e.g.
`/cf1/pose`, `/cf2/pose`. To narrow the topic list to one drone, filter by namespace:

```bash
ros2 topic list | grep cf1        # only cf1's topics
ros2 topic echo /cf1/pose         # echo a specific drone topic
```

`ROS_DOMAIN_ID` only matters in two cases:

1. **Your terminal sees no topics at all.** The shell's `ROS_DOMAIN_ID` must
   **match** the one the crazyflie stack was launched with (default `0`). In every
   terminal that needs to see the topics, set the same value (and a matching
   `ROS_LOCALHOST_ONLY`), then re-list:
   ```bash
   export ROS_DOMAIN_ID=<same value as the running stack>
   ros2 topic list
   ```
2. **Shared lab network / multiple users on one machine.** Pick a unique
   `ROS_DOMAIN_ID` (0–101) and `export ROS_LOCALHOST_ONLY=1` so you don't see — or
   accidentally command — someone else's robots. (See upstream crazyswarm2
   `docs2/usage.rst`.)

> The `natnet_ros2` helper GUI (`src/natnet_ros2/scripts/helper_node_r2.py`) has a
> domain-id selector — it sets which domain the **NatNet driver node** publishes on,
> i.e. the driver's domain, not a per-drone separation.

## G. Enabling extra telemetry logging (custom topics)

The drones can stream onboard firmware variables back as ROS topics. This is
configured under `all.firmware_logging.custom_topics` in
`config/crazyflies.yaml`. Several example blocks are shipped **commented out** —
enable them by uncommenting.

```yaml
all:
  firmware_logging:
    enabled: true
    custom_topics:
      kalman_preflight:   # enabled by default -> /cf1/kalman_preflight
        frequency: 5      # feeds the [preflight GUI](preflight-gui.md) — keep it
        vars: [kalman.stateX, kalman.stateY, kalman.stateZ, motion.deltaX,
               motion.deltaY, range.zrange, stateEstimateZ.vx, stateEstimateZ.vy]
      # attitude:         # uncomment to enable -> /cf1/attitude
      #   frequency: 10
      #   vars: [stabilizer.roll, stabilizer.pitch, stabilizer.yaw]
      # battery:          # uncomment to enable -> /cf1/battery
      #   frequency: 1
      #   vars: [pm.vbat, pm.state]
```

The `kalman_preflight` block is what the preflight GUI plots — leave it enabled
(it uses 22 B of the 26 B log-block budget; every var must exist in the
firmware's log TOC or the cpp server aborts at connect).

**To enable a log topic:**

1. Uncomment the block (remove the leading `# `), or add your own. Each top-level
   key (`attitude`, `battery`, …) becomes the ROS topic name `/<cf>/<name>`.
2. Set `frequency` (Hz) — **keep it low**; every block shares the Crazyradio
   bandwidth (see [mocap.md section 3c](mocap.md#3c-trim-drone-log-topics-to-protect-radio-bandwidth)).
3. List the firmware `vars` you want. Discover valid names with:
   ```bash
   ros2 run crazyflie listLogVariables --uri radio://0/80/2M/E7E7E7E701
   ```
4. Rebuild and relaunch:
   ```bash
   ./scripts/build.sh crazyflie     # rebuild after editing the config
   ros2 launch crazyflie launch.py
   ```

**To view a topic** (type is `crazyflie_interfaces/LogDataGeneric`):

```bash
ros2 topic list | grep cf1          # see which log topics exist
ros2 topic echo /cf1/attitude       # live values
ros2 topic hz /cf1/attitude         # confirm it streams at the set rate
```

The `values` array in `LogDataGeneric` is ordered exactly as the `vars` list.
The `default_topics` (`pose`, `status`) are enabled the same way — they're just
predefined names the server understands.

> Tip: enable high-rate blocks (e.g. 50 Hz attitude/kalman) only while actively
> debugging, then comment them out again for normal flight to free up the radio.

## H. Color LED control (Color LED deck)

Applies to drones carrying the bottom-mounted **Color LED deck**
(`bcColorLedBot`; the firmware must expose the `colorLedBot` params). Everything
below drives a single firmware parameter — `colorLedBot.wrgb8888`, a uint32
packed as `0xWWRRGGBB`. White uses the dedicated **W** channel (`0xFF000000`);
an RGB-mixed white looks purplish. **Hardware only** — the `sim` backend
declares no firmware params, so LED commands have no effect there.

### Automatic status behavior (no command needed)

- **Green on connect** — `crazyflie_server` sets full green when a drone
  connects; a drone without the deck just logs
  `No Color LED deck detected — skipping LED set`.
- **Red while a script runs** — `crazyflie_py`'s `Crazyswarm()` sets the deck
  red at startup and restores green on exit via an `atexit` hook, so it
  recovers on normal exit, exceptions, and Ctrl-C.

### Manual control (server must be running)

Both tools accept a color name (case-insensitive) or a number key, and share
the same mapping:

| Key | Color | Hex (WRGB) | Decimal |
|-----|-------|-----------|---------|
| `0` | black (off) | `0x000000` | `0` |
| `1` | green | `0x00FF00` | `65280` |
| `2` | red | `0xFF0000` | `16711680` |
| `3` | yellow | `0xFFFF00` | `16776960` |
| `4` | blue | `0x0000FF` | `255` |
| `5` | purple | `0x9400D3` | `9699539` |
| `9` | white | `0xFF000000` | `4278190080` |

**`scripts/led.sh` — recommended.** Wraps the `ros2 param set` CLI; the
long-running ROS 2 CLI daemon keeps the graph warm, which makes this the most
reliable path. It re-discovers every connected drone's LED param on each color
change, so all drones with the deck switch together.

```bash
./scripts/led.sh yellow     # one-shot by name
./scripts/led.sh 3          # one-shot by number key (= yellow)
./scripts/led.sh 0          # off (same as "black")
./scripts/led.sh            # interactive — press 0-5/9 to switch, q to quit
```

**`ros2 run crazyflie_examples color_led`** — the same control as an rclpy
node (calls `/crazyflie_server/set_parameters` directly; needs the workspace
built and sourced):

```bash
ros2 run crazyflie_examples color_led yellow
ros2 run crazyflie_examples color_led 3
ros2 run crazyflie_examples color_led       # interactive (q or Ctrl-C quits)
```

**Raw CLI** — what both boil down to (decimal value, one drone at a time):

```bash
ros2 param set /crazyflie_server cf1.params.colorLedBot.wrgb8888 16776960   # yellow
```

Auto-discovery of the per-drone LED params requires
`firmware_params: query_all_values_on_connect: True` in `config/server.yaml` —
already set in this repo (it makes connecting slightly slower).

### Standalone cflib demo (server must be STOPPED)

`scripts/color_led_cflib.py` talks to one drone directly over the Crazyradio
with cflib — no ROS involved. It plays a fixed sequence
(green → red → green → blue → white → off) and exits.

```bash
# stop `ros2 launch crazyflie launch.py` first — cflib and the server
# cannot share the radio dongle
python3 scripts/color_led_cflib.py
```

The target URI is hardcoded near the top of the file (marked `# EDIT ME`) —
set it to the drone you want. The script also enables the deck's brightness
correction (`colorLedBot.brightCorr = 1`) on connect.

## Launch arguments (crazyflie launch.py)

| Arg | Values | Meaning |
|-----|--------|---------|
| `backend` | `cpp` \| `cflib` \| `sim` | Hardware (C++/Python) or simulation |
| `mocap` | `True` \| `False` | Start the motion_capture_tracking node (default `True`) |
| `teleop` | `True` \| `False` | Start joystick teleop + joy node (default `True`) |
| `rviz` | `True` \| `False` | Start RViz (default **`True`**; `rviz:=false` to disable) |
| `preflight` | `True` \| `False` | Start the preflight GUI (default **`True`**; see preflight-gui.md) |
| `gui` | `True` \| `False` | Start the swarm GUI (default **`False`**) |
| `foxglove` | `True` \| `False` | Start the foxglove bridge (default `True`; needs `ros-$ROS_DISTRO-foxglove-bridge`) |
| `debug` | `True` \| `False` | Launch the C++ server under gdb (default `False`) |
| `server` | `True` \| `False` | `False` = mocap + RViz + preflight GUI and **no server**: no radio owner, nothing armable. The state `scripts/sync_initial_positions.py` wants (default `True`) |
| `mocap_hostname` | IPv4 literal | Motive PC address; overrides `hostname: "auto"` in `motion_capture.yaml`. Also read from env `CRAZYSWARM_MOCAP_HOST` |
| `trace_cf` | `all` \| `cf1,cf3` \| empty | Per-second packet-trace summaries per drone (read at connect). A **launch** argument, not `--ros-args` |
| `crazyflies_yaml_file`, `motion_capture_yaml_file`, `rviz_config_file`, `teleop_yaml_file` | path | One-off config overrides. A fleet override desyncs the file the server reads from the file `sync_initial_positions.py` writes; prefer editing `enabled:` in the one yaml |
