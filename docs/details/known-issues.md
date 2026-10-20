# Known issues: the hard-won record

Every silent failure this rig has hit, with the evidence and the fix. Read the
entry before re-investigating anything here: most of these took days to find.
The short symptom → fix tables are in [troubleshooting.md](troubleshooting.md).
"server" below is `src/crazyswarm2/crazyflie/src/crazyflie_server.cpp`; what was changed
in it, and why, is in [server-changes.md](server-changes.md).

- **`set -u` vs ROS `setup.bash`.** Sourcing `/opt/ros/<distro>/setup.bash` under
  `set -u` aborts on the unbound `AMENT_TRACE_SETUP_FILES`. `build.sh` wraps the
  source in `set +u`/`set -u`. Without it the build silently never runs → empty
  `install/`.
- **cffirmware (simulator only).** `crazyflie_sim` imports `cffirmware` (Crazyflie
  firmware Python bindings) — not a pip package. `setup_sim_firmware.sh` builds it
  from `crazyflie-firmware` (tag 2025.02). NOT needed for hardware backends.
  - Its **CMSIS submodule needs `git-lfs`** or the checkout aborts (`arm_add_f32.c`
    missing). The script installs git-lfs.
  - The `setup.py` egg does **not** bundle the compiled `_cffirmware*.so`; expose
    `crazyflie-firmware/build` on `PYTHONPATH` instead (script appends to `~/.bashrc`).
- **conda shadows system Python.** ROS 2 runs nodes with `/usr/bin/python3`. A conda
  base env (different Python) causes `No module named '_cffirmware'` and rclpy errors.
  Deactivate conda for ROS work. `build.sh` now defends the BUILD only: if
  `CONDA_PREFIX`/`VIRTUAL_ENV` is set or `python3` isn't `/usr/bin/python3` it strips
  conda/venv from `PATH`+`PYTHONPATH` and passes `-DPython3_EXECUTABLE=/usr/bin/python3`.
  Without that, rosidl generated the Python message bindings for the wrong interpreter
  (`cpython-312` .so on a 22.04 box whose `ros2` runs 3.10) — C++ nodes fine, but every
  `ros2 topic echo` of a workspace message died with
  `The message type '.../NamedPoseArray' is invalid`. RUNTIME is still undefended:
  deactivate conda before `ros2 launch`.
- **Preflight GUI needs `libxcb-cursor0` on 22.04/jammy.** pip `cfclient` pulls
  PyQt6 >= 6.5, whose xcb platform plugin needs it; jammy doesn't install it by
  default, so the preflight node dies at start with
  `Could not load the Qt platform plugin xcb`. `install_deps.sh` installs it
  (plus `python3-tk`).
- **Compiler warnings: first-party code must stay clean; ~25 remain, all
  third-party and reviewed.** A clean build used to emit ~77 warnings. Most came
  from mocap backends this rig never uses, so they are no longer compiled at all
  (see `motion_capture_tracking/CMakeLists.txt`) — that removed an overlapping-buffer
  `sprintf` in the Qualisys SDK, strict-aliasing type-punning, and a truncating
  `strncpy` in VRPN, none of it reachable with `type: "optitrack"`. The ~25 left are
  ALL in `deps/librigidbodytracker` (+1 in `deps/libmotioncapture/src/optitrack.cpp`)
  and were each checked: `-Wsign-compare` on loops bounded by drone counts,
  `-Wreorder` whose initializers are all constants (so declaration-order init is
  identical), and unused locals. **Benign — do not mass-patch upstream to silence
  them, and do NOT add `-w`/`-Wno-*` to those targets**: this workspace patches
  vendored deps (e.g. the NatNet timeout in `optitrack.cpp`), so blanket suppression
  would hide OUR future mistakes in exactly the files we edit. Any NEW warning in
  `src/natnet_ros2` or `src/crazyswarm2` is a real regression — fix it.
- **`declare_parameter(name, {})` is a trap.** A bare `{}` is ambiguous between the
  `(name, default_value, …)` and `(name, ParameterDescriptor, …)` overloads; gcc
  picks the descriptor one, declaring the parameter with NO default so rclcpp throws
  `NoParameterOverrideProvided` at runtime instead of using the empty default. It
  warns at compile time but only as "would use explicit constructor". Always spell
  the default out (`std::vector<std::string>{}`). Fixed in `natnet_ros2.cpp`.
- **RViz and the preflight GUI are ON by default** in `launch.py`
  (`rviz:=false` / `preflight:=False` to disable). `foxglove:=True` by default
  but needs `ros-$ROS_DISTRO-foxglove-bridge` (installed by `install_deps.sh`);
  view via the Foxglove Studio app, not a window.
