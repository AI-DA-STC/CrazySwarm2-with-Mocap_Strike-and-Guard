# Flight logs

Every flight is recorded to a folder of its own, so that what happened can be
answered after the console has been closed. A NEAR MISS line used to exist only in
the console's memory.

## Where they are

```
~/.ros/flight_logs/<YYYYmmdd_HHMMSS>_<script>/
    output.log        everything the show printed, each line stamped with the wall clock
    meta.json         the exact command, start and end, exit code, git commit (+ dirty?),
                      branch, host, ROS_DOMAIN_ID, sim or hardware
    config/           crazyflies.yaml and arena.yaml as they were at the start
    bag/              ros2 bag (mcap) of the topics below
    report.txt        the numbers, written by flight_report after the flight
    report.json       the same, for scripts
    guard_trace.csv   guard_show only: per tick, per drone, measured and commanded
                      position, phase and intent
```

`FLIGHT_LOG_ROOT` moves the folders. Nothing is deleted automatically. A flight is
about 6 MB a minute, mostly `/poses`.

## Who records

- **The mission console** records every process it treats as a flight: the
  Dashboard's Fly and every mission's main script (`procs.is_flight`). This
  happens whatever the mission is. The recorder (`ros2 bag record ...`) and the
  report (`ros2 run crazyflie_shows flight_report ...`) appear in the live console
  as ordinary processes, with their command lines.
  `MISSION_CONSOLE_FLIGHT_LOG=0` turns recording off. Code:
  `console/mission_console/flightlog.py`.
- **A terminal:** put `./scripts/record_flight.sh` in front of the command:

  ```bash
  ./scripts/record_flight.sh ros2 run crazyflie_shows guard_show --ros-args -p paced:=true ...
  ```

  The show behaves exactly as without it: Enter works at its gates, and Ctrl-C
  reaches the show. The bag runs in its own session, so the Ctrl-C does not end
  the recording before the abort landing has finished.

The show is told its folder through `$FLIGHT_LOG_DIR`. A show that writes its own
trace (`guard_show`) puts it there.

## What the bag records

| Topic | Rate | Why |
|---|---|---|
| `/poses` | mocap rate | where every rigid body really was, the DJI included |
| `/cfN/cmd_full_state`, `cmd_position`, `cmd_hover`, `cmd_vel_legacy` | 20 Hz while streaming | what each drone was told |
| `/cfN/pose` | 10 Hz | the drone's own estimate, to compare with mocap |
| `/cfN/status` | 1 Hz | battery, signal, unicast latency, packets, supervisor flags |
| `/cfN/kalman_preflight` | 5 Hz | the preflight plotter's estimator values |
| `/cfN/downwash` | 10 Hz | only if its log block is switched on (off by default; below) |
| `/rosout` | events | the server's command journal (takeoff, land, emergency) and every warning |
| `/escort/vip` | as published | the VIP keyboard's point (`vip_mode:=manual`) |

High-level commands (`takeoff`, `goTo`, `land`) are service calls. A bag does not
record those, but the server logs each one to `/rosout`, and the report lists them.
`/guard/markers` is left out on purpose: about 1.5 MB/s, and `guard_trace.csv`
keeps the intents.

## Reading a flight

```bash
ros2 run crazyflie_shows flight_report ~/.ros/flight_logs/<folder>
```

This runs on its own after every recorded flight; run it again by hand any time.
`--close 0.6` lists every pair that came closer than 0.6 m.

**Per drone:**
- **track err**: the commanded position against mocap at the same instant
  (mean / 95th percentile / max).
- **lag**: the delay that best lines the aircraft up with its commands.
- **resid**: the error left once that lag is taken out. A drone that follows
  faithfully but late has a large error and a small resid. A drone that does not
  follow has a large resid.
- **cmd Hz / stalls**: the command stream's rate, and how often it stopped for
  more than 0.15 s while streaming. That is the radio, nearly always.
- **mocap Hz / drops / jumps**:
  - drops: gaps of more than 0.1 s;
  - jumps: a pose that moved further in one frame than a Crazyflie can fly, which
    means a swapped or ghost rigid body.
- **est yaw p95**: the onboard heading against mocap, the fly-away precursor
  ([../troubleshooting.md](../troubleshooting.md)).
- **batt**: start > lowest > end; **lat ms**: the worst unicast latency;
  **flags**: any tumbled, locked or crashed bit seen.
- **motor%**: the highest motor PWM, from the downwash block when it is on; **SATURATED n s**:
  time with a motor above 95 %, when the drone can no longer hold its height.
  **tilt**: the largest roll/pitch.

**Separation:**
- the closest measured pair, and how far apart their *commands* were at that
  moment;
- every pair inside `--close`, each with a verdict:
  - *mocap glitch*: a pose jumped at that moment;
  - *the plan put them there*: the commands were as close;
  - *the aircraft lagged their commands*.
- the closest any drone came to each other rigid body (the DJI).

**Also listed:**
- the show's own alarm lines (NEAR MISS, SAFETY PAUSE, ABORT, ...);
- grouped `/rosout` warnings;
- the server's commands.

To look at the raw data, open the bag in Foxglove (`foxglove_bridge` is in the
launch), or play it back with `ros2 bag play`.

## The downwash detector

A drone flying under another loses lift. The report flags it in two halves.

**From mocap** (every flight, including ones recorded before the log block existed):
- A drone is *overflown* while another Crazyflie is above it: within 0.35 m across
  and 0.05 to 1.5 m higher.
- For the DJI or any other rigid body the cone is wider and taller: 0.9 m across,
  up to 3.0 m higher.
- An overflight is a **downwash event** when the drone underneath *sank*. That
  means its height fell 5 cm or more below its command, beyond how far it usually
  trails. For a high-level flight with no streamed command, it means 5 cm below
  where it was.
- Overflights with no measurable sink are counted, not listed.

**From the drone: optional, OFF by default.** To investigate downwash, uncomment
the `downwash` log block in `crazyflies.yaml` (10 Hz, 24 of 26 bytes), restart the
server, and fly. It logs `stabilizer.roll`, `stabilizer.pitch`, `stabilizer.thrust`, `acc.z`
and `motor.m1` to `motor.m4`. Each event gets:
- how much the thrust rose above that drone's own median;
- the peak motor PWM;
- the largest tilt;
- the lowest vertical acceleration (1.0 g at hover; a dip means it was pushed down).

The thresholds are `DW_*` at the top of `flight_report.py`. They are first guesses;
the first flights with the block will say whether they need moving.

**The cost** is why it is off: about 10 more packets a second per drone, on links
that already warn (the `pose` comment in `crazyflies.yaml`). Switch it on for a
session that is about downwash, then comment it out again. Every variable was
checked against this fleet's log TOC (`cache/E46BE59F.json`). A drone with
trimmed firmware that lacks one of them makes the server abort at connect. The
console's fleet check counts the block's bytes (`configio.VAR_BYTES`).

## Not logged yet

- `pm.vbat` at 10 Hz (battery sag under load) does not fit in the downwash block.
  The 1 Hz status has the voltage.
- `/poses` carries no latency or residual from Motive, so the logs cannot tell a
  late frame from a wrong one. The vendored driver could publish
  `NamedPoseArrayV2` (which has latencies); that would be a change to
  `motion_capture_tracking`.
