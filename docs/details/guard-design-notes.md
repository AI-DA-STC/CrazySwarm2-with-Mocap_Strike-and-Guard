# Guard: design notes

N defenders against M attackers around a VIP, with the strategies plugged in by
name. It was built 2026-11-03 for the big arena as the successor *experiment* to the
escort. The escort stays as it is: it is the demo flown for guests. The beginner
guide is [../guard/run.md](../guard/run.md); every module is described in
[guard-modules.md](guard-modules.md).

**Status: offline and simulator only. Not flown on hardware.**

## The four layers

| Layer | File | What it decides |
|---|---|---|
| Strategies | `crazyflie_shows/guard/policies/` | what each team *wants*: a velocity per drone |
| Safety layer | `crazyflie_shows/guard/safety_layer.py` + `crazyflie_shows/cbf.py` | what the drones are *allowed* to do |
| Referee | `crazyflie_shows/guard/rules.py` | strikes, tags, the clock, who won |
| Engine | `crazyflie_shows/guard/engine.py` | one tick of all three, in a fixed order |

`plan_guard` drives the engine against simulated aircraft; `guard_show` drives it on
drones. They run the same code, so what passes offline is what flies.

One tick: build the View (positions from mocap where fresh, else setpoints); ask both
strategies; cap each request at its team speed and the acceleration limit; **project
every request at once onto the safe set**; integrate into setpoints; the referee
judges the aircraft positions; tagged and striking attackers start landing.

## The safety layer (the CBF, from AirStack)

`crazyflie_shows/cbf.py` is AirStack's `svg_ground_control/cbf_filter.py`, copied
**byte for byte** between BEGIN/END markers. `test/test_cbf.py` holds AirStack's
own tests plus one that re-hashes the block against the upstream sha256. It is the
bridge to flying Crazyflies under AirStack later, so it is never edited here: change
it upstream and re-copy.

What is ours is the constraint set handed to its solver
(`solve_safe_commands`), in its own `PairwiseConstraints` shape:

- **Aircraft pairs: a velocity CBF on an ellipsoid.** It is taller than it is wide
  (`cc_z_ratio` 1.5), because a Crazyflie in another's downwash loses thrust.
  `h = (dx²+dy²)/a² + dz²/c² − 1`, and `ḣ + αh ≥ 0` stays linear in the velocities.
  AirStack's sphere is the case `a = c`.
- **The VIP is a fixed row at its measured velocity,** so only the Crazyflies dodge.
  This is AirStack's treatment of an RC-flown intruder. Its ellipsoid is larger
  (`d_vip`, `vip_z_ratio`).
- **Landing drones are fixed rows too,** descending at `land_speed`.
- **Walls, floor and ceiling are constraints against phantom fixed rows** at zero
  velocity. The solver only knows pairs, and a pair with a motionless phantom is a
  one-drone half-space. There is **one row per polygon edge within reach**, using the
  distance to the edge *segment*. A single nearest-edge row let a drone sliding
  along one wall pass straight through the next one at a convex corner (found by
  `test_walls_hold_a_drone_inside_the_room`). Using segments keeps the step's inward
  corner from trimming the room. The rows hold `wall_margin` (5 cm) inside, so
  integrating at 20 Hz cannot creep past the edge.
- **The backstop clamp after integration never fires** in any run so far. Every
  firing is counted, and `plan_guard` treats one as a safety failure.