- **Mocap "died" / `/poses` 0 publishers** — CONFIRMED cause on this rig: a
  leftover process bound to UDP 1511. Two `SO_REUSEPORT` sockets on 1511 → the
  kernel gives each NatNet datagram to only ONE socket → the mocap node starves
  and hangs silently in libmotioncapture `connect()` (no crash, not in
  `ros2 node list`). Diagnose `ss -uanp | grep :1511`; kill the orphan and
  relaunch. Ping to the Motive PC proves nothing (unicast ≠ multicast).
- **Motive address:** `motion_capture.yaml` `hostname: "auto"` → `launch.py`
  discovers the Motive PC via a NatNet ping broadcast on UDP 1510 (lab DHCP
  drifts: .100 → .124 → .152). Override: `mocap_hostname:=<ip>` launch arg or
  `CRAZYSWARM_MOCAP_HOST`. Must be an IPv4 literal; the launch aborts loudly if
  nothing answers instead of the node hanging silently.
- **Motive transmission type is read once at connect** (the vendored
  `motion_capture_tracking` requires Multicast or Broadcast Frame Data; never
  install the apt package — 1.0.9 hard-codes a foreign interface IP) — after changing it, fully
  restart the launch. A frozen mocap node ignores SIGINT (blocked in `recv`);
  launch escalates to SIGKILL — check `pgrep -f motion_capture_tracking` for
  leftovers (they make the next connect SIGABRT).
- **Rigid-body orientation.** Create the Motive rigid body with the drone's
  forward axis on global +X. `locSrv.extPosStdDev=1e-3` force-fuses mocap
  position, so position error is ~1 mm even with a rotated body — a yaw offset
  is invisible at rest and a fly-away in flight. The preflight GUI's banner /
  `err.yaw` catches it (±5° fly; 5–15° fix; >20° no fly).
- **ROS apt 404 churn.** `ros-<distro>-{sensor-msgs,tf2-ros,ament-cmake-auto}` can
  404 when apt tries to *upgrade* to a pruned pool version. `install_deps.sh` uses
  `--no-upgrade` for these (desktop already provides them).
- **natnet NatNet SDK is NOT committed.** `src/natnet_ros2/.gitignore` excludes
  `deps/NatNetSDK/*`; CMake runs `install_sdk.sh`, which downloads it with `wget`
  (x86_64 or ARM) on the first build. A fresh clone therefore needs internet once,
  and the rig network has none: build on another network first, or copy the folder.
- **Same-process DDS loopback failure.** On this rig a node's OWN
  `/parameter_events` messages are never delivered back to itself (events from
  *other* processes arrive fine). Three consequences: (1) runtime firmware-param
  pushes in `crazyflie_server.cpp` use `add_on_set_parameters_callback`
  (synchronous, inside the `set_parameters` service call — no pub/sub
  round-trip) instead of upstream's ParameterEventHandler, which never fired,
  so `ros2 param set` silently never reached the drones; (2) `scripts/led.sh`
  deliberately drives the `ros2` CLI (its long-running daemon keeps the ROS
  graph warm) instead of rclpy — fresh rclpy processes see DDS discovery never
  complete and parameter service calls time out; (3) `Crazyswarm()` in a fresh
  rclpy process can hang waiting on `all/emergency` for the same reason
  (`color_led.py` avoids Crazyswarm() and calls `set_parameters` directly).
- **Ctrl-C kills the ROS context BEFORE your handler runs — so "land on abort"
  silently does nothing.** `rclpy.init` (inside `Crazyswarm()`) installs its own
  SIGINT handler that shuts the context down; by the time `KeyboardInterrupt`
  reaches the script, `allcfs.land()` dies with `failed to initialize wait set:
  the given context is not valid` — at exactly the moment it is needed, leaving
  the drones flying their last command. Verified failing in sim 2026-09-20.
  Fix: after `Crazyswarm()` returns, take the signal back with
  `signal.signal(signal.SIGINT, ...)` (and SIGTERM, which the console's Stop
  sends) and raise your own exception — `take_signals()` in
  **`crazyflie_shows/abort.py`**, which every show that can arm must use.
  Restore `SIG_DFL` for **both** signals once
  the abort starts, so a second Ctrl-C can still kill the process. That also
  means ANY second signal kills it mid-landing — this entry used to say the
  restore stops the console's SIGTERM escalation from interrupting a slow
  landing; it does the opposite (`SIG_DFL` SIGTERM terminates). So the console
  now waits **15 s** after SIGINT before SIGTERM for a flight script
  (`procs.FLIGHT_STOP_ESCALATION`), and the mission window's Abort sends ONE
  SIGINT and never escalates (`procs.interrupt`). **`ShowAborted` is a
  `BaseException`** (since 2026-10-09): as an `Exception` it was swallowed by
  `escort_show.operator_said()`'s `except Exception` around `select()`, so a
  Ctrl-C at a paced gate did NOTHING — measured in sim, the show sat at its ARM
  gate after SIGINT. Never wrap a select/publish in a bare `except Exception`
  that could catch it either. Set `armed = True` **before** the arm loop, not after, or a
  signal mid-loop skips the abort and leaves part of the fleet armed. Note `ros2 run` does
  NOT forward a signal sent to it alone; a terminal Ctrl-C reaches the child
  because it goes to the whole foreground process group, so test an abort with
  `kill -INT <the script's own PID>`, not the wrapper's.
