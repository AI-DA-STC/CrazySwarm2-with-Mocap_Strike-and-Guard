# Known issues: the evidence

One entry per silent failure this rig has hit, and one per rule in `CLAUDE.md`: what
happens, the evidence, and where the fix is. Read the entry before re-investigating
anything here; most took days to find. The symptom → fix tables are in
[troubleshooting.md](troubleshooting.md). "The server" is
`src/crazyswarm2/crazyflie/src/crazyflie_server.cpp`; what was changed in it, and how, is
in [server-changes.md](server-changes.md).

## The rules in CLAUDE.md

### The server hangs forever on the first unreachable drone

The server connects the enabled drones in lexicographic (`std::map`) order and blocks,
silently and for good, on the first one that does not answer the radio: no error, no
`/all/*` services, and the hung server needs SIGKILL. Seen causes: a dead drone (cf6,
2026-08-04: silent on full channel and datarate sweeps at its own and at the factory
address, so a physical check was needed), a wrong address, and a URI datarate that does
not match the drone (a `2M` URI for a radio running `1M`; a scan of the drone's address
shows its real rate, e.g. `radio://*/90/1M/...`).

**Rule:** `./scripts/scan_fleet.sh` before every launch. It reads the list from
`crazyflies.yaml`; the five lists once written into the docs had all drifted, and none
named the drone the yaml marks intermittent.

### Never install the apt motion-capture-tracking

`ros-<distro>-motion-capture-tracking` 1.0.9 hard-codes a foreign interface address,
`141.23.110.162`, into the NatNet socket. The node then aborts (exit -6,
`set_option: No such device`) or never binds and publishes nothing, forever. Every apt
version also mis-parses Motive's NatNet 4.2 model definition and can segfault. The
vendored copy in `src/motion_capture_tracking` is the fixed one
([VENDORED.md](../../src/motion_capture_tracking/VENDORED.md)); `install_deps.sh`
removes the apt package so it cannot shadow the build. Check:
`ros2 pkg prefix motion_capture_tracking` must print `.../install/motion_capture_tracking`.

### `initial_position` comes from `/poses`, never `/cfX/pose`

