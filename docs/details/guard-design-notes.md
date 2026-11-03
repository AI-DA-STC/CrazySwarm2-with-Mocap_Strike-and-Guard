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

## Before the first hardware flight

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