- **"Link alive, log data dead": a drone stops publishing ALL telemetry while
  still answering.** Seen repeatedly 2026-10-02, five drones on one Crazyradio
  2.0. `/cfX/pose`, `/cfX/status` AND `/cfX/kalman_preflight` all read **exactly
  0.00 Hz** (not degraded) for one or more drones, picked at random per session
  and frozen for it; the victim set changes every launch. The link is NOT down:
  the server keeps completing latency ping round trips (`on_latency`, 10-35 ms,
  ~0.84/s) and `ros2 param set` still reaches the drone (an LED write works).
  The DRONE is not at fault either: a second Crazyradio in a separate process
  connects and streams its log at 10 Hz, with hours of drone uptime (no reboot).
  **Recovery is now automatic** -- the telemetry watchdog below recreates that
  one drone's log blocks in place. The manual fallback is to restart the server
  (its connect sequence does `logReset()` and recreates the blocks).
  Power-cycling drones is NOT needed -- that is the supervisor-LOCKED case
  below, a different failure.
  Diagnose with `warnings.communication.publish_stats: true` (already on) ->
  `/cfX/connection_statistics`, plus `scripts/link_stall_recorder.py`, which
  dumps the 60 s precursor for EVERY drone the moment one stalls.
  **Counter semantics (verified 2026-10-05, an earlier note here was wrong):**
  `sent_count` ~175/s on a live drone; `ack_count` counts VALID acks (the
  safelink discard invalidates the ack first, so a high ack_count RULES OUT
  safelink); `receive_count` counts acks pushed to the app queue but ALSO the
  drone's 1-byte "nothing to send" nulls, because the null filter is commented
  out, so `receive == ack` is normal and is NOT proof of payloads; and
  `enqueued_count` is the OUTGOING queue depth, a gauge (0 is healthy, and it
  underflows to 2^64-1 during a stall -- a library accounting bug).
  **MEASURED at a real stall (cf5, 2026-10-05):**
  while cf5 published nothing, the server was still sending ~175/s and getting
  ~167 valid acks/s. So the drone answers every poll and has nothing to send, on
  that link only -- which rules out airtime starvation AND the safelink discard.
  **Ruled out by measurement, do not re-chase:** telemetry rates (ours are
  byte-identical to upstream AI-DA-STC and flew for weeks); the console
  (dashboard open vs closed changed nothing -- 12 connections and continuous
  probing, all five drones still 10.0 Hz; argv, env values, cgroup and limits
  identical to a shell launch); CPU/graphics load (24 cores, load 3.6, server
  2.5%); pty back-pressure (nothing ever blocked in a tty write); apt overlay
  shadowing; DDS config; the dongle (reproduced on the same stick); drone
  firmware (all five identical, rev0 2570053570); leftover log blocks
  (`logReset`, create and `start` are all acked); and the radio loop skipping
  connections (it services every connection every iteration,
  `CrazyradioThread.cpp:195`).
  **LOCALISED 2026-10-05 by packet tracing (`trace_cf:=all`).** At the freeze the
  link trace reads `log=0 null=~200 other=1` and the host trace agrees
  (`log=0 dispatched=0`): **zero log packets ever leave the drone on that
  connection** -- it answers every poll with a 1-byte "nothing to send" null.
  So nothing is dropped, misdispatched or failing validation host-side; there is
  nothing arriving to drop. That kills the two host-side explanations outright
  (lost before dispatch, and misdelivery to another connection) and leaves the
  drone's per-link log production. The inline-mode desync theory is NOT
  supported: it would affect every connection and raise unrequested-block
  warnings, and neither happens.
  Context, not cause: freezes follow a ~3 s link disturbance and a backlog flush
  (`log=50 null=1` in one second), but other drones survive identical saturated
  bursts (cf1 took `log=34 null=0` and stayed healthy), so the flush alone is
  not sufficient.
  **ROOT CAUSE, FOUND IN THE FIRMWARE 2026-10-05 -- the drone deletes its own
  log blocks when it thinks WE went away.** `logRunBlock()` in the firmware's
  `src/modules/src/log.c` ends with

      // Check if the connection is still up, oherwise disable
      // all the logging and flush all the CRTP queues.
      if (!crtpIsConnected()) { logReset(); crtpReset(); }

  and `crtpIsConnected()` -> `radiolinkIsConnected()` in `src/hal/src/radiolink.c`
  is just `(xTaskGetTickCount() - lastPacketTick) < M2T(1000)`, where
  `lastPacketTick` is refreshed ONLY when the DRONE RECEIVES a CRTP packet
  (`SYSLINK_RADIO_RAW`/`_BROADCAST` in `radiolinkSyslinkDispatch`). So **one
  second without receiving anything makes a drone delete every log block and
  flush its CRTP queues** -- and it never tells the host. The nRF51 goes on
  acking polls at the radio level, so every host-side counter stays perfect.
  That is the entire syndrome. It also promotes the "~3 s link disturbance
  before each freeze" from context to CAUSE: the drone's receive gap crossed
  1000 ms. The firmware source is on this box (`~/crazyflie-firmware`, tag
  2025.02, same version the fleet runs) -- read it before theorising about the
  radio again.
  **What the trigger therefore IS, and is not** (measured 2026-10-05, correcting
  a first guess that the 1 Hz warning ping sat on the threshold): a healthy
  drone on this rig reports `/cfX/status` `num_rx_unicast` ~168/s and
  `num_rx_broadcast` ~145/s, and `count_rx_unicast` is incremented in the SAME
  `radiolinkSyslinkDispatch` branch that refreshes `lastPacketTick` -- so the
  timer is refreshed ~170 times a second by the link library's own auto-pings.
  The margin is not thin. Tripping it takes a GENUINE >= 1 s window in which
  that one drone receives nothing at all, which is exactly the "~3 s link
  disturbance" seen before every freeze. **What causes that outage is the one
  thing still open.** `server.yaml` `keepalive_frequency: 4.0` adds a guaranteed
  per-drone unicast floor (4/s on top of ~170/s): cheap insurance if auto-ping
  behaviour ever changes, NOT a fix -- a starved connection starves the
  keep-alive too, since both go through the same radio thread. Its timer runs on
  `callback_group_cf_cmd`, not the mutually-exclusive `callback_group_cf_srv`
  where the watchdog's rebuild runs, so a rebuild cannot silence it.
  **So the recovery, not the prevention, is what makes the rig usable.**
  **How it was measured, before the firmware was read: the drone DROPS its log
  blocks.** The
  watchdog's first remedy was a stop/start of the existing blocks; at a real cf5
  stall that came back as `Could not start log block!` -- a response, not a
  timeout, so the drone answered the control request and REFUSED it. A block
  cannot be started if it no longer exists on the aircraft. That single result
  explains the whole syndrome: no block -> nothing to send -> every poll
  answered with a null -> a link that measures perfectly healthy. It also
  explains why only a server restart ever recovered it (its connect sequence
  re-CREATES the blocks) and why a second dongle always worked (a fresh
  connection creates its own). What makes the drone drop them is still open --
  it is the firmware's own 1 s radio-activity timeout, above.
  **FIX IN PLACE -- the telemetry watchdog** (`server.yaml`
  `telemetry_watchdog_s: 5.0`, `check_telemetry_watchdog()` in
  `crazyflie_server.cpp`): when a drone delivers no log data for that long while
  its latency echo is still current (< 2 s), the server recovers that one drone
  in two tiers -- **tier 1** `restart_log_blocks()` (stop/start, cheap, works if
  the blocks still exist), and when that throws, **tier 2**
  `rebuild_log_blocks()`: destroy the block objects, `logReset()`, then create
  and start them all again, which is the logging half of a server restart
  without the restart. Tier 2 is why every block is now registered through
  `add_log_builder()` at connect instead of just being constructed -- the
  builder closure is the only record of how to make that block again.
  **VERIFIED ON HARDWARE 2026-10-05:** cf5 stalled twice in one 20-minute run;
  each time tier 1 was refused, tier 2 recreated the blocks, and `/cf5/pose`,
  `/cf5/status` and `/cf5/kalman_preflight` were all back **~1.0 s** after the
  stall was declared -- no server restart, no power cycle. Note the stall
  RECURS on the same drone, so the watchdog treats it as an ongoing condition,
  not a one-off. Every wait on the recovery path is **bounded**
  (`RECOVERY_TIMEOUT_MS` = **1000 ms x 2** per request -- an earlier version of
  this note said 300 ms, which the code raised after a real start answered
  later than that; it bails out entirely if `logReset` goes unanswered) because
  the link timer shares a mutually-exclusive callback group with `land` and
  `emergency` -- an unbounded wait there would be worse than the stall. **That
  group is FLEET-WIDE, not per drone** (created once in the `CrazyflieServer`
  constructor and handed to every `CrazyflieROS`), and it also carries the 1 ms
  `spin_once` that is the only place log data is dispatched -- so a stuck wait
  costs ALL drones' per-drone services and ALL telemetry. See the open item
  below. The connect path still waits unbounded, deliberately, unchanged.
  **THREE CORRECTNESS FIXES 2026-10-06, found by reading the firmware rather
  than the host:**
  (1) **tier 1's `start()` was still unbounded.** Blocks built at connect carry
  `m_timeout_ms = 0`, and the one-arg `start()` forwards it, so tier 1 ran the
  unbounded wait -- the trap `627ab55` closed for uploads, left open one
  function away. `stop()` was already bounded; only `start()` was missed. There
  is now a two-arg `start(period, timeout_ms)` with **no default argument**,
  and tier 1 passes the bound. Do not give it a default or collapse the
  forwarder: bounding CONNECT would make one busy link kill all five drones'
  launch, because a throw out of a log-block builder is not caught at the
  `CrazyflieROS` construction site.
  (2) **a log-control answer could satisfy the wrong wait.**
  `crtpLogControlResponse::valid()` tests only port 5 / channel 1 / 3-byte
  payload, which EVERY log-control reply satisfies -- and tier 1 is literally
  `stop(); start(p);`, so a late stop answer was read as "start succeeded".
  Tier 1 then "worked", logged `log blocks restarted`, and the watchdog never
  escalated to the tier 2 that actually fixes it. Waits now match on the
  command byte and the block id, which works because the firmware answers by
  REUSING the request packet (`log.c` `logControlProcess` overwrites only
  `data[2]` and `size`). **`logReset` is matched on the command ONLY** --
  `crtpLogResetRequest` is `Packet(5,1,1)`, so `data[1]` of a reset reply is
  indeterminate and matching an id there would reject the drone's own answer.
  (3) **the rebuild destroyed our own log blocks BEFORE probing the drone.** An
  unanswered `logReset` left that drone with zero host-side blocks while the
  aircraft may still have held live ones. The probe now comes first, so a
  failed probe is a no-op.
  It **refuses to act unless the drone may not be airborne**: mocap must
  positively show it on the floor (`z <= 0.10 m`), unknown altitude counts as
  airborne, AND `commanded_flight_` must be clear. That flag was dead code
  until 2026-10-06 -- declared false, set false, read once, **never set true**
  -- so the gate was the mocap test alone despite a comment implying more. It
  is now set by every handler that can put a drone in the air, the `/all/*`
  broadcasts included, and cleared by mocap. The gate is also re-checked
  between builders, because it used to be evaluated once while the bounded
  worst case to the last builder is several seconds. Set `telemetry_watchdog_s`
  to 0 to disable.
  **Packet tracing** (`ros2 launch crazyflie launch.py trace_cf:=all`, or a
  comma-separated subset) prints ONE summary per second per drone from the link
  layer and from `processPacket`, plus per-packet lines only for anomalies. It
  is a launch argument, NOT `--ros-args` (`ros2 launch` has no such flag), and
  is read at connect because this rig's `/parameter_events` never loop back.
