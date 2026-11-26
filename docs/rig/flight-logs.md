# Flight logs

Every flight is recorded to a folder of its own, so what happened can be answered after
the console is closed.

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

`FLIGHT_LOG_ROOT` moves the folders. Nothing is deleted automatically; a flight is about
6 MB a minute, mostly `/poses`. The show learns its folder from `$FLIGHT_LOG_DIR` and
writes its own trace there (`guard_show`).

## Who records

- **The mission console**, for every process it treats as a flight: the Dashboard's Fly
  and every mission's main script (`procs.is_flight`). The recorder (`ros2 bag record`)
  and the report (`flight_report`) show in the console as ordinary processes.
  `MISSION_CONSOLE_FLIGHT_LOG=0` turns it off. Code: `console/mission_console/flightlog.py`.
- **A terminal:** prefix the command with `./scripts/record_flight.sh`:

  ```bash
  ./scripts/record_flight.sh ros2 run crazyflie_shows guard_show --ros-args -p paced:=true ...
  ```

  The show behaves as without it (Enter at its gates, Ctrl-C reaches it). The bag runs in
  its own session, so a Ctrl-C does not end the recording before the abort landing ends.

## What the bag records

| Topic | Rate | Why |
|---|---|---|
| `/poses` | mocap rate | where every rigid body really was, the DJI included |
| `/cfN/cmd_full_state`, `cmd_position`, `cmd_hover`, `cmd_vel_legacy` | 20 Hz while streaming | what each drone was told |
| `/cfN/pose` | 10 Hz | the drone's own estimate, to compare with mocap |
| `/cfN/status` | 1 Hz | battery, signal, unicast latency, packets, supervisor flags |
| `/cfN/kalman_preflight` | 5 Hz | the preflight plotter's estimator values |
| `/cfN/downwash` | 10 Hz | only if its log block is on (off by default; below) |
| `/rosout` | events | the server's command journal (takeoff, land, emergency) and every warning |
| `/escort/vip` | as published | the VIP keyboard's point (`vip_mode:=manual`) |

High-level commands (`takeoff`, `goTo`, `land`) are service calls, which a bag does not
record; the server logs each to `/rosout` and the report lists them. `/guard/markers` is
left out on purpose (about 1.5 MB/s; `guard_trace.csv` keeps the intents).

## Reading a flight

```bash
ros2 run crazyflie_shows flight_report ~/.ros/flight_logs/<folder>
```

It runs by itself after every recorded flight; run it again any time.
`--close 0.6` lists every pair that came closer than 0.6 m.

**Per drone:**

| Column | Meaning |
|---|---|
| track err | commanded position against mocap at the same instant (mean / p95 / max) |
| lag | the delay that best lines the aircraft up with its commands |
| resid | the error left once that lag is taken out: late but faithful = large error, small resid; not following = large resid |
| cmd Hz / stalls | the command stream's rate, and how often it stopped for more than 0.15 s while streaming (nearly always the radio) |
| mocap Hz / drops / jumps | drops: gaps over 0.1 s; jumps: a pose that moved further in one frame than a Crazyflie can fly (a swapped or ghost rigid body) |
| est yaw p95 | onboard heading against mocap, the fly-away precursor ([troubleshooting](../troubleshooting.md)) |
| batt / lat ms | start > lowest > end; the worst unicast latency |
| flags | any tumbled, locked or crashed bit. The supervisor has set `crashed, tumbled` at ordinary touchdowns (2026-11-17, 2026-11-23): check the mocap trace before calling it a crash |
| motor% / SATURATED / tilt | from the downwash block when on: peak motor PWM; time with a motor over 95 % (it can no longer hold height); largest roll/pitch |

**Separation:** the closest measured pair and how far apart their *commands* were then;
every pair inside `--close`, each with a verdict (*mocap glitch*: a pose jumped; *the plan
put them there*: the commands were as close; *the aircraft lagged their commands*); and
the closest any drone came to each other rigid body (the DJI).

**Also listed:** the show's alarm lines (NEAR MISS, SAFETY PAUSE, ABORT, ...), grouped
`/rosout` warnings, and the server's commands.

For the raw data, open the bag in Foxglove (`foxglove_bridge` is in the launch) or
`ros2 bag play` it. To watch a guard_show flight again (the console's 3D view rebuilt from
the log, or the hall camera's footage with every drone circled):
[../guard/details/flight-replay.md](../guard/details/flight-replay.md).

## The downwash detector

A drone flying under another loses lift. The report flags it in two halves.

**From mocap** (every flight, also ones recorded before the log block existed): a drone is
*overflown* while another Crazyflie is within 0.35 m across and 0.05-1.5 m above it (for
the DJI or any other rigid body: 0.9 m across, up to 3.0 m above). An overflight is a
**downwash event** when the drone underneath sank: its height fell 5 cm or more below its
command, beyond its usual trail (in a high-level flight with no streamed command: 5 cm
below where it was). Overflights with no measurable sink are counted, not listed.

**From the drone: optional, OFF by default.** Uncomment the `downwash` log block in
`crazyflies.yaml` (10 Hz, 24 of 26 bytes), restart the server, fly. It logs
`stabilizer.roll`, `stabilizer.pitch`, `stabilizer.thrust`, `acc.z` and `motor.m1` to
`motor.m4`, and each event gets: the thrust rise over that drone's own median, the peak
motor PWM, the largest tilt, and the lowest vertical acceleration (1.0 g at hover; a dip
means it was pushed down). The thresholds are `DW_*` at the top of `flight_report.py`,
first guesses until flights with the block say otherwise.

It is off because it costs about 10 more packets a second per drone on links that already
warn: switch it on for a downwash session, then off again. Every variable was checked
against this fleet's log TOC (`cache/E46BE59F.json`); a trimmed firmware lacking one makes
the server abort at connect. The console's fleet check counts the block's bytes
(`configio.VAR_BYTES`).

## Not logged yet

- `pm.vbat` at 10 Hz (battery sag under load) does not fit in the downwash block; the 1 Hz
  status has the voltage.
- `/poses` carries no latency or residual from Motive, so a late frame cannot be told
  from a wrong one. The vendored driver could publish `NamedPoseArrayV2` (which has
  latencies), a change to `motion_capture_tracking`.

---

Full earlier text: `git show 678bac1:docs/rig/flight-logs.md`
