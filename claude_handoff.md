# Claude handoff: Strike and Guard (Crazyflie rig)

> **How to use this file.** Read it at the start of a session, after [CLAUDE.md](CLAUDE.md).
> §1 is the current state, §2 is what is waiting on people, §3 is the next steps.
> Update all three before you stop.
> Last updated: 19 November 2026.

## 00. 19-11 later: safer at 1.0 m/s (NOT yet flown)

The user flies paced at **1.0 m/s** (default restored) and asked for stronger safety
without being too aggressive. Done (details: docs/details/guard-design-notes.md,
"Landing out of the way, and what the planner flies"):

* **Retired drones exit before landing** (`engine.py` `exiting` / `pop_landing`;
  `exit_*` in config.py): brake, 1.0 s to let the aircraft catch up, fly out past the
  VIP's landing rim if inside it, then land. Matrix at 1.0 m/s: unsafe cells 14 -> 1,
  10 -> 1, 23 -> 5 (still / DJI-hover / drifting DJI), closest pair 0.08 -> 0.34 m;
  game balance unchanged. `exit_min_s:=0.0` = old behaviour.
* **`plan_guard` plant = 0.4 s delay + 0.2 s lag** (`--delay`, `--tau`), fitted to the
  hardware traces; it also reinstates the winning striker at its setpoint, as
  guard_show does. Older planner numbers in this file are on the old plant.
* Tried and dropped: command-ahead (lead), speed-dependent keep-out padding, a
  finale settle. Why: the design notes.
* 103 tests pass; one simulator match at 1.0 m/s clean. Two sim trace folders were
  written to `~/.ros/flight_logs/20261119_103551_guard_show` and `..._120038_...`
  (simulator, not flights).

## 0. 19-11: the 17-11 18:00/18:02 flights, fixed offline (NOT yet flown)

Read from `~/.ros/flight_logs/20261117_180002_guard_show` and `..._180244_...`:

* **"The drones did not follow the DJI."** The form-up built its slots ONCE, round where
  the DJI was when the gate was passed; the pilot then moved it 1.4 m (y -0.2 -> -1.6),
  the ring stayed put, cf4's slot ended 1.2 m from the DJI (inside its keep-out), so
  "not all in position after 25 s". Fix: `formation.Follow` -- slots are offsets from
  the VIP, re-placed round its live position every tick (rigid translate; rebuilt only
  when the room no longer fits it; last good goals held if nothing fits). The form-up
  now waits for the DJI to be above `vip_airborne_z` (0.3 m), and keeps following
  through the START gate; the match is built from where they are at START.
  `plan_guard` flies the same (and its VIP now drifts through the form-up too).
* **The abort 1.5-5 s after START was the containment check, not a collision risk.**
  Both runs flew 1.0 m/s (console default); aircraft lag 0.56-0.60 s, so 0.6 m behind
  the CURRENT setpoint = "not following". Fix: `track_lag_s` 1.0 (guard only; escort
  unchanged): error = distance to the nearest setpoint of the last 1.0 s. Replay of all
  14 hardware traces: old rule 11 aborts in 7 flights, new 0; worst windowed error
  0.59 m for one tick. Tests: still trips on a drone that stops or flies off.
* **Defaults:** team speeds stay 1.0 m/s -- the user wants it paced at 1.0 (19-11;
  I had briefly set 0.6, reverted). `plan_guard --tau` 0.6 (the measured lag; was
  0.25). One intent test pinned to 1.0 m/s.