- **An UPLOAD can wedge the server permanently -- the worst failure on this
  rig, and the watchdog above cannot save you from it.** Seen 2026-10-05
  mid-show: all five drones stopped publishing telemetry during the trajectory
  upload and **did not recover when the show was stopped**, because the server
  itself was stuck, not the drones. The chain, each link verified in the log or
  the source:
  1. The upload saturates the radio and starves the other connections --
     measured `[cf5] Low unicast receive rate (0.10 < 0.90). Sent: 2807.
     Received: 289`, i.e. the drone got 10% of what was sent to it.
  2. A starved drone crosses the firmware's 1 s radio-activity timeout and runs
     `logReset(); crtpReset();` (see the stall entry above). **`crtpReset()`
     flushes its CRTP queues -- including the memory-write response the server
     is at that moment waiting for.**
  3. `Crazyflie::uploadTrajectory` waited for that response with an UNBOUNDED
     `waitForResponse`, so the service callback never returned.
  4. `callback_group_cf_srv` is **mutually exclusive** and carries that drone's
     `land`, `takeoff`, `arm`, `emergency` and `spin_once` AND the telemetry
     watchdog's timer. One stuck upload therefore disables all of them for that
     drone, for good. `[cfX] upload_trajectory(...)` is logged on ENTRY, so a
     line with nothing after it is the signature. The preflight GUI showing
     `takeoff (cfX): timed out waiting for response` is the same wedge.
  SIGINT will not stop a server in this state (its threads are blocked); it
  needs SIGKILL, and `ros2 launch` leaves the node behind.
  **FIXED**: the memory-write wait is now bounded (500 ms x 2, the chunk resent
  up to 3 times) and `uploadTrajectory` throws if it still gets nothing. The
  server catches that, logs FATAL, and records the id in `bad_trajectories_` --
  **`start_trajectory` then REFUSES that id** until it uploads cleanly, because
  the caller otherwise flies a partially written trajectory. Do not "simplify"
  that refusal away. (`UploadTrajectory.srv` DOES carry `success`/`message` and
  `crazyflie_py` raises on it -- an earlier note here and a comment in the
  server both said otherwise. `StartTrajectory.srv` is the one with no response
  fields, which is why `bad_trajectories_` still matters on the broadcast path.
  That set is now mutex-guarded: it is written on `callback_group_cf_srv` and
  read from the broadcast handler on `callback_group_all_srv_`, and a
  concurrent read/write of a `std::set` is UB.)
  **ALSO FIXED 2026-10-06 -- the reply was matched by SHAPE, not identity.**
  `crtpMemoryWriteResponse::valid()` checks only port 4 / channel 2 / 6-byte
  payload, so the chunk RESEND that `627ab55` introduced could leave the host
  one reply out of phase for the rest of the upload, and a chunk whose request
  was then lost counted as written -- `success = true` for a trajectory with a
  24-byte hole. `sizeof(poly4d)` is 132 and 132 % 24 != 0, so the hole lands
  mid coefficient array and the drone flies a hybrid of two polynomials;
  `piecewise_eval` applies whatever bytes are there with **no validation, no
  clamp and no finiteness check**, and the supervisor only reacts to TUMBLED
  and battery. The wait now matches the memory id and the 32-bit address
  (the firmware echoes both -- `crtp_mem.c` `memWriteProcess`, whose own
  comment reads *"Dont' touch the first 5 bytes, they will be the same."*), and
  a non-zero status THROWS instead of being logged, because it can only mean
  `(offset + length) <= sizeof(trajectories_memory)` failed -- deterministic,
  so not retried. Tightening the predicate removed an accidental latency
  absorber, so a stale reply now counts as proof the drone is alive-but-
  backlogged and buys more time, under a 10 s per-chunk and 90 s per-call cap.
  **Still unbounded, same trap:** most other `waitForResponse()` calls in
  `crazyflie_cpp` (params, log TOC). They run at connect, where blocking is the
  documented behaviour, but any of them reached while the rig is saturated can
  wedge a drone's services the same way. Bound them before calling them from a
  service handler.