The onboard estimate `/cfX/pose` is seeded from the yaml, so copying it back is circular.
`scripts/sync_initial_positions.py` copies from `/poses` and carries the refusals a hand
edit lacks (procedure: [mocap.md 2b](mocap.md#2b-setting-initial_position-from-poses)).
The flight scripts compute absolute `goTo` targets from each drone's yaml position, so two
drones swapped between marks fly crossing paths: that was the real mid-air collision of
2026-08-04. The trajectory shows also keep enabled drones ≥ 1 m apart (the rig rule; the
sync script warns under 1 m and refuses under 0.30 m, where marker sets merge). Planners derive their plan from the marks, so re-run the planner after every
sync.

There is one `crazyflies.yaml`, in `crazyflie/config/`: the server, every planner and the
sync script read it. A second copy in `crazyflie_shows` was removed on 2026-10-02 after
the two drifted (one had cf8, the other did not, so the planner checked one fleet and the
server flew another). `crazyflies_yaml_file:=<path>` still works for a one-off fleet, and
`show_launch.py` prints a **FLEET YAML OVERRIDE** banner when it is used. Change a show's
fleet with `enabled:` in the one file.

### `use_sim_time:=true` in the simulator, never on hardware

The sim clock (`/clock`) is only paced to wall time (`sim.realtime`, default true) and
runs flat out with `sim.realtime:=false`. A script that streams setpoints or sleeps on a
schedule without the flag drifts away from the physics, or finishes in seconds. Run
hardware without the flag. Restart the sim launch between runs.

### Set `ROS_DOMAIN_ID`: domain 0 is shared with the lab

Domain 0 is the default, and the lab network carries other people's ROS traffic: a
colleague's `/all/takeoff` has been seen here. Every terminal and the console need the
same private `ROS_DOMAIN_ID`.

### Supervisor LOCKED after an E-STOP

After an emergency stop, `/cfX/status` `supervisor_info` has bit `0x40` set and
`CAN_BE_ARMED` (`0x01`) clear, and the firmware refuses to arm. The state machine's only
transition out of locked leads back to locked (blocker `supervisorAlways`,
`supervisor_state_machine.c`), so only a battery out and in, per drone, clears it.
Verified 2026-10-02: five drones sat locked with healthy batteries (4.10-4.22 V) and the
only symptom was that nothing flew. `arm()` is fire-and-forget (`crazyflie_py` never reads
the answer), so the only proof a drone flew is its mocap altitude. Every show checks this
before its ~55 s upload (`check_supervisor` / `report_supervisor` in
`crazyflie_shows/preflight.py`). A silent `/cfX/status` counts as a note, not a refusal,
because the [telemetry stall](#link-alive-log-data-dead) looks the same.

### Ctrl-C kills the ROS context before your handler runs

`rclpy.init` (inside `Crazyswarm()`) installs a SIGINT handler that shuts the context
down. By the time `KeyboardInterrupt` reaches the script, `allcfs.land()` fails with
`failed to initialize wait set: the given context is not valid` and the drones keep
flying their last command (verified in sim 2026-09-20). Rules:

- Take SIGINT and SIGTERM (the console's Stop) back after `Crazyswarm()` returns and raise
  your own exception: `take_signals()` in `crazyflie_shows/abort.py`, which every show
  that can arm must use. It restores `SIG_DFL` for both once the abort starts, so a second
  signal of either kind kills the process, mid-landing too. The console therefore waits
  15 s after SIGINT before SIGTERM for a flight script (`procs.FLIGHT_STOP_ESCALATION`),
  and the mission window's Abort sends one SIGINT and never escalates (`procs.interrupt`).
- `ShowAborted` is a `BaseException` (since 2026-10-09). As an `Exception` it was
  swallowed by an `except Exception` around `select()` in `escort_show.operator_said()`,
  and in sim the show sat at its ARM gate after SIGINT. Never wrap a gate, select or
  publish in a bare `except Exception`.
- Set `armed = True` before the arm loop, or a signal mid-loop skips the abort and leaves
  part of the fleet armed.
- `ros2 run` does not forward a signal sent to it alone (a terminal Ctrl-C works because
  it reaches the whole process group). Test an abort with `kill -INT <the script's PID>`.

### The STL algorithm is a port

`stl_game.py` is a line-for-line port of a colleague's algorithm; do not patch its
behaviour. A new version arrives as a new file and is re-ported:
[stl/details/design-notes.md](../stl/details/design-notes.md#when-v4-arrives).

### Compiler warnings: any new one is a regression

About 25 warnings remain, all in third-party code and each reviewed: `-Wsign-compare` on
loops bounded by drone counts, `-Wreorder` with all-constant initializers, unused locals,
all in `deps/librigidbodytracker` plus one in `deps/libmotioncapture/src/optitrack.cpp`.
The ~77 a clean build once gave fell because the mocap backends this rig never uses are no
longer compiled (`motion_capture_tracking/CMakeLists.txt`). Do not add `-w` / `-Wno-*`:
this workspace patches those vendored files, and blanket suppression would hide our own
mistakes there. A new warning in `src/crazyswarm2` or `src/natnet_ros2` is a bug.

### `stop_stack.sh` stops every stack on the machine

`console/stop_stack.sh` finds processes by command line (`ros2 launch crazyflie`,
`crazyflie_server`, `motion_capture_tracking_node`, ...), not by `ROS_DOMAIN_ID`, so it
also stops a stack someone else, or another test, has up. Stop a private test stack by
its PIDs.

## Mocap

### Rigid-body orientation

A rigid body's zero orientation is captured when it is created, so the drone's nose must
lie along global +X at that moment. `locSrv.extPosStdDev = 1e-3` force-fuses the mocap
position, so a rotated body still shows ~1 mm position error: the yaw offset is invisible
at rest and a fly-away in flight. The preflight GUI's red banner and `err.yaw` catch it.
Go/no-go: within ±5° fly; 5-15° fix first; over 20° do not fly.

### Mocap "died": an orphan on UDP 1511

Confirmed cause on this rig: a leftover process bound to UDP 1511 (a stray listener, or
the last launch's mocap node, which ignores SIGINT while blocked in `recv`). With two
`SO_REUSEPORT` sockets on 1511 the kernel hands each NatNet datagram to only one, and the
mocap node starves silently inside libmotioncapture `connect()`: no crash, no publisher.
Ping to Motive proves nothing (unicast works while multicast starves). A frozen node left
behind can also make the next connect abort with SIGABRT.

### Motive's address and Local Interface

The lab Motive PC's DHCP address has moved (.100 → .124 → .152), and every move left
`/poses` silent with the node blocked in `connect()`. `hostname: "auto"` makes `launch.py`
find Motive with a NatNet discovery ping on UDP 1510 and abort with a message if nothing
answers. After the 2026-11-02 move to the big arena, Motive's Data Streaming **Local
Interface** was unset: the PC answered ping but not NatNet. It must name the wired
adapter.

### `/poses` silent with Wi-Fi and the wire both up (fixed 2026-11-23)

The driver joins the NatNet multicast group on `interface_ip`, but upstream's node never
forwarded that parameter, so the join used `0.0.0.0`, the default route's interface.
NetworkManager ranked Wi-Fi first (metric 600 against the wire's no-internet 20100), so
the join landed on Wi-Fi: Motive answered ping and discovery, and no frame arrived.
Signature: `ip maddr show dev <wifi>` lists `239.255.42.99` and the wired device does not.
Fix: vendored patch 0007 plus `interface_ip: "auto"`. Verified with Wi-Fi up: 55 Hz
`/poses`, joined on the wire.

## Radio and server

### Link alive, log data dead

**What:** one drone's `/cfX/pose`, `/cfX/status` and `/cfX/kalman_preflight` all fall to
exactly 0.00 Hz while its link is up: latency pings still complete (10-35 ms) and
`ros2 param set` still reaches it. First seen 2026-10-02, five drones on one Crazyradio
2.0; the victim changes every launch, and it recurs on the same drone.

**Cause, read in the firmware 2026-10-05** (`~/crazyflie-firmware`, tag 2025.02, what the
fleet runs): `logRunBlock()` in `src/modules/src/log.c` runs `logReset(); crtpReset();`
when `crtpIsConnected()` is false, and `radiolink.c` defines that as "received a CRTP
packet in the last 1000 ms". One second in which the drone receives nothing makes it
delete every log block and flush its CRTP queues, without telling the host. Its radio goes
on acking every poll with a 1-byte null, so every host-side counter looks healthy.

**Evidence:** at the freeze, packet tracing (`trace_cf:=all`) reads `log=0 null=~200
other=1` a second and the host agrees (`log=0 dispatched=0`): nothing leaves the drone.
The watchdog's stop/start came back `Could not start log block!`, an answer, not a
timeout: the blocks no longer existed. A second Crazyradio in another process streamed
the same drone's log at 10 Hz (hours of uptime, no reboot). A server restart always
recovered it, because connect recreates the blocks.

**Fix:** the server's telemetry watchdog (`telemetry_watchdog_s: 5.0`; design in
[server-changes.md §1](server-changes.md#1-telemetry-watchdog-detect-and-recover-from-link-alive-log-data-dead))
recreates that drone's blocks in place, only while mocap shows it on the floor
(z ≤ 0.10 m). Verified 2026-10-05: cf5 stalled twice in 20 minutes, and each time all
three topics were back ~1.0 s after the stall was declared. Manual fallback: restart the
server. A power cycle is not needed.

**Still open: what causes the ≥ 1 s receive gap.** A healthy drone here reports
`num_rx_unicast` ~168/s and `num_rx_broadcast` ~145/s, and the same firmware branch that
counts them refreshes the 1 s timer, so tripping it takes a genuine outage. One was seen
before every freeze: a ~3 s link disturbance, then a backlog flush (`log=50 null=1` in one
second); other drones survived identical bursts. The live, unmeasured candidate is the
broadcast-priority skip in `crazyflie-link-cpp/src/CrazyradioThread.cpp`: while any
broadcast connection has a queued packet or a pending retry, every unicast connection is
skipped for that pass, and `posesChanged` feeds the broadcast connection at the mocap
rate. That is upstream code: measure it before editing it. `keepalive_frequency: 4.0`
adds a 4/s unicast floor per drone; it is insurance, not a fix (a starved connection
starves the keep-alive too).

**Ruled out by measurement, do not re-chase:** telemetry rates (byte-identical to
upstream, flew for weeks); the console (open or closed made no difference); CPU and
graphics load (24 cores, load 3.6, server 2.5 %); pty back-pressure; apt overlay
shadowing; DDS config; the dongle (reproduced on the same stick); drone firmware (all
identical, rev0 2570053570); leftover log blocks (`logReset`, create and start are all
acked); the radio loop skipping connections (it services every connection each
iteration, `CrazyradioThread.cpp:195`); loss or misdelivery on the host (nothing arrives);
an inline-mode desync (it would hit every connection and raise unrequested-block
warnings). At a real stall the server still sent ~175/s and got ~167 valid acks/s, which
rules out airtime starvation and the safelink discard.

**Reading `/cfX/connection_statistics`** (`publish_stats: true`, semantics verified
2026-10-05): `sent_count` is ~175/s on a live drone; `ack_count` counts valid acks (high
means not safelink); `receive_count` also counts the drone's 1-byte nulls, so
`receive == ack` is normal and does not prove payloads; `enqueued_count` is the outgoing
queue depth, 0 when healthy, and underflows to 2^64-1 during a stall (a library bug).
`scripts/link_stall_recorder.py` dumps the 60 s before a stall for every drone.

### An upload can wedge the server (fixed 2026-10-05)

Mid-show on 2026-10-05 all five drones stopped publishing during a trajectory upload and
did not recover when the show stopped: the server was stuck. The chain, each link seen in
the log or the source:

1. The upload saturates the radio and starves the other connections:
   `[cf5] Low unicast receive rate (0.10 < 0.90). Sent: 2807. Received: 289`.
2. A starved drone crosses the firmware's 1 s timeout (above) and its `crtpReset()`
   flushes the memory-write reply the server is waiting for.
3. `Crazyflie::uploadTrajectory` waited for that reply without a bound.
4. The waiting callback sits in the fleet-wide, mutually exclusive
   [`callback_group_cf_srv`](#open-one-fleet-wide-callback-group), so every drone's
   `land`, `takeoff`, `arm`, `emergency` and the `spin_once` that dispatches all log data
   stop with it. `/all/*` still works.

Signature: `[cfX] upload_trajectory(...)` (logged on entry) with nothing after it, or the
preflight GUI's `takeoff (cfX): timed out waiting for response`. SIGINT cannot stop the
server in this state; it needs SIGKILL. The same day a show flew cf5 through four
trajectories it never received (`Sent: 1487. Received: 0`) until it was e-stopped. Fix:
bounded, identity-matched uploads, and `start_trajectory` refuses an id whose upload
failed ([server-changes.md §2](server-changes.md#2-bounded-trajectory-upload-bad_trajectories_-and-refusing-to-fly-a-failed-upload)).
Most other `waitForResponse()` calls (params, log TOC) are still unbounded: they run at
connect, but bound any of them before calling it from a service handler.

### OPEN: one fleet-wide callback group

`callback_group_cf_srv` is created once in the `CrazyflieServer` constructor and handed to
every `CrazyflieROS`. It carries every drone's `land`, `takeoff`, `arm`, `emergency`,
`go_to`, `start_trajectory` and `upload_trajectory`, the telemetry watchdog's timer, and
the 1 ms `spin_once` that is the only place log data is dispatched. rclcpp runs one
callback at a time from a mutually exclusive group, whatever the executor, so a stuck wait
on one drone stops every drone's services and all telemetry; a worst-case watchdog rebuild
is a ~14 s fleet-wide freeze. `/all/emergency`, `/all/land` and `/all/takeoff` are on
`callback_group_all_srv_` and go through the broadcaster, which never touches a stuck
drone's `Crazyflie` object, so the fleet E-STOP (console, preflight GUI's `e` key) keeps
working. The keep-alive timer is on `callback_group_cf_cmd`.

**Not changed, on purpose.** `Crazyflie::processAllPackets` and
`Crazyflie::waitForResponse` pop the same per-connection queue and the `Crazyflie` object
has no mutex, so moving only `spin_once` or only `upload_trajectory` out of the group
would make `spin_once` eat the reply a service waits for. Per-drone groups are the only
safe split, and that is a concurrency refactor of the binary that owns the radio. Measure
first: time a rebuild on the bench (five drones, props off, on the floor). If the freeze
stays ~1.0 s (as on 2026-10-05), lower `RECOVERY_TIMEOUT_MS` toward 300-500 ms instead,
for a ~4-7 s worst case at no concurrency risk. A refactor must keep the other four drones
publishing `/cfX/pose` at 10 Hz and answering `land` / `arm` while one rebuilds, and needs
a server-level recovery gate and an upload mutex (today both are accidental: the shared
group serialises recoveries, and `crazyflie_py` waits for each upload).

### Crazyradio firmware 5.1 (fixed 2026-11-17)

On 2026-11-17 the links failed one way: the drones heard the laptop (-39 to -72 dBm) but
only 2-30 % of their replies were acknowledged (40-47 % on 2026-11-06). Connecting seven
drones took 95-309 s instead of 27-29 s, and "Unexpected number of unicast packets" lines
(the drone counts each resend after a lost ack, the
server counts the packet once) rose from 7-11 a minute to 150-1,600. One
radio ran firmware 5.1, which Bitcraze has retired (5.2 fixed malformed USB replies in
5.1's inline mode, and `crazyflie-link-cpp` switches inline mode on for any Crazyradio 2.0
on 5.1 or newer); the other ran 5.4. With both on 5.5: seven drones connected in 28 s,
46 % acked, and matches flew. A 5.5 radio reports 5.04 over USB (its build says 5.4.0);
only `CURRENT.UF2` in bootloader mode tells them apart. Ruled out that day, among others:
server code and config, drone firmware, Wi-Fi, Bluetooth, the USB hub (direct ports were worse), the
console, the Starlings, the charging pods, the mocap rate. Flashing and the other levers:
[troubleshooting.md](troubleshooting.md#crazyradio--drones).

### OPEN: `/poses` arrives late between processes on the laptop (2026-11-17)

On 2026-11-17 the mocap node published an even 50 Hz, but other processes on the same
laptop received it with gaps (a bag recorder: up to 1.6 s, 41.7 Hz on average), and every
new ROS process took 12-23 s to start talking (1.8 s on 11-06; one guard show hung over
12 minutes before its first line). A take-off aborted itself 4 s after lifting because
the show's own copy of `/poses` was stale while the recorder was receiving. The likely
cause, not proved: 57 abandoned Fast DDS shared-memory files in `/dev/shm`, left by
processes killed with SIGKILL; every run that day also followed a suspend and resume. Remedy to try: reboot,
or stop the stack and the console, `fastdds shm clean`, `ros2 daemon stop`, restart.

### A second Crazyradio is the best probe

With the server holding one dongle, a second lets another process talk to the same drone.
The link library skips any radio whose serial it cannot query (`USBManager.cpp:188-207`),
so to other processes the free stick is `devId 0`: address it as
`radio://0/80/2M/E7E7E7E70X`, not `radio://1/...` (e.g.
`ros2 run crazyflie log --uri ... --var kalman.stateX`). Two dongles on one channel collide
briefly: fine for a read-only probe, not for flight.

### Two dongles: channels at least 2 apart at 2M

A 2M channel is ~2 MHz wide, so crazyflie-link-cpp refuses two dongles on adjacent
channels (`Channels 80 and 81 are already served by Crazyradio 0`). The comments in
`crazyflies.yaml` record the channels in use.

### Two logging traps

1. `[cfX] Logging to /pose at N Hz` is printed on intent, before the block exists: a
   block that never delivers leaves no trace.
2. The link warnings (`Low unicast receive rate`, `High latency`) fire only while a rate
   is bad, so silence is not health. A "when did each drone die" timeline built from the
   last warning per drone produced a convincing and false pattern on 2026-10-02. Measure
   the topics directly, all drones at once: a sequential `ros2 topic hz` misses a drone
   that drops while you sample another.

## ROS 2, build and tools

### A node never hears its own `/parameter_events`

On this rig a node's own `/parameter_events` are never delivered back to itself (other
processes' arrive). So upstream's `ParameterEventHandler` never fired and
`ros2 param set` silently never reached the drones; the server applies `<cf>.params.*` /
`all.params.*` in an `add_on_set_parameters_callback` instead, inside the service call.
Fresh rclpy processes also see DDS discovery sometimes never complete: parameter calls
time out and `Crazyswarm()` can hang on `all/emergency`. Hence `scripts/led.sh` drives the
`ros2` CLI (its daemon keeps the graph warm) and `color_led.py` calls `set_parameters`
directly. It is also why `trace_cf` is read only at connect.

### `declare_parameter(name, {})` is a trap

A bare `{}` matches both the `(name, default_value)` and the `(name, ParameterDescriptor)`
overloads; gcc picks the descriptor, so the parameter has no default and rclcpp throws
`NoParameterOverrideProvided` at runtime. The compile-time hint is only "would use
explicit constructor". Spell the default out (`std::vector<std::string>{}`). Fixed in
`natnet_ros2.cpp`.

### Console blind after a Wi-Fi switch

The mission console runs every check through the `ros2` CLI daemon it starts, and its
fleet journal is a long-running `ros2 topic echo /rosout`. Both join DDS on the network
the laptop had when the console started. After a Wi-Fi switch (2026-11-05, hangar →
`motive`) both went deaf while RViz, the preflight GUI and the drones, all started later,
worked: health said "crazyflie_server not running" during a real flight. Reproduced with
`scripts/offline_window.sh console_network`: the old daemon's `ros2 node list` was empty
while `--no-daemon` saw the server, and the journal heard 0 of 2 `land` commands.
`ros2 daemon stop` fixes health but not the journal (a separate process). The mission
window's 3D view is not affected (the browser talks to foxglove_bridge directly).

### Environment traps (closed)

- **`set -u` vs ROS `setup.bash`:** sourcing it under `set -u` aborts on the unbound
  `AMENT_TRACE_SETUP_FILES`, so the build never ran and `install/` stayed empty.
  `build.sh` wraps the source in `set +u` / `set -u`.
- **conda:** ROS 2 runs nodes with `/usr/bin/python3`. With conda active, rosidl built the
  message bindings for the wrong Python (a `cpython-312` `.so` on a 3.10 box), and every
  `ros2 topic echo` of a workspace message died with
  `The message type '.../NamedPoseArray' is invalid`. `build.sh` now strips conda/venv
  and passes `-DPython3_EXECUTABLE=/usr/bin/python3`; at runtime, deactivate conda
  yourself.
- **cffirmware (simulator only):** not a pip package; `setup_sim_firmware.sh` builds it
  from `crazyflie-firmware` tag 2025.02. Its CMSIS submodule needs `git-lfs`, and the
  `setup.py` egg leaves out the compiled `_cffirmware*.so`, so the script puts
  `crazyflie-firmware/build` on `PYTHONPATH`.
- **Sim `plan_start_trajectory` arity:** the binding built here takes 5 arguments
  (`p, trajectory, reversed, relative, start_from`, verified 2026-09-17), and calling it
  with 7 killed the sim server at the first `startTrajectory`. `crazyflie_sil.py` picks
  the call by `inspect.signature` arity; never hard-code either.
- **NatNet SDK not committed:** `install_sdk.sh` downloads it with `wget` on the first
  `natnet_ros2` build, so a fresh clone needs internet once, which the rig network lacks.
- **ROS apt 404s:** upgrading `ros-<distro>-{sensor-msgs,tf2-ros,ament-cmake-auto}` can
  404 on a pruned pool version; `install_deps.sh` installs them with `--no-upgrade`.
- **Preflight GUI on 22.04:** pip `cfclient` pulls PyQt6 ≥ 6.5, whose xcb plugin needs
  `libxcb-cursor0`; without it the node dies with
  `Could not load the Qt platform plugin xcb`. `install_deps.sh` installs it.

### LED convention

Green: drone connected and ready for command. Red: a script is controlling the drones.
The server turns the Color LED deck green on connect and off on a clean disconnect; every
`crazyflie_py` script sets it red for its lifetime and restores green on exit
(`crazyswarm_py.py`, `atexit`, which survives exceptions and Ctrl-C; if rclpy is already
shut down, or after a hard link loss, the deck keeps its last colour). Set colours by hand
with `scripts/led.sh` or `ros2 run crazyflie_examples color_led`.

---

Full earlier text: `git show 678bac1:docs/rig/known-issues.md` (and the 2026-11-17 session
report: `git show 678bac1:docs/rig/radio-link-2026-11-17.md`).