* **1.0 m/s, the flown pairing (pressure, shell v coordinated) WITH the finale:**
  default VIP seed 2 -> cf2/cf12 0.19 m in the finale RALLY, 0.6 s after the match
  ended (aircraft still carrying 1 m/s of lag while the finale turns them round);
  DJI-hover VIP seeds 2/8 -> 0.33/0.31 m around the strike. Seed 42 (the console's)
  is safe at both (0.42 / 0.37 m), but a seed on hardware is not a guarantee. The
  matrix (no finale) hides this. Real fixes: Mellinger (no lag) or a lag-aware CBF.
* **Sims redone** (tau 0.6, 17-11 marks, form-up, 12 seeds, 4x4 strategies x 5 rule
  sets = 80 cells per row; unsafe = cells with any safety failure):

  | scenario | unsafe cells | min pair | pressure shell v coordinated |
  |---|---|---|---|
  | default VIP, 0.6 m/s | 5/80 | 0.33 m | 0/12 defence, safe |
  | DJI's 17-11 hover (-0.20,-2.07,1.10), 0.6 | 7/80 | 0.32 m | 0/12, safe |
  | default VIP, 1.0 m/s | 23/80 | 0.28 m | 0/12, safe |
  | DJI hover, 1.0 m/s | 24/80 | 0.27 m | 0/12, UNSAFE |
  | default VIP drifting 0.2 m/s, 0.6 | 18/80 | 0.33 m | 0/12, safe |

  The drifting-VIP failures are "an aircraft got to 0.90 of the VIP keep-out" (the
  lagging aircraft v a moving DJI), not drone-drone. Open. The DJI's FIRST hover point
  (-0.15,-1.60) puts cf4's floor mark inside its keep-out: plan_guard refuses it.
  Balance under pressure stays one-sided (as in §3.1).
* Simulator: one paced 7-drone match (domain 87) formed up, START gate followed, match
  + finale clean, 0 near misses.

## 1. Current state (as of 17-11)

**Radio problem fixed (17-11 ~17:15): the Crazyradio firmware.** One radio ran 5.1, retired by
Bitcraze for an inline-mode bug our link library exercises. Both are on 5.5 now (backups and
notes in `~/crazyradio_firmware/`); link numbers back to 11-06 and several matches flew
cleanly. Full story: [docs/details/radio-link-2026-11-17.md](docs/details/radio-link-2026-11-17.md).

**Form-up, new and the default (17-11 ~17:55):** `guard/formation.py`. Before START (after
the DJI gate) every drone flies, through the safety layer, to a formation built round the
VIP's live position: defenders on a 1.8 m ring, attackers up to 4.4 m out on their own side,
minimum-travel slot assignment, rotated up to +/-90 deg to fit the room; the match is then
rebuilt from the formation. `guard_show -p form_up:=false` / `plan_guard --no-form-up` = old.
With it on, the start-reach rule applies to the formation, not the floor marks.
Verified: 93 tests pass; `plan_guard` SAFE on every seed (today's marks, pressure, 0.6 m/s);
one simulator match (domain 88) formed up, "in position", 0 near misses. NOT yet flown.

**Balance is still one-sided on the real marks** (planner, 0.6 m/s): pressure, every defence
v coordinated/direct/wolfpack 0/12, with or without form-up and with every single pressure
parameter nudged (strike_time 2.0, down_time 1.6, reach 1.0, strike_radius 1.3, drain 1.0);
tag goes the other way (defence 12/12). On the planner's own default layout pressure is
roughly even (shell v coordinated 5/12 at 0.6, 8/12 at 1.0), and the form-up uses that same
geometry, so the remaining gap is NOT the start: likely the VIP point / room shape near the
real attack side. Open question for next session (see §3).

**Safety:** at 1.0 m/s `plan_guard` FAILS on today's marks (closest pair 0.21 m, 4 seeds).
Several 17-11 runs after 17:31 flew at 1.0. Fly 0.6 (both speed fields).

**Uncommitted changes on branch `big-arena`** (review, then commit or drop):

| File | Change |
|---|---|
| `src/crazyswarm2/crazyflie/config/crazyflies.yaml` | `initial_position` synced from `/poses` (attackers moved for the cameras on the pods; defenders pulled in) |
| `src/motion_capture_tracking/.../motion_capture_tracking_node.cpp`, `patches/0006-node-max-rate.patch`, `VENDORED.md`, `crazyflie/config/motion_capture.yaml` | `/poses` capped at 55 Hz (`max_rate`), steps down only |
| `docs/details/mocap.md` | the limiter, and why the Starlings keep Motive at 240 Hz |
| `src/crazyswarm2/crazyflie_shows/crazyflie_shows/guard/formation.py` | NEW: the form-up |
| `.../guard_show.py`, `.../plan_guard.py` | form-up wired in (default on), `mark_problems(reach=...)` |
| `docs/guard/run.md` | one paragraph on the form-up |
| `docs/details/radio-link-2026-11-17.md`, `docs/details/README.md`, `claude_handoff.md` | the session write-up, its index row, this file |

## 2. Waiting on people

1. **Fly the form-up** on hardware at 0.6 m/s (now the default): ARM, DJI gate, move the
   DJI and watch the formation follow it, START. Confirm no containment abort at START.
2. **Commit or drop** the changes in §1.
3. **Batteries**: six of seven read 3.72-3.80 V at the 16:54 preflight.
4. **Reboot** still worthwhile: 57 abandoned Fast DDS shared-memory files sat in `/dev/shm`
   (stops use SIGKILL); applies the static Motive-LAN address too.

## 3. Next steps for the next session

1. **Why the defence loses on the real layout** when it is even on the default one. Run
   `plan_guard --vip <the DJI's real hover point>` and with the default VIP, and compare the
   formation each builds (print the goals); check whether the attack side the attackers
   stand on (towards the room's corner/step) gives them a short, protected approach.
   Then strategy work: under pressure, shell sends defenders one-on-one (each gets
   outnumbered: 3 downs per match); a "wingman" defence that keeps pairs may be the fix.
2. Make it more dynamic: test a moving DJI offline (`plan_guard --vip-move 0.2`); the
   defence already re-forms round the live VIP every tick.
3. The 11-06 lag (~0.56 s, PID ignores velocity feed-forward) caps speed at 0.6;
   Mellinger (`-p controller:=mellinger`) is the proposed fix, hover-test first.

Background that holds across sessions lives in the memory files (guard show, mocap rate
limiter); the AirStack training project keeps its own handoff at
`~/AirStack-starling-max2/svg_training/docs/claude/HANDOFF.md`, untouched here.