- **`requestMemoryToc` ALREADY matches ids -- do not "fix" it.** An audit
  reported that it consumes GetInfo replies positionally with no id check, so a
  late reply would shift every later entry and a trajectory write could go to
  the wrong memory. **That reading is inverted**, and the mistake is easy to
  repeat: `Crazyflie.cpp:19` is an unconditional `#define FIRMWARE_BUGGY` with
  no `#undef` anywhere, so the `#ifndef FIRMWARE_BUGGY` branch -- the one that
  would consume positionally -- is **preprocessed away**. The compiled function
  is a single send-wait ping-pong whose LIVE branch is
  `if (res::id(p) != i) { warn; --i; }`; the `assert` is the dead `#else`. The
  drone cannot reorder these anyway: `memTask` is one FreeRTOS task draining
  one FIFO and replying synchronously with a blocking send, and it echoes the
  requested id. Two further traps if you do edit it: dropping the `--i` removes
  the only absorber for a duplicated request, and
  `m_memoryTocEntries[res::id(p)]` would be an unbounded indexed write driven
  by a byte the drone chose, into a vector sized from an earlier packet --
  heap corruption in the process that owns the only radio. The ping-pong also
  has a firmware reason: `crtpRxTask` blocks **forever** on a full port queue
  ("we should never drop a packet"), so keeping one GetInfo outstanding keeps
  at most one MEM packet in that 16-deep queue.