**Separation is the guard's own, relaxed 2026-11-03.** It does not use
`arena.yaml`'s 0.80 m floor, which every other show keeps. The STL game is designed
to 0.20 m between drones at one cruise height (stl-design-notes.md: "closest
approach 0.18-0.20 m"), and side by side at one height is the regime that is fine.
One drone over another is a different hazard: downwash. So the floor is an
ellipsoid:
- `min_separation` 0.35 m across;
- `min_separation_z` 0.62 m vertically (`escort.DOWNWASH_DZ`, the measured downwash
  threshold).

`config.problems` refuses anything under 0.20 m across: nothing here has evidence
for closer.

**The CBF holds the setpoints apart, not the aircraft.** It runs on the commanded
reference, which exists in the simulator as well as on hardware. The aircraft trail
it, so the CBF's keep-out is the floor plus `TRACKING_MARGIN`: `d_cc` 0.45 m across,
and `cc_z_ratio` 2.2 makes it about 1 m tall. Two checks watch the aircraft
themselves:
- `guard_show`'s near-miss watchdog lands everything if two measured drones come
  inside `near_miss_ratio` (0.7) of the floor ellipsoid: 0.25 m across, 0.43 m
  vertically.
- The escort's per-drone `contain_check` handles staleness, leaving the room, and
  not following.

This is a first-order (velocity) CBF. AirStack's docstring describes the
acceleration-level upgrade (an HOCBF) as a builder swap with the same solver. It
would remove the dependence on tracking lag, and is the obvious next step before
flying faster.

## Rules

The rules are a module of their own (`guard/rules/`), with every rule set written as
meters. [guard-modules.md](guard-modules.md) describes the five built-in sets and how
to write one. They were refactored from the first fixed referee on 2026-11-03.

**The refactor changed nothing it was not meant to.** Before touching the rules I
recorded per-seed results under both old modes: 32 matches with tagging and 16
without. Afterwards, `tag` and `timer` gave the same results on all 48: winner,
match time, strikes, downs and closest pair. The strategy upgrades below came after
that check.

**One subtlety a test now pins:** a meter is a sum of 20 Hz ticks.
`22 × 0.05/1.1` comes out a hair under 1.0, so "full" is `≥ 1 − 1e-9`. Without that,
a down lands one tick late against the old seconds-based clock.

**What the strategies do with the rules** (all through the rule set's own rate
functions, so it works under any rule set):

- **`coordinated` (attack):**
  - it predicts its *own* down meter along each candidate path, from its current
    meter;
  - it evades when the rules would start filling its meter here or one step on;
  - while striking, it breaks off on its public meter;
  - where defenders can be downed, it **gangs up**: when the pack could down a
    defender without filling its own meters, the attackers converge on that defender.
- **`shell` (defence):**
  - pincers now close round the attacker itself, so two defenders count under a
    majority rule;
  - a post the rules would punish (outside home ground, or next to two attackers) is
    pulled in toward the VIP;
  - a defender whose own meter passes `bail` falls back to the shell.

**Measured 2026-11-03.** `plan_guard --matrix --rules all`, 4 v 3, 12 seeds,
relaxed 0.45 m keep-out. Each entry is defence wins out of 12, with the number of
defenders downed across all 12 matches in brackets:

| Rule set | `shell` v `coordinated` | `shell` v `direct` | `ring` v `coordinated` | `ring` v `direct` |
|---|---|---|---|---|
| `tag` | 12 | 0 | 4 | 5 |
| `zone` | 11 | 0 | 6 | 5 |
| `pressure` | 8 (13 down) | 3 (10 down) | 0 (23 down) | 0 (12 down) |
| `zone_pressure` | 1 | 3 | 0 | 0 |
| `timer` | 0 | 0 | 0 | 0 |

- Every cell was safe. The closest aircraft pair was 0.40 m against the 0.35 m floor.
- **`pressure` is the most two-sided:**
  - defenders are downed as well as attackers;
  - `ring`, which never gangs up, loses every match: the rule rewards coordination,
    which was the point;
  - its strike radius defaults to 1.6 m, not 2.4 m. A lone defender cannot down a
    lone attacker, so the strike zone has to be smaller. At 2.0 m `shell` won 4 and
    0 of 8.
- **`timer` cannot be held** at any strike radius from 1.6 to 2.4 m. Nothing downs
  an attacker, and with the relaxed 0.45 m keep-out one defender's wall is too thin.
  Pure denial needs a wider keep-out (`-p d_cc:=0.9`).
- **`zone_pressure` favours the attack.** Neither default strategy has home-ground
  tactics yet: the defence could hold a tighter perimeter, and the attack could lure
  defenders out. That is the next strategy work, not a rule fix.
- **No strategy dominates.** `shell` beats the planner under `tag` and `zone` but
  loses to the rush; `ring` the reverse; under `pressure` coordination decides.

**Earlier, with the 0.90 m keep-out and the first fixed referee:**
- A defender on the line between the VIP and an attacker was a wall: the CBF let
  nothing through, and attackers stopped at the defender's distance + `d_cc`. A strike
  radius of 1.6–2.2 m never scored against `shell`.
- At 2.4 m, `shell` against `coordinated` went from 11 of 12 to 0 of 12 between a
  1.10 s and a 1.15 s tag time. One simultaneous exchange tends to settle a match.

Run `plan_guard --matrix --rules all` for the current numbers. Do not copy them
from here.

## What a strategy may know

The platform is pointless if one team can read the other's intent, so the engine
enforces the boundary (engine.py, "What a strategy may know"):

- **Opponents are observed, never asked.** You get their mocap position (the
  setpoint in the simulator) and a velocity *estimated* from it. Their commanded
  velocity, their strategy's decision, never appears. You see your own team's
  commands.
- **Each team gets a private copy of everything, every tick:** the View, the
  agents, the config and the arena. Changing them changes nothing outside.
- **Each team has its own random stream.**
- **Both decide on the same tick's observations.**

`test_guard.py` checks this with a spy, a vandal and a dice test. Before this was
enforced, opponents' velocities were their commands and both teams shared one
random stream.

## Strategies

A strategy is a class with `team`, `name`, `DEFAULTS` and `act(view)`.
`act(view)` returns a velocity request per active drone of its own team. The engine
ignores requests for the other team's drones (`test_a_strategy_cannot_steer_the_other_team`).
A strategy can be naive or buggy and still not crash anything, because the safety
layer gets the last word. That is the point of the split.

To plug one in without editing the package, put it in any importable module and
pass `-p policy_module:=my_lab.strategies` (show) or `--policy-module` (planner).
The template is in the docstring of `guard/policies/__init__.py`.

Built in:

- **`shell` (defence, default).** Ideas from the STL game; its code is untouched.
  - An urgency-weighted assignment of defenders to threats, kept sticky.
  - A *predictive* intercept on the 3D line from the VIP to where the attacker is
    going. It meets an over-the-top or floor-level attack at its own height.
  - Pincers when defenders outnumber threats.
  - Idle posts above, below and around the VIP.
- **`ring` (defence, baseline).** The escort's idea: a flat ring that turns to face
  the nearest threat.
- **`coordinated` (attack, default).** A team play: stage on lanes, commit together
  or behind a decoy, regroup onto rotated lanes.
  - Lanes are spread over 240°, at different heights. In the default *overload*
    formation, two attackers converge 60° apart on one side, because a lone
    defender beats a lone attacker.
  - Each attacker replans every 0.4 s over 3D candidate goals, rolled out against a
    prediction of the defenders marking it.
  - Candidates are scored by STL-style robustness: a smooth minimum (the STL game's
    `soft_min`) of the room and band margins, and a *temporal* tag margin. That is
    how long it would spend in tag range, against the rule's `tag_time`.
  - The score adds progress toward the VIP, the angle to the nearest defender, and
    the pull of its own lane.
  - It feints, and evades according to its own tag clock, kept the way the referee
    keeps it.
- **`direct` (attack, baseline).** Straight at the VIP, all at once.

Two lessons from building `coordinated`:
- **Gating the attempt on a provably open lane meant it never went at all.**
  Robustness now *chooses* the line; it does not *gate* the attempt.
- **Fleeing on the first approach of a defender made striking impossible.**

## Verification

- `test/test_guard.py` and `test/test_cbf.py`: 46 tests. Run them with
  `PYTHONPATH=src/crazyswarm2/crazyflie_shows python3 -m pytest -q src/crazyswarm2/crazyflie_shows/test`.
- **`plan_guard`'s safety verdict covers every seed.** It fails if any of these
  happen:
  - two airborne aircraft get inside the hard floor ellipsoid, or one gets inside
    the VIP's keep-out;
  - a drone goes outside the room or the band;
  - a solver emergency, or the backstop fires.
- **Simulated aircraft:** a first-order lag (τ = 0.25 s) behind the setpoint. It is
  a stand-in, not a measured model.
- **Measured:** closest aircraft pair 0.45 m at the defaults, and never closer than
  1.29× the floor ellipsoid. Zero emergencies, zero backstop firings.
- **Speed:** an engine tick takes 3 ms mean and 17 ms at worst for 4 v 3, and 27 ms
  at worst for 6 v 6, against the 50 ms budget at 20 Hz. The spikes are the
  attackers' replans.

## Gates and pauses

With `paced:=true` the show waits for Enter (or the console's Continue) at:
1. **ARM and take off.**
2. **PILOT: take off the DJI** (`vip_mode:=mocap` only). The DJI goes up *into* a
   volume whose drones are already dodging it: first in.
3. **START the match.**
4. **At the end:** with a DJI, **PILOT: land the DJI**, before the drones come down
   (last out); otherwise **LAND the drones?**

A match has no legs, so there are no gates inside it, unlike the escort's per-leg
Continue.

**While a gate waits, or the match pauses** (a lost VIP pose, a drone on hold), the
engine's `hold()` runs:
- every drone holds where it is **through the safety layer**, so it still dodges
  the DJI and keeps its spacing;
- every watchdog keeps running;
- the strategies are not asked and the match clock stops.

The first version only re-sent the last setpoint during a gate. A DJI climbing past
the drones would then have had nothing getting out of its way
(`test_a_held_drone_still_dodges_the_dji`).

The mission console's window is `missions/guard.yaml`: every choice above, the gates
as buttons, indicators for phase, rules, result, last down or strike and safety, a
VIP keyboard for `vip_mode:=manual`, and the 3D view with the show's markers.

## Making the match readable (2026-11-05)

The show had been flown several times on hardware (4 v 3, cf1-cf4 against
cf10-cf12). Three problems came out of those flights. First, the strategies'
intent was only partly visible. Second, most matches ended on a near-miss
landing before a winner was obvious. Third, who won lived in the console.

**Intent, not clutter.** Strategies now say what each drone means to do
(`Intent`: kind, goal, target) and what the team's play is (`plan`). The viz
draws these as an operations map. The engine hands them to the picture only,
never to the opponent. Recording them does not change play: `plan_guard` gives
the same result, match time and closest pair as before the change, on 12 seeds
of the defaults and on 8 seeds of `pressure` with a drifting VIP.

What was removed:
- the body sphere on each drone (it sat on top of the real drone);
- the always-on keep-out ellipsoids, now shown only while the CBF is changing that
  drone's command;
- the translucent strike and keep-out spheres round the VIP, now two circles.

**Near misses: graded, glitch-filtered, explained.** The old watch landed
everything when two measured drones were inside 0.7 of the floor ellipsoid on
a single frame. Two things made that end matches it did not need to end:
- One frame is enough for a mocap glitch to count. A swapped or ghost rigid
  body puts a drone on top of another for a frame or two.
- Landing does not separate a close pair. Holding does: the CBF already keeps the
  *setpoints* `d_cc` apart, so held aircraft settle back apart.

So now (guard/watch.py):
- A pose that jumps further than a Crazyflie can fly is a glitch. The drone flies
  on its setpoint for that tick, and the glitch is counted.
- A soft near miss on two ticks in a row pauses the match.
- Inside 0.55 of the floor (0.19 m across, 0.34 m vertically), or a pause that
  does not clear in 3 s, everything lands.
- `near_miss_pause:=false` restores the old rule.

**Why the near misses happened is not known yet.** No output from those flights
was kept. The stand-in aircraft in `plan_guard` (first-order lag, 0.25 s) never
comes inside the floor, so the cause is something it does not model: real
tracking, mocap glitches, or both. Every near miss now prints the setpoint gap
and each drone's tracking error at that tick. Each run writes a trace to
its flight folder (`guard_trace.csv`, next to the bag the console records: [flight-logs.md](flight-logs.md)). The next hardware session should answer it.

**The finale (guard/finale.py)** makes the result visible on the drones:
- losers dark, low, home, landed;
- winners green, in an honour guard (defence) or a capture ring (attack);
- the attacker that struck stays up for the capture.

It flies through `Match.steer`, so the CBF is under it, and `plan_guard` checks it
on every seed. Measured on 8 seeds each, all reached the end of the finale:
4 v 3 under `tag`, `timer` and `pressure`; 2 v 1; 5 v 5 `zone_pressure`; tau 0.4.

The first version landed the losers at their marks wherever the VIP was. With a
drifting VIP that was unsafe: down to 0.50 of the VIP keep-out at 0.5 m/s. A drone
being landed is a fixed obstacle that cannot dodge, and nothing stops a hand-flown
DJI. Losers now land only `land_clear` (0.8 m) beyond the keep-out. The capture
ring is at 1.8 ± 0.12 m.

**A moving DJI: what `plan_guard --vip-move` says** (8 seeds, VIP on a 0.6 m
circle; the worst figure is the closest any aircraft came, as a fraction of the
VIP keep-out):

| Rules | Drift | Worst | Verdict |
|---|---|---|---|
| `tag` | 0.1 to 0.5 m/s | 0.98 to 0.94 | SAFE |
| `timer`, finale on | 0.3 m/s | 0.95 | SAFE |
| `timer`, finale on | 0.5 m/s | 0.88 (1 seed) | FAILED: the winning striker rallying from the keep-out's edge, aircraft lag |
| `pressure` | 0.1 m/s | 0.98 | SAFE |
| `pressure` | 0.2 to 0.5 m/s | 0.85 to 0.66 | FAILED |

The `pressure` failures **predate this change**. They are downed *defenders*
being landed straight down near the VIP while it drifts onto them. This is the same
mechanism the finale fix removes. Widening `d_vip` does not help (tried 1.35).

The fix is to have a downed drone move clear of the VIP through the CBF before it
is landed. That changes the match: the drone stays an obstacle for longer, and the
balance shifts. It is not done yet. Until it is, fly the DJI under `tag` (only
attackers are downed, out where defenders meet them), and keep the DJI slow
(≤ 0.3 m/s) during the match and the finale.

**LEDs.** The cues are now:
- out of play: dark (amber read as red across the room);
- scoring: white (a defender tagging, an attacker in the strike zone);
- decoy: magenta;
- finale: winners green.

Each cue is sent only on a change, at most every 0.25 s per drone. None of it has
been seen on hardware yet. Magenta against red is the one most likely to be hard to
tell apart.

## The first hardware matches (2026-11-06)

Seven Crazyflies (cf1-cf4 defend, cf10-cf12 attack), the DJI as the VIP (rigid body
`dji`), `pressure` rules, paced from the console. Every run has a flight folder
([flight-logs.md](flight-logs.md)); that is where all the numbers below come from.

| Run | Ended | Why |
|---|---|---|
| 14:53 | abort at the START gate | `CONTAINMENT cf1: no mocap for 1.1 s`, and the console never showed the START card |
| 15:09 | abort in the match | `cf10: 0.64 m from where it was commanded for 0.9 s` |
| 15:13 | **attack won** | cf10 downed cf4 and cf3, then struck; capture finale |
| 15:19 | operator landed | batteries 3.72-3.87 V at the start |
| 15:27 | **defence won** | three downs in 12.4 s; honour-guard finale |

Four causes were found and three fixed.

**1. Every drone trails its setpoint by ~0.56 s (not fixed: needs a hover test).**
Every drone, every run, followed its commanded path to within 3-5 cm, but 0.54-0.60 s
late. So at 1 m/s it sat 0.5-0.7 m behind its setpoint. The firmware's PID position
controller (`stabilizer.controller` 1, which the server sets) overwrites the
setpoint velocity in `modeAbs` (`position_controller_pid.c`, the `runPid` branch), so
`cmd_full_state`'s velocity feed-forward is thrown away and the drone moves only in
proportion to its position error.

Consequences:
- The CBF's `TRACKING_MARGIN` (0.10 m) and `plan_guard`'s default stand-in lag
  (0.25 s) are both optimistic for hardware.
- The 15:09 abort was this lag.
- Both completed runs had a closest pair at the 0.35 m floor, with the setpoints
  further apart.
- The simulator never showed it: `server.yaml` runs the SIL drones on Mellinger.

`plan_guard --tau 0.6` is the honest check:
- At 1 m/s, 89 of 128 pairing/rule/fleet cells are safe.
- At 0.6 m/s, 113 of 128 are.
- Widening `d_cc` to 0.60 m moved the problem into solver emergencies (111 of 128).

The fix to try is `-p controller:=mellinger` (full-state tracking), on one hovering
drone first. Until then fly 0.6 m/s.

**2. `/poses` went stale inside the show (fixed).**
- `crazyflie_py` subscribes every drone's `/cfN/pose` (10 Hz) and `/cfN/status` on the
  show's node: about 127 messages/s with 7 drones.
- The show ran one `spin_once` per tick, and a paced gate sits 50 ms in `select()`
  between ticks.
- Reproduced off the drones at the same rates: `/poses` was 0.3-0.4 s old on average
  and up to 0.9 s.
- A real 0.34 s mocap stall on top of that crossed the 1.0 s watchdog: the 14:53 abort.
- `drain()` now runs up to `drain_count()` callbacks per tick (14 with 7 drones);
  `/poses` is then 0-5 ms old.
- The escort had the same pattern and now uses the same helper.

**3. The console lost a gate (fixed).** Answering a gate cleared "whatever gate is open"
after the POST returned. When the show printed the next gate in the same millisecond
(PILOT -> START), that was the new one. The window now clears only the gate it
answered.

**4. The console's 3D view lagged (fixed).**
- Drawing every 20 Hz marker message, it fell 0.7 s/s behind: 3.3 s late by the end of
  the 15:27 match.
- Then it replayed 4 s of match in 2. That was the "accelerated" attacker rush on the
  screen recording; mocap shows the drones flew normally.
- Now the show publishes at 10 Hz and the window draws only the newest snapshot per
  frame.

Also seen: the whole `/poses` stream froze for 0.2-0.55 s every 10-40 s, and the server
saw it too. It is under the 1.0 s watchdog, and the cause is not known yet (network, or
laptop load).

## More strategies (2026-11-06)

`zone` and `hunter` (defence), `flood` and `wolfpack` (attack); what each does is in
[guard-modules.md](guard-modules.md). They were designed to be different ideas, not
parameter variants, and checked offline on every pairing with all eight strategies.

**Safety** (`plan_guard`, 12 seeds per cell; `tag` and `pressure`; 4 v 3, 2 v 1, 5 v 5
and the real roster: 128 cells):

| Stand-in lag | Speed | Safe cells | Failures |
|---|---|---|---|
| 0.25 s | 1.0 m/s | 127/128 | shell v coordinated, `pressure`, roster: 2 seeds of solver emergency (existing strategies only) |
| 0.6 s | 1.0 m/s | 89/128 | every strategy, old and new (hunter and flood 14 cells each, shell and coordinated 10) |
| 0.6 s | 0.6 m/s | 113/128 | hunter 8 (all `pressure`, 0.85-1.00 of the floor), flood 3, shell/ring 6 |

The 0.6 s failures are cause 1 above, not the strategies. `hunter` is the most sensitive
to it: its flanking pair closes on one attacker from both sides.

**Balance** (defence wins of 12, 4 v 3, stand-in lag 0.25 s; † = mostly ran the
clock out):

| Rules | Defence | v coordinated | v direct | v flood | v wolfpack |
|---|---|---|---|---|---|
| `tag` | shell | 12 | 0 | 12 | 0 |
| `tag` | ring | 4 | 5 | 0 | 0 |
| `tag` | zone | **6** | 0 | 12 | 0 |
| `tag` | hunter | 12 | 12 | 12 | 12 |
| `pressure` | shell | **8** | 3 | 2 | **6** |
| `pressure` | ring | 0 | 0 | 0 | 0 |
| `pressure` | zone | 0 | 0 | 2 | 0 |
| `pressure` | hunter | 0 | 12† | 1 | 2 |

Even pairings for a demo:
- zone v coordinated under `tag`: 6/12, and 9/12 from the real roster.
- shell v wolfpack under `pressure`: 6/12, and 8/12 from the roster.
- shell v coordinated under `pressure`: 8/12, but 0/12 from the roster.

Lopsided pairings:
- `hunter` wins every `tag` match.
- `zone` loses to overloads under `pressure`.
- `hunter` v `direct` under `pressure` is a clock-out standoff.

**Simulator** (the SIL simulator, 4 v 3 on the real roster, a fresh launch each, all
completed with no CBF emergency, backstop or near miss): zone v coordinated (`tag`,
attack won), shell v wolfpack (`pressure`, defence 3 downs), hunter v flood (`pressure`,
defence), hunter v wolfpack (`pressure`, attack struck at 6.9 s), zone v flood (`tag`,
defence).

## The simulator is fast enough to use now (2026-11-06)

The SIL simulator ran at 0.06x real time with 7 drones, so a 4 v 3 match with finale
took about 5 minutes. It is one Python thread, and the time went on per-call overhead,
not physics. Each step still runs, at the same 0.5 ms:
- the rigid-body step is in plain floats instead of numpy/rowan on 3-vectors;
- roll/pitch/yaw are in closed form;
- the setpoint is converted to a State only when the `none` backend or the `pdf`
  visualization reads it;
- `/clock` is published at 500 Hz and the RViz TF at 100 Hz;
- ten physics steps run per timer callback.

Each replacement was checked against the original to 1e-13 or better.

The result is 0.76x even under load, and it is now paced to exactly 1.00x at half a core
(`sim.realtime`, default true; `false` runs it flat out, about 18 s of wall time per
match with finale).



**Proven in the simulator** (which has no mocap, so poses come from setpoints):
- the full flight path;
- a paced run with every gate answered through stdin, as the console does;
- one SIGINT mid-match landing all seven drones (exit 130);
- downs landing drones one at a time.

**Not exercised until hardware:**
- **Every check that reads real `/poses`:** the per-drone containment watchdog, the
  near-miss check on measured aircraft, the placement check, and opponents'
  velocities estimated from real mocap. The escort's first flight was the first test
  of its equivalents too.
- **Close flying.** The STL game is designed to 0.20 m, but `stl_show` has no
  hardware flight recorded in this repo.
- **Streaming load.** Seven drones on `cmd_full_state` at 20 Hz: the escort streamed
  four, and the STL game uses the high-level commander. Expect two Crazyradios
  (roster URIs `radio://0/…`, `radio://1/…`).
- **The DJI gates.** They need a mocap VIP.
- **LED cues.** They are off in the simulator.

**A ladder for the first session.** Run `plan_guard` with the same choices before
each step, and a dry run (`-p dry_run:=true`) before the first:

| Step | Teams | Settings |
|---|---|---|
| 1 | 1 v 1 | point VIP, `rules:=tag`, `v_max_defense`/`v_max_attack` 0.5, `min_separation` 0.6, `d_cc` 0.7, paced |
| 2 | 2 v 1 | the same; then `rules:=pressure`, so a defender can be downed |
| 3 | 4 v 3 | 0.8 m/s; then narrow the separation in steps, watching the closest pair the show prints at the end |
| 4 | with the DJI | `vip_mode:=mocap`, paced, all gates |

Before going faster than 1 m/s, build the acceleration-level CBF (HOCBF).
