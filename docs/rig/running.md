# Launching, checks and LEDs

General rig commands that belong to no demo: the launch, a one-drone test flight, health
checks, LEDs, logging and every launch argument. The demos share
[../02-flight-day.md](../02-flight-day.md); each has its own run page
([escort](../escort/run.md), [STL](../stl/run.md), [guard](../guard/run.md),
[serpent](../serpent/run.md)). Every terminal is opened as in
[setup step 5](../01-setup.md#step-5-open-a-terminal-the-right-way).

`config/<name>.yaml` below means `src/crazyswarm2/crazyflie/config/<name>.yaml`. Edit it
there and rebuild.

## A. Simulation (no hardware, no mocap)

The fastest check of an install. It needs the `cffirmware` bindings once
([setup step 4](../01-setup.md#step-4-build-the-simulator-simulator-only); the symptom is
`No module named 'cffirmware'`).

```bash
ros2 launch crazyflie launch.py backend:=sim
ros2 launch crazyflie_examples launch.py script:=hello_world   # second terminal
```

Any script that streams setpoints or sleeps on a schedule (every show) **needs**
`--ros-args -p use_sim_time:=true` in the simulator. The sim clock follows the wall clock
only approximately (`sim.realtime`, default true) and runs flat out with
`sim.realtime:=false`, so a script on the wall clock drifts away from the physics.

RViz and the [preflight GUI](preflight-gui.md) open by default (`rviz:=false`,
`preflight:=False` to skip them); with no mocap, the preflight GUI's mocap panels stay
empty. The simulator's settings (physics backend, visualisations) are under `sim:` in
`config/server.yaml`.

## B. Hardware flight with OptiTrack

One drone: take off, hover, land. The `motion_capture_tracking` node that `launch.py`
starts talks to Motive directly and publishes `/poses`; no separate driver or bridge.

**Before:** one Motive rigid body per drone, named as in `config/crazyflies.yaml`, and
Motive streaming Multicast at 50 Hz ([mocap.md](mocap.md),
[flight day](../02-flight-day.md#once-before-the-first-flight)). The rate must match
`poses.qos.deadline` in `config/motion_capture.yaml`, whose parser `type: "optitrack"`
(the open one) must stay: `optitrack_closed_source` hangs for good after a Wi-Fi multicast
stall. A mismatch here is the most common reason a drone will not localise.

```bash
./scripts/scan_fleet.sh                    # terminal 0: every enabled drone must say GO
ros2 launch crazyflie launch.py            # terminal 1: mocap, server, RViz, preflight GUI, Foxglove bridge
# check the drone in the preflight GUI (preflight-gui.md)
ros2 run crazyflie_examples hello_world    # terminal 2: arm, take off, hover, land, disarm
```

Do not skip the preflight check: it is the only thing that catches a rotated rigid body
before it becomes a fly-away ([preflight-gui.md](preflight-gui.md#the-orientation-warning-read-this)).

`crazyflie_examples/hello_world.py` is `arm` → `takeoff` → sleep → `land` → `disarm`.
Its values:

| What | In the script | Default |
|------|--------------------|---------|
| Climb time | `TAKEOFF_DURATION` | `5.0` s |
| Hover time | `HOVER_DURATION` | `5.0` s |
| Hover height | `cf.takeoff(targetHeight=0.5, ...)` | `0.5` m |
| Touchdown height | `cf.land(targetHeight=0.03, ...)` | `0.03` m |
| Descent time | `cf.land(..., duration=3.0)` | `3.0` s |

Start low (≤ 0.5 m) for first flights.

### Visualization

- **RViz** (on by default) shows two frames per drone: `cf1` (the onboard estimate) and
  `cf1_mocap` (the raw mocap pose). They should overlap. A growing gap means the estimator
  and mocap disagree; rotated axes mean the rigid body has a yaw offset, which the
  preflight GUI measures as `err.yaw`.
- **Foxglove** (`foxglove:=True` by default) needs
  `sudo apt install ros-$ROS_DISTRO-foxglove-bridge`. It is not a window: connect the
  Foxglove app to `ws://localhost:8765`.

### Verifying the pose pipeline

```bash
ros2 topic hz /poses               # ~50 Hz
ros2 topic echo /cf1/pose --once   # onboard estimate
ros2 topic echo /cf1/status --once # battery, supervisor, link
```

`/poses` silent: fix Motive streaming (Multicast, 50 Hz, Broadcast Frame on) or the
network ([mocap.md section 5](mocap.md#5-networking-mocap-over-a-router-lab-setup)).
`/poses` stopped after flowing: `ros2 topic info /poses`; 0 publishers means the mocap node
is dead or starved, and a leftover process on UDP 1511 is the confirmed cause here
([troubleshooting.md](troubleshooting.md#mocap-pipeline)).

> **Alternative: the `natnet_ros2` driver.** To stream through it instead of
> `motion_capture_tracking`, start it and the bridge yourself:
> `ros2 launch natnet_ros2 natnet_ros2.launch.py`, then `python3 scripts/pose_bridge.py`
> (republishes per-body poses to `/poses` at 50 Hz). The flight steps are the same.

## F. Useful checks

```bash
ros2 node list
ros2 topic list
ros2 service list | grep -E 'takeoff|land|go_to|arm'
ros2 topic echo /cf1/status --once                  # status topic must be enabled in crazyflies.yaml
ros2 topic echo /cf1/connection_statistics --once
```

> **The `/all/*` services never appear:** the server is **blocked, silently and for
> good, on the first enabled drone that does not answer** (it connects drones in name
> order). A dead drone, a wrong address or a **datarate mismatch** (a `2M` URI on a drone
> whose radio runs at `1M`) all do it; nothing is printed and the server needs SIGKILL.
> That is why `./scripts/scan_fleet.sh` runs before every launch: it reads the enabled
> addresses from `crazyflies.yaml`, so never scan a list written down anywhere. Then fix
> the URI or disable the drone. More: [troubleshooting.md](troubleshooting.md#crazyradio--drones);
> two dongles: [mocap.md section 3c](mocap.md#3c-trim-drone-log-topics-to-protect-radio-bandwidth).

### Testing on the mocap Wi-Fi without internet (`offline_window.sh`)

With the wired port taken, the laptop is on one Wi-Fi at a time: `motive` (mocap, no
internet) or the internet one. `scripts/offline_window.sh` runs a probe on `motive` and
always switches back: it syntax-checks the probe, logs to `log/offline/<stamp>/run.log`,
opens a window that follows the log, and a watchdog reconnects the internet Wi-Fi even if
the script is killed. It refuses while a crazyflie server or mocap node runs, and keeps
what it starts on a private `ROS_DOMAIN_ID`.

```bash
scripts/offline_window.sh --dry-run console_network   # all phases, no network switch
scripts/offline_window.sh console_network             # the real thing (~3 min offline)
```

Probes live in `scripts/offline_probes/`; the header of `offline_window.sh` says how to
write one. `console_network` checks the console, its journal, the mission window
(headless Chrome) and Motive discovery across a switch; its browser tests need Node ≥ 22
(nvm) and `google-chrome`, and are skipped without them.

### Prop-spin ground test (`arming` example)

```bash
ros2 run crazyflie_examples arming   # server must be running
```

Arms every enabled drone and spins the props at **low PWM** (`SPIN_PWM = 10000` of 65535,
~15%; hover needs roughly 38000+) for `SPIN_SECONDS = 10.0`, then stops and disarms. A
brushed CF2.1 does not idle-spin on arming, so this drives the firmware's motor-test
params (`motorPowerSet.*`, as cfclient's propeller test does). Motors stop in a `finally:`
block, even on Ctrl-C. **Ground test only**: keep the drone on the floor and fingers
clear.

### Color LED deck — status convention and manual control

For drones with the bottom Color LED deck. **Hardware only**: the simulator has no
firmware params.

| Colour | Means | Set by |
|---|---|---|
| **Green** | connected, idle, ready for a command | the server, on connect (a drone without the deck logs `No Color LED deck detected — skipping LED set`) |
| **Red** | a script controls it (in flight) | `Crazyswarm()`, for its lifetime; an `atexit` hook restores green on exit, exception or Ctrl-C |
| **Dark** | clean server shutdown | the server, on disconnect (after a hard link loss it keeps its last colour) |

Manual control, server running. Both tools take a number key or a colour name:

| Key | Colour | Hex (WRGB) | Decimal |
|-----|-------|-----------|---------|
| `0` | black (off) | `0x000000` | `0` |
| `1` | green | `0x00FF00` | `65280` |
| `2` | red | `0xFF0000` | `16711680` |
| `3` | yellow | `0xFFFF00` | `16776960` |
| `4` | blue | `0x0000FF` | `255` |
| `5` | purple | `0x9400D3` | `9699539` |
| `9` | white | `0xFF000000` | `4278190080` |

```bash
./scripts/led.sh 3                          # one-shot (or: ./scripts/led.sh yellow)
./scripts/led.sh                            # interactive: number keys, q quits
ros2 run crazyflie_examples color_led 3     # the same, as an rclpy node
ros2 param set /crazyflie_server cf1.params.colorLedBot.wrgb8888 16776960   # raw, one drone
```

All set the firmware param `colorLedBot.wrgb8888` (`0xWWRRGGBB`; white uses the W
channel, because RGB-mixed white looks purple). `led.sh` is the most reliable: it goes
through the `ros2` CLI daemon, which keeps the graph warm, and re-discovers every drone's
LED param on each change. `color_led` calls `/crazyflie_server/set_parameters` directly.
Neither uses `Crazyswarm()`, which can hang here waiting on `all/emergency` because fresh
rclpy processes can stall in DDS discovery
([troubleshooting.md](troubleshooting.md#ros-2--dds--parameters)). Discovery needs
`firmware_params: query_all_values_on_connect: True` in `config/server.yaml` (set; it makes
connecting slightly slower).

**Without ROS** (server **stopped**: cflib and the server cannot share the dongle):
`python3 scripts/color_led_cflib.py` plays green, red, green, blue, white, off on one drone
and exits. Its URI is hard-coded at the top (`# EDIT ME`); it also sets
`colorLedBot.brightCorr = 1`.

### Runtime firmware parameters

`ros2 param set` reaches the drones: the vendored server applies `<cf>.params.*` /
`all.params.*` in an on-set-parameters callback inside the service call (upstream's
`/parameter_events` handler never fired on this rig). With
`firmware_params.query_all_values_on_connect: True` in `config/server.yaml`, every
firmware param is exposed at connect:

```bash
ros2 param set /crazyflie_server cf1.params.ring.effect 7              # one drone
ros2 param set /crazyflie_server all.params.kalman.resetEstimation 1   # broadcast
```

### Viewing a drone's topics (ROS_DOMAIN_ID)

All drones share one ROS domain; each has its own namespace (`/cf1/pose`, `/cf2/pose`):

```bash
ros2 topic list | grep cf1
ros2 topic echo /cf1/pose
```

`ROS_DOMAIN_ID` matters in two cases:

1. **A terminal sees no topics at all**: its `ROS_DOMAIN_ID` (and `ROS_LOCALHOST_ONLY`)
   must match the stack's. `export ROS_DOMAIN_ID=<the stack's>`, then list again.
2. **The lab network is shared**: pick an ID nobody else uses (0–101) and
   `export ROS_LOCALHOST_ONLY=1`, so you neither see nor command someone else's robots.

The `natnet_ros2` helper GUI's domain selector sets the domain the NatNet driver publishes
on, not a per-drone separation.

## G. Enabling extra telemetry logging (custom topics)

Drones can stream firmware variables as ROS topics, configured under
`all.firmware_logging.custom_topics` in `config/crazyflies.yaml`. Example blocks ship
commented out:

```yaml
all:
  firmware_logging:
    enabled: true
    custom_topics:
      kalman_preflight:   # enabled -> /cf1/kalman_preflight; feeds the preflight GUI, keep it
        frequency: 5
        vars: [kalman.stateX, kalman.stateY, kalman.stateZ, motion.deltaX,
               motion.deltaY, range.zrange, stateEstimateZ.vx, stateEstimateZ.vy]
      # attitude:         # uncomment to enable -> /cf1/attitude
      #   frequency: 10
      #   vars: [stabilizer.roll, stabilizer.pitch, stabilizer.yaw]
      # battery:          # uncomment to enable -> /cf1/battery
      #   frequency: 1
      #   vars: [pm.vbat, pm.state]
```

`kalman_preflight` uses 22 B of the 26 B log-block budget. Every var must exist in the
firmware's log TOC, or the cpp server aborts at connect.

1. Uncomment a block or add one; its key becomes the topic `/<cf>/<name>`.
2. Keep `frequency` (Hz) **low**: every block shares the radio
   ([mocap.md section 3c](mocap.md#3c-trim-drone-log-topics-to-protect-radio-bandwidth)).
   Turn high-rate blocks on only while debugging.
3. List the `vars`. Valid names:
   `ros2 run crazyflie listLogVariables --uri radio://0/80/2M/E7E7E7E701`
4. `./scripts/build.sh crazyflie`, then relaunch.

The topic type is `crazyflie_interfaces/LogDataGeneric`; its `values` follow the order of
`vars`. Check it with `ros2 topic echo /cf1/attitude` and `ros2 topic hz /cf1/attitude`.
The `default_topics` (`pose`, `status`) are enabled the same way.

## Launch arguments (crazyflie launch.py)

| Arg | Values | Meaning |
|-----|--------|---------|
| `backend` | `cpp` \| `cflib` \| `sim` | Hardware (C++ or Python server) or simulation |
| `mocap` | `True` \| `False` | Start motion_capture_tracking (default `True`) |
| `teleop` | `True` \| `False` | Start joystick teleop + joy node (default `True`) |
| `rviz` | `True` \| `False` | Start RViz (default `True`) |
| `preflight` | `True` \| `False` | Start the preflight GUI (default `True`) |
| `gui` | `True` \| `False` | Start the swarm GUI (default `False`) |
| `foxglove` | `True` \| `False` | Start the foxglove bridge (default `True`; needs `ros-$ROS_DISTRO-foxglove-bridge`) |
| `debug` | `True` \| `False` | Run the C++ server under gdb (default `False`) |
| `server` | `True` \| `False` | `False` = mocap, RViz and preflight GUI with **no server**: nothing owns the radio, nothing can arm. What `sync_initial_positions.py` wants (default `True`) |
| `mocap_hostname` | IPv4 literal | Motive PC address; overrides `hostname: "auto"` in `motion_capture.yaml`. Also read from `CRAZYSWARM_MOCAP_HOST` |
| `trace_cf` | `all` \| `cf1,cf3` \| empty | Per-second packet-trace summaries per drone, read at connect. A **launch** argument, not `--ros-args` |
| `crazyflies_yaml_file`, `motion_capture_yaml_file`, `rviz_config_file`, `teleop_yaml_file` | path | One-off config overrides. A fleet override splits the file the server reads from the one `sync_initial_positions.py` writes; prefer editing `enabled:` in the one yaml |

---

Full earlier text: `git show 678bac1:docs/rig/running.md`