- **OPEN: `callback_group_cf_srv` is ONE fleet-wide mutually-exclusive group.**
  Created once in the `CrazyflieServer` constructor and handed to every
  `CrazyflieROS`, it carries each drone's `land`/`takeoff`/`arm`/`emergency`/
  `go_to`/`start_trajectory`/`upload_trajectory`, the telemetry watchdog timer,
  AND the 1 ms `spin_once` that is the only place log data is dispatched. A
  `MultiThreadedExecutor` does not help: rclcpp runs one callback at a time from
  a mutually-exclusive group. So a stuck wait on ONE drone costs all five
  drones' per-drone services and ALL telemetry -- which explains the measured
  2026-10-05 "all five stopped publishing during the upload" with no firmware
  involvement needed. Worst-case tier-2 rebuild is a ~14 s fleet-wide freeze.
  **Not changed, deliberately**: per-drone groups are the only safe
  granularity, and that is a concurrency refactor of the binary that owns the
  radio. `Crazyflie::processAllPackets` and `Crazyflie::waitForResponse` pop the
  **same per-connection receive queue** and match replies by shape, and the
  `Crazyflie` object has no mutex -- so splitting only `spin_once`, or only
  `upload_trajectory`, out of the group makes `spin_once` eat the reply a
  service is blocked on. **Measure before refactoring:** time
  `restart_log_blocks()`/`rebuild_log_blocks()` on the bench with five drones,
  props off, on the floor. If the freeze stays ~1.0 s (as measured 2026-10-05),
  take the cheap fix instead -- lower `RECOVERY_TIMEOUT_MS` toward 300-500,
  which shrinks the worst case to ~4-7 s at zero concurrency risk. If it goes
  ahead, the acceptance criterion is that **while one drone rebuilds, the other
  four keep publishing `/cfX/pose` at 10.0 Hz and their `land`/`arm` still
  answer**; and it needs a server-level recovery gate (the shared group is
  currently a de-facto "one recovery at a time" lock) plus an upload mutex
  (today's sequencing is accidental -- `crazyflie_py` happens to spin until each
  upload future completes).
  **Mitigating, and verified:** `/all/emergency`, `/all/land` and `/all/takeoff`
  are on `callback_group_all_srv_` and go through `broadcaster_`, which never
  touches a stuck drone's `Crazyflie` object -- so the fleet e-stop, the
  console's E-STOP and the preflight GUI's `e` key keep working through all of
  this. That is why these are "high", not "critical".
