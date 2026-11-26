# Server changes: what this repo changed in Crazyswarm2

The Crazyswarm2 in `src/` came from the team repo
[AI-DA-STC/CrazySwarm2-with-Mocap](https://github.com/AI-DA-STC/CrazySwarm2-with-Mocap),
itself built on [IMRCLab/crazyswarm2](https://github.com/IMRCLab/crazyswarm2). Here
**"upstream" means that team repo** and **"the fork" means this code**. Most changes make
the server survive the radio failures in [known-issues.md](known-issues.md), which holds
the evidence; this page holds the design, the traps and the order to re-apply them.

For a maintainer re-applying the changes onto a newer upstream, or choosing which to offer
back. Tags: **[diff]** read in `git diff upstream/main HEAD` (2026-10-08); **[inferred]**
reasoned from the code, not measured. Everything else cites known-issues.md.

## Regenerate this diff before trusting the document

```bash
git remote add upstream https://github.com/AI-DA-STC/CrazySwarm2-with-Mocap.git   # once
git remote set-url --push upstream DISABLED   # fetch only: changes go back by pull request
git fetch upstream
git merge-base upstream/main HEAD       # 9ed4bae as of 2026-10-08: no merge/rebase since

# exact per-file added/removed (use --numstat: --stat sums added + removed)
git diff --numstat upstream/main HEAD -- \
  src/crazyswarm2/crazyflie/src/crazyflie_server.cpp \
  src/crazyswarm2/crazyflie/config/server.yaml \
  src/crazyswarm2/crazyflie/launch/launch.py \
  src/crazyswarm2/crazyflie/deps/

# the server diff itself
git diff upstream/main HEAD -- src/crazyswarm2/crazyflie/src/crazyflie_server.cpp
```

If the output no longer matches the numbers here, the numbers here are stale.

## Summary

| # | group | lines | why | portable? |
|---|---|---|---|---|
| 1 | Telemetry watchdog (detect + 2-tier recovery of dead log blocks) | ~170 fn + ~60 builder refactor | a drone silently deletes its own log blocks after a 1 s receive gap | mechanism yes (default off); tuning rig-specific |
| 2 | Bounded trajectory upload + `bad_trajectories_` refusal | server + `Crazyflie::uploadTrajectory` | an upload could wedge the server, or report success for a trajectory with a hole | **yes, strongest candidate** |
| 3 | Airborne gate (`may_be_airborne` / `commanded_flight_` / mocap z) | server | never `logReset` a drone that might be flying | only with mocap |
| 4 | Keep-alive timer (`keepalive_frequency`) | small | per-drone unicast floor under the 1 s timeout | yes; insurance, not a fix |
| 5 | Packet tracing (`trace_cf`) | server + 4 link-cpp files | localised the stall to the drone | yes, cheap when off |
| 7 | `server.yaml` | 54 / 3 | §7 | partly |
| 8 | `launch.py` (`trace_cf`, `server:=False`) | 26 / 3 | mocap up, server down, for `sync_initial_positions.py` | yes |
| 9 | Library changes the server needs | `crazyflie_cpp` | identity-matched replies, bounded waits, `abandon()`, trace hooks | yes, the other strongest candidates |

**Exact file totals [diff]:**

| file | added | removed | note |
|---|---|---|---|
| `crazyflie/src/crazyflie_server.cpp` | 445 | 22 | 1760 → 2183 lines |
| `crazyflie/config/server.yaml` | 54 | 3 | |
| `crazyflie/launch/launch.py` | 26 | 3 | |
| `crazyflie/deps/.../crazyflie_cpp/**` | 512 | 68 | `Crazyflie.h` 266/68, `Crazyflie.cpp` 212/9, `crtp.h` 51/0, link-cpp 51/0 across 4 files |

## 0. What "upstream" is, and what is not in the diff

- `upstream` = `AI-DA-STC/CrazySwarm2-with-Mocap` at `9ed4bae` (10 Sep 2026), also the
  merge base; the fork has not been rebased since. It derives from IMRCLab, so anything
  before that fork point is invisible here. **[diff]**
- **The server cannot be re-applied from `crazyflie_server.cpp` alone:** it calls API that
  exists only in the vendored libraries (§9).
- Already at `upstream/main`, so **not** in the diff although earlier notes called them
  fork changes **[diff]**: `add_on_set_parameters_callback` instead of
  `ParameterEventHandler` (upstream `crazyflie_server.cpp:1311`/`1319`); LED green on
  connect, off on clean disconnect (lines 381-395, 580-606);
  `query_all_values_on_connect: True` (this fork only lowercased it); the foxglove_bridge
  and preflight-GUI nodes and the `rviz` / `preflight` / `foxglove` launch arguments
  (lines 252-255, 286, 307-319). Whether they are IMRCLab or AI-DA-STC originals was not
  checked. **If you rebase onto anything that is not AI-DA-STC, re-apply them:** this rig
  never delivers a node's own `/parameter_events`
  ([known-issues](known-issues.md#a-node-never-hears-its-own-parameter_events)), so
  without the callback `ros2 param set` never reaches the drones. The LED writes
  `colorLedBot.wrgb8888` (`0xWWRRGGBB`, green `0x0000FF00`); the red-while-flying half is
  in `crazyswarm_py.py`, not the server.

## 1. Telemetry watchdog: detect and recover from "link alive, log data dead"

The failure and its evidence: [known-issues](known-issues.md#link-alive-log-data-dead).

**Where:** `CrazyflieROS::check_telemetry_watchdog()`, `restart_log_blocks()` (tier 1),
`rebuild_log_blocks()` (tier 2), `add_log_builder()`. `on_link_statistics_timer()` calls
the watchdog first; `last_log_rx_` is stamped in all five `on_logging_*` callbacks,
`last_latency_rx_` in `on_latency`. Config: `telemetry_watchdog_s: 5.0` in `server.yaml`.
**Trap:** the C++ fallback when the key is absent is `0.0`, off, so a yaml without the key
silently disables recovery.

**Upstream** builds each block inline
(`log_block_pose_.reset(new LogBlock<logPose>(&cf_, {...}, cb)); ...->start(period)`);
nothing watches for silence or can re-create a block. **[diff]**

**The fork:**

1. Each of the five block kinds (pose, scan, odom, status, generic/custom) is registered
   through `add_log_builder(lambda)`, which runs the lambda once (same behaviour at
   connect) and keeps it in `log_block_builders_`: **the closure is the only record of how
   to make that block again.** Periods live in `period_pose_`, `period_scan_`,
   `period_odom_`, `period_status_`, `periods_generic_`; `publishers_generic_` is a
   `std::list` so the `user_data` pointer captured by the generic builder stays valid.
2. A drone is stalled when no log callback came for `telemetry_watchdog_s`, **and** its
   latency echo is current (≤ 2.0 s; otherwise it is an ordinary dead link), **and**
   `may_be_airborne()` is false (§3). Recovery sets `recovering_` and runs:
   - **Tier 1** `restart_log_blocks()`: `stop()` then `start(period, RECOVERY_TIMEOUT_MS)`
     per block. Works only if the blocks still exist on the drone.
   - **Tier 2** `rebuild_log_blocks()`, when tier 1 throws: `cf_.logReset(RECOVERY_TIMEOUT_MS, 2)`
     **first, as a probe** (false → throw, nothing destroyed), then `abandon()` and free
     every host block, clear `periods_generic_`, set `recovery_timeout_ms_`, and re-run
     every builder, re-checking `may_be_airborne()` between builders.
   - A rebuild that fails half-way sets `rebuild_pending_` and is retried at the same
     cadence (a half-built set still delivers data, so the silence timer would never fire
     again). A retry **skips tier 1**, which would "succeed" on the surviving blocks.
3. `RECOVERY_TIMEOUT_MS = 1000`, ×2 tries (raised from 300 ms after a real `start`
   answered later). `recovery_timeout_ms_` is 0 (unbounded) at connect and non-zero only
   during a rebuild; every exit path resets it.

**Do not reorder probe-before-destroy:** the original order freed every host block before
an unanswered `logReset`, leaving the drone with no dispatch while it might still hold
live blocks. **If reverted:** the stall returns and only a server restart clears it.

**Portable?** The mechanism suits any Crazyswarm2 server on a saturated dongle; the tuning
(5 s, 1000 ms ×2, z ≤ 0.10 m) is rig-specific. Split the PR: builder refactor first
(behaviour-neutral), watchdog second, default `0.0`. A rig without mocap needs another
interlock (§3) first.

**Known wart [inferred]:** a tier-2 rebuild runs on the fleet-wide, mutually exclusive
`callback_group_cf_srv`, so a worst-case rebuild freezes every drone's services and
telemetry for up to ~14 s ([OPEN](known-issues.md#open-one-fleet-wide-callback-group)).

## 2. Bounded trajectory upload, `bad_trajectories_`, and refusing to fly a failed upload

The failure and its evidence: [known-issues](known-issues.md#an-upload-can-wedge-the-server-fixed-2026-10-05).

**Where:** the `upload_trajectory` handler (try/catch, `response->success` / `message`),
`trajectory_is_bad()`, `mark_trajectory_bad()`, `bad_trajectories_` +
`bad_trajectories_mutex_`, and the refusal in both the per-drone `start_trajectory` and
the broadcast `CrazyflieServer::start_trajectory`. Library: `Crazyflie::uploadTrajectory`
(§9). **Upstream:** an unbounded `waitForResponse`, no try/catch, no success report, and
`start_trajectory` starts whatever id it gets.

**The fork:**

- The upload throws after bounded retries (500 ms × 2 per wait, each chunk resent up to 3
  times, 10 s per chunk, 90 s per call). The handler catches, logs FATAL, sets
  `success=false` and marks the id bad; a later clean upload clears it.
- Unicast `start_trajectory` refuses a bad id with a FATAL log. The **broadcast** handler
  refuses for everyone if any drone has the id marked bad, so the formation holds instead
  of one drone flying garbage. Shows start trajectories by broadcast, which never touches
  a `CrazyflieROS`, so the per-drone refusal alone would not stop them.
- The set is mutex-guarded: written on `callback_group_cf_srv`, read on
  `callback_group_all_srv_`; an unguarded `std::set` is UB.

**If reverted:** one starved drone can wedge the server for good, and a show can fly a
partly written trajectory: `piecewise_eval` applies whatever bytes are there (no
validation, clamp or finiteness check), and the supervisor reacts only to TUMBLED and
battery. **Trap:** do not "simplify away" the refusal, or drop the mutex.

**Portable?** Yes: high value, rig-independent. `UploadTrajectory.srv` already has
`success` / `message` (and `crazyflie_py` raises on it); `StartTrajectory.srv` has no
response fields, hence the server-side set. Companion show-side check: commit `0d9ca40`.

## 3. The airborne gate: `may_be_airborne()` / `commanded_flight_` / mocap z

**Where:** `may_be_airborne()`, `note_commanded_flight()`, `note_mocap_z()`,
`CrazyflieServer::note_commanded_flight_all()`; called from per-drone and broadcast
`takeoff`, `go_to`, `start_trajectory`, and from the `/poses` handler for every known
drone. `commanded_flight_`, `last_mocap_z_valid_`, `last_mocap_z_` are `std::atomic`.
**Upstream:** nothing (no recovery to gate).

**The fork:** the watchdog may touch a drone only if mocap positively shows z ≤ 0.10 m
**and** `commanded_flight_` is clear. Unknown altitude counts as airborne. Commands set the
latch, mocap alone clears it. Mocap, because `/cfX/status` is dead exactly when it would
be asked; the latch covers `/all/*` because shows take off by broadcast.

**History [diff]:** until 2026-10-06 `commanded_flight_` was never set true, so the gate
was mocap alone; it was evaluated once though the bounded worst case to the last builder
is several seconds (hence the re-check); and the three fields were plain types written on
`callback_group_mocap_` and read on `callback_group_cf_srv`, a data race on the one guard
that decides whether to touch a possibly flying drone.

**If reverted:** the watchdog could `logReset` a flying drone; whether that harms it was
never measured **[inferred]**. Keep the fail-safe.

**Portable?** Only with mocap, together with the watchdog. A rig without mocap needs
another "on the ground" signal, e.g. the supervisor's `CAN_BE_ARMED` / flying bits from
`/cfX/status`, unusable here because that topic is the one that goes silent.

**Gap (checked 2026-10-08 by reading the code):** there is deliberately no latch in
`land` / `emergency`, and `notify_setpoints_stop` and both `cmd_full_state_changed`
handlers do not latch either. The escort streams `cmdFullState` but starts with
`cf.takeoff(...)`, which latches, so the gate holds for it. A show that streamed
`cmdFullState` without a prior takeoff / go_to / start_trajectory would rest on mocap z
alone. Not tested on hardware.

## 4. Keep-alive

**Where:** `keepalive_timer_`, `keepalive_hz_`; `keepalive_frequency` (default 4.0,
mirrored in `server.yaml`) is declared in the `CrazyflieServer` constructor. The timer
calls `cf_.triggerLatencyMeasurement()` on **`callback_group_cf_cmd`**, not `_cf_srv`, so a
rebuild cannot silence it. **Upstream:** none.

**Status: insurance, not a fix** ([why](known-issues.md#link-alive-log-data-dead)): a
healthy drone already receives ~168 unicast/s from the link library's auto-pings, and a
starved connection starves the keep-alive too. **If reverted:** probably nothing visible
today; it guards against auto-ping behaviour changing. Upstream will ask for evidence
that it helps, and there is none beyond the argument.

## 5. Packet tracing (`trace_cf`)

**Where:** `debug.trace_cf`, parsed in the `CrazyflieROS` constructor (`"all"`, `"*"`, or
comma-separated names) → `cf_.setTrace(true)` plus a WARN line. `launch.py` folds
`LaunchConfiguration('trace_cf')` (default `''`) into `server_params[1]['debug.trace_cf']`.
Library: `Connection::setTrace`, the `ConnectionImpl::trace_*` counters, a block in
`CrazyradioThread.cpp` (one relaxed atomic load per ack when off), and `Crazyflie::m_trace*`
in `processPacket`.

It prints one summary per second per drone from the link layer and from `processPacket`
(per-packet printing would be ~825 lines/s for five drones and perturb the timing), plus
per-packet lines only for anomalies (a valid but unregistered log packet, a port-5 packet
failing `valid()`).

**Traps:** it is a **launch argument** (`ros2 launch` has no `--ros-args`), read **at
connect only**. **[diff]** The comment above the parser still shows
`--ros-args -p debug.trace_cf:=cf1`, which does not work through `ros2 launch`; trust
`launch.py`. The `telemetry_watchdog_s` declaration sits in the middle of that hunk:
cosmetic. **If reverted:** you lose the diagnostic. **Portable?** Yes.

## 6. Why three earlier-claimed "fork changes" are not in this diff

See §0: they are already at `upstream/main`.

## 7. `server.yaml` delta (54 added, 3 removed) [diff]

| key | upstream | fork | why |
|---|---|---|---|
| `keepalive_frequency` | absent | `4.0` | §4 |
| `warnings.motion_capture.warning_if_rate_outside` | `[80.0, 120.0]` | `[40.0, 60.0]` | Motive streams 50 Hz here, so the old band warned every launch (`Motion capture rate off (Avg: 50.3)`). **Rig-specific: derive it from your Motive rate.** |
| `warnings.communication.publish_stats` | `false` | `true` | feeds `/cfX/connection_statistics`, how link stalls are diagnosed; one small message per drone per second. The yaml's counter comments are the corrected version. |
| `telemetry_watchdog_s` | absent | `5.0` | §1; `0`, or no key, disables |
| `firmware_params.query_all_values_on_connect` | `True` | `true` | cosmetic |
| comment on `cf231` | none | an upstream placeholder, not a drone | |

`keepalive_frequency` and `telemetry_watchdog_s` are top-level under
`/crazyflie_server: ros__parameters:`, **not** under `warnings:`.

## 8. `launch.py` delta (26 added, 3 removed) [diff]

- `trace_cf` launch argument (§5).
- `server` launch argument (default `True`). **`server:=False` starts mocap, RViz and the
  preflight GUI without a server**: no radio owner, nothing armable, the state
  `scripts/sync_initial_positions.py` needs.
- The three server `Node`s (`cflib`, `cpp`, `sim`) changed from
  `LaunchConfigurationEquals('backend', X)` to
  `IfCondition(PythonExpression(["'", backend, "' == X and '", server, "'.lower() in ('true','1')"]))`.
  **Trap: keep all three in step**, or `server:=False` still starts that backend, a radio
  owner you did not expect while rewriting `initial_position`.

## 9. Library changes the server depends on (not in `crazyflie_server.cpp`, but required)

All under `src/crazyswarm2/crazyflie/deps/crazyflie_tools/crazyflie_cpp/`. **[diff]**

| API the server uses | defined in | what it is |
|---|---|---|
| `Crazyflie::setTrace(bool)` | `Crazyflie.h` → `Connection::setTrace` | trace switch (§5) |
| `Crazyflie::logReset(unsigned timeout_ms, size_t tries)` → `bool` | `Crazyflie.cpp` | bounded probe. The no-arg `logReset()` stays **unbounded on purpose** (connect's first handshake) and now matches by `answersLogReset` |
| `LogBlock` / `LogBlockGeneric` ctor arg `timeout_ms` (0 = unbounded) | `Crazyflie.h` | recovery passes `recovery_timeout_ms_` |
| `LogBlock::start(period, timeout_ms)`, two-arg with **no default**, plus the one-arg forwarder | `Crazyflie.h` | **Trap: no default argument, and do not collapse the forwarder.** Bounding connect would let one busy link kill the whole launch, because a throw from a log-block builder is not caught where `CrazyflieROS` is constructed. Tier 1 once used the one-arg form (`m_timeout_ms = 0`) and so waited unbounded: the trap `627ab55` closed for uploads, left open one function away (fixed 2026-10-06). |
| `LogBlock::abandon()` | `Crazyflie.h` | skips the destructor's stop handshake for blocks already gone from the drone |
| `crtpLogControlResponse::isAnswerTo(p, cmd, blockId)`, `isAnswerToCommand(p, cmd)`, enum `crtpLogControlCommand` | `crtp.h` | identity matching. **`logReset` is matched on the command only:** its request (`Packet(5,1,1)`) has no block id, so `data[1]` of the reply is indeterminate |
| memory-write reply matched by memory id + 32-bit address; non-zero status **throws** (it can only mean the bounds check failed: deterministic, not retried) | `Crazyflie::uploadTrajectory` | §2 |
| `registerLogBlock` / `unregisterLogBlock` guards | `Crazyflie.cpp` | `erase(end())` on a missing id was UB; plus constructor rollback if a `LogBlock` ctor throws |
| trace counters | `Crazyflie.cpp processPacket`, `CrazyradioThread.cpp`, `ConnectionImpl.h`, `Connection.cpp/.h` | §5 |

### Reply matching by identity, not shape: the most important library change

`crtpLogControlResponse::valid()` and `crtpMemoryWriteResponse::valid()` test only port,
channel and payload size, which every reply of that kind passes. Matching on command byte
+ block id (log) or memory id + address (memory) is exact, because the firmware answers by
**reusing the request packet**: `log.c logControlProcess` overwrites only `data[2]` and
`size`, and `crtp_mem.c memWriteProcess` says *"Dont' touch the first 5 bytes, they will
be the same."* Two silent failures this fixed (2026-10-06):

1. Tier 1 is literally `stop(); start(p);`, so a late **stop** answer satisfied the
   **start** wait: tier 1 "worked", logged `log blocks restarted`, and the watchdog never
   escalated to tier 2.
2. A resent upload chunk could leave the host one reply out of phase for the rest of the
   upload, so a chunk whose request was lost counted as written and `success=true` came
   back for a trajectory with a 24-byte hole. `sizeof(poly4d)` is 132 and `132 % 24 != 0`,
   so the hole lands mid coefficient array and the drone flies a hybrid of two
   polynomials.

Both are portable and the strongest upstream candidates. The tighter memory predicate
removed an accidental latency absorber, so a stale reply now counts as proof the drone is
alive but backlogged and buys more time, under the per-chunk and per-call caps.

**Trap: do not "fix" `requestMemoryToc`.** An audit claimed it consumes GetInfo replies
positionally with no id check. Inverted: `Crazyflie.cpp:19` is an unconditional
`#define FIRMWARE_BUGGY` with no `#undef`, so the positional `#ifndef` branch is
preprocessed away and the live one is `if (res::id(p) != i) { warn; --i; }` (the `assert`
is the dead `#else`). The drone cannot reorder these anyway: `memTask` is one FreeRTOS
task draining one FIFO and replying synchronously, echoing the requested id. Dropping the
`--i` removes the only absorber for a duplicated request, and indexing
`m_memoryTocEntries[res::id(p)]` would be an unbounded write driven by a byte the drone
chose, into a vector sized from an earlier packet: heap corruption in the process that
owns the radio. The ping-pong also has a firmware reason: `crtpRxTask` blocks forever on a
full port queue, so one GetInfo outstanding keeps at most one MEM packet in that 16-deep
queue.

**Still unbounded, same trap:** most other `waitForResponse()` calls (params, log TOC).
They run at connect, where blocking is documented; bound them before calling any from a
service handler.

## 10. Re-apply checklist on a newer upstream

1. `git fetch upstream` and diff the three first-party files and `deps/` (commands at the
   top). Expect conflicts in `CrazyflieROS` log-block construction: the builder refactor
   touches every block.
2. Apply in this order, so each step compiles and stays behaviour-neutral until the last:
   library API (§9) → builder refactor (`add_log_builder`, periods) → state and atomics
   (§3) → `on_logging_*` stamps → watchdog (§1) → upload + bad-trajectory set (§2) →
   keep-alive, trace, yaml, launch.
3. Verify: `./scripts/build.sh` with **no new warnings** under `src/crazyswarm2`. The sim
   cannot exercise any of this (a different server binary). Then hardware, props off, on
   the floor: interrupt one drone's link for > 1 s and confirm `/cfX/pose` returns ~1 s
   after the stall is declared.
4. The fleet-wide callback-group refactor, if ever done: its acceptance test and the
   cheaper alternative are in [known-issues](known-issues.md#open-one-fleet-wide-callback-group).

## 11. What to offer upstream, in order

1. Identity-matched replies, the bounded, resent, status-checked upload with
   `success` / `message`, and the bad-trajectory refusal (§2, §9).
2. The builder refactor + the watchdog, behind `telemetry_watchdog_s: 0` (default off).
3. The trace hooks.
4. The `server:=False` launch argument.

**Keep fork-only:** the mocap-z gate wiring if upstream is not mocap-centric, the 40-60 Hz
warning band, and `publish_stats: true`.

## Known gaps in this document

- Per-group line counts are approximate; only the per-file totals are exact. Recompute a
  hunk with `git diff upstream/main HEAD -- <file> | grep -c '^+'`.
- Not diffed against IMRCLab, so it cannot say which upstream features are IMRCLab's and
  which AI-DA-STC's.
- The hardware numbers are cited from known-issues.md and the yaml comments, not
  re-measured.
- `Crazyflie.h` / `Crazyflie.cpp` were scanned for key terms, not read line by line; §9 may
  omit minor edits (the +266/−68 in `Crazyflie.h` includes unlisted constructor/ordering
  changes).

---

Full earlier text: `git show 678bac1:docs/rig/server-changes.md`