- **STILL OPEN: what causes the >= 1 s receive gap in the first place.** The
  firmware's reaction is fully explained (`radiolink.c` -> `log.c`
  `logReset(); crtpReset();`) and a healthy drone here sees ~168 unicast rx/s,
  so tripping it takes a genuine outage. The live candidate, UNMEASURED, is the
  broadcast-priority skip in `crazyflie-link-cpp/src/CrazyradioThread.cpp`: if
  ANY broadcast connection has a queued packet or a pending retry, every
  non-broadcast connection is `continue`d for the whole pass -- and
  `posesChanged` feeds the broadcast connection continuously at the 50 Hz mocap
  rate. That is upstream code; it deserves its own measurement, not a drive-by
  edit.
- **A second Crazyradio is the best diagnostic probe on this rig.** With the
  server holding one dongle, a second one lets another process talk to the same
  drone: the link library **skips any radio whose serial it cannot query**
  (`USBManager.cpp:188-207`), so the server's claimed stick is invisible to
  other processes and the free one is `devId 0` to them -- address it as
  `radio://0/80/2M/E7E7E7E70X`, not `radio://1/...`. That is how the drone was
  exonerated above (`ros2 run crazyflie log --uri ... --var kalman.stateX`).
  Both dongles on one channel do collide briefly: fine for a read-only probe,
  not for flight.
- **Two logging traps that waste hours.** (1) `"[cfX] Logging to /pose at N Hz"`
  is printed on INTENT, before the block is created -- a block that never
  delivers leaves no trace. (2) The link warnings (`Low unicast receive rate`,
  `High latency`) only fire while a rate is BAD, so **absence of warnings is not
  evidence of health**; a "when did each drone die" timeline built from the last
  warning per drone is an artifact (it produced a convincing but entirely false
  reverse-connection-order pattern on 2026-10-02). Measure topics directly, all
  drones simultaneously -- sequential `ros2 topic hz` misses a drone that drops
  while you are sampling another.
- **Supervisor LOCKED latches after an e-stop; only a power cycle clears it.**
  `/cfX/status` `supervisor_info` with bit `0x40` set and `CAN_BE_ARMED` (0x01)
  clear means the firmware will refuse to arm, and the state machine has exactly
  one transition out of locked -- back to locked, blocker `supervisorAlways`
  (`supervisor_state_machine.c`). Battery out and in, per drone. Verified
  2026-10-02: all five sat locked with healthy batteries (4.10-4.22 V) after an
  e-stop, and the only symptom was that nothing flew. Every show now checks
  this BEFORE uploading — `check_supervisor`/`report_supervisor` in
  **`crazyflie_shows/preflight.py`** — because the upload is ~55 s and the
  arming failure used to come after it. `arm()` is fire-and-forget
  (`crazyflie_py` never inspects the response), so a refused arm is otherwise
  invisible: the only positive confirmation a drone actually flew is its mocap
  altitude. A silent `/cfX/status` is counted as a NOTE, not a refusal,
  because that is also what the telemetry stall looks like — watch that drone
  on takeoff.
- **Server BLOCKS FOREVER on the first unreachable enabled drone.** The cpp
  server connects drones in lexicographic `std::map` order and hangs
  **silently** on the first enabled drone that doesn't answer radio — one
  unreachable drone kills the whole launch (no error, no `/all/*` services,
  needs SIGKILL). Go/no-go rule: **scan every enabled address before every
  launch** — `./scripts/scan_fleet.sh`, which derives the list from the yaml
  and reports GO/NO-GO. Never scan a list written down in prose: the five
  copies that used to exist in this repo had all drifted, and the drone none
  of them named (cf4) is the one the yaml marks intermittent.
  cf6 died this way 2026-08-04 (silent on full channel/datarate
  sweeps at its own AND factory address — physical check needed).
- **Two Crazyradios (when running two dongles — current rig is single-dongle):
  channels must be ≥2 apart at 2M.** A 2M channel is ~2 MHz wide, so adjacent
  channels overlap and crazyflie-link-cpp refuses the pair — USBManager.cpp:
  `"Channels 80 and 81 are already served by Crazyradio 0"`. Historical
  two-dongle rig: cf1 on `radio://0/80/2M`, cf11 on `radio://1/90/1M`
  (10 channels clear).
- **URI datarate must match the drone.** A wrong datarate in the URI (e.g. `2M`
  for a drone talking `1M`) makes the server hang **forever** waiting for a
  drone that never answers — no error, and the `/all/*` services are never
  created. Verify with a scan on the drone's address
  (`scan --address 0xE7E7E7E711` → `radio://*/90/1M/...`).
- **ONE `crazyflies.yaml`: `crazyflie/config/`.** It is what the server reads,
  what every planner reads, and what `sync_initial_positions.py` writes.
  `crazyflie_shows` shipped a second copy until 2026-10-02 — that is gone, and
  do not reintroduce one: the copies drifted (the show's had no cf8 while the
  workspace's did, so the planner verified one fleet and the server flew
  another). `launch.py`/`show_launch.py` still accept
  `crazyflies_yaml_file:=<path>` for a one-off fleet; `show_launch.py` prints a
  **FLEET YAML OVERRIDE** banner naming the file and the `--yaml` sync command,
  because an override silently decouples the file the server seeds from the
  file the sync writes. Per-show fleet changes should be an `enabled:` edit in
  the one file, not a second file.
- **`initial_position` comes from `/poses`, never `/cfX/pose`.** The onboard
  estimate is seeded by the yaml — copying it back is circular. **Use
  `scripts/sync_initial_positions.py`** (mocap up, server not yet started): it
  samples `/poses`, matches each drone to the rigid body of the same name, and
  rewrites only the `initial_position` triples in place (comments preserved).
  **Scope is the ROOM, not the fleet** (changed 2026-10-02): it writes a mark
  for every drone mocap is streaming, `enabled` or not, so switching fleets
  between shows never carries a stale mark — place once, sync once, then enable
  whichever subset the show needs (`--enabled-only` for the old behaviour). An
  enabled drone that is not streamed is still a refusal; a parked one is
  skipped, and a parked drone standing <1 m from a flying one is reported as a
  mark that cannot be used until it moves. It REFUSES to write when an enabled
  drone is not streamed, is moving
  (>10 mm spread over the window), sits above 0.5 m, or when two drones are
  <1 m apart — `--dry-run` to preview, `--force` to override, `--with-z` to
  write the measured z instead of keeping the yaml's. Manual equivalent: read
  x/y from `ros2 topic echo /poses | grep -A5 -- '- name: cf1$'` and edit by
  hand. Either way, restart the server (yaml read only at launch). Enabled
  drones **≥1 m apart** (same-trajectory flight preserves start separation),
  and each drone at ITS OWN yaml position — wrong-corner placement = crossing
  goTo paths = the real collision of 2026-08-04.
- **Sim `plan_start_trajectory` arity — DO NOT ASSUME, PROBE.** This entry used
  to claim the binding is 7-arg (`relative_position`/`relative_yaw` +
  `start_from`/`start_yaw`). That is **backwards** for the build on this box:
  verified 2026-09-17, `~/crazyflie-firmware/build/cffirmware.py` exposes
  `plan_start_trajectory(p, trajectory, reversed, relative, start_from)` —
  **5 args**. Calling it with 7 raises `TypeError: takes 5 positional arguments
  but 7 were given`, which **kills the sim server outright at the first
  `startTrajectory`** — the demo runs fine through takeoff, waypoints and the
  gather, then the server dies mid-flight and the script hangs forever in the
  next `sleep`. `crazyflie_sim/crazyflie_sil.py` now picks the call by
  `inspect.signature(...)` arity at import, so either binding works. Sim-only;
  hardware unaffected.
- **Sim runs need `--ros-args -p use_sim_time:=true`** for any script that
  streams setpoints or sleeps on a schedule (the escort included) — the sim clock is
  ~4x slower than wall time, so without the flag the script races ahead of the
  physics. Hardware runs WITHOUT the flag.
- **LED convention: green = drone connected and ready for command; red =
  drones are in flight / a script is controlling them.** The server turns the
  Color LED deck green on connect (and off on clean disconnect); every
  crazyflie_py script sets it red for its lifetime and restores green on exit
  (`crazyswarm_py.py`, atexit — survives exceptions and Ctrl-C; if rclpy is
  already shut down the deck keeps its last color). Change colors manually
  with `scripts/led.sh` or `ros2 run crazyflie_examples color_led`.

