# Guard: the modules

How the guard show is put together: what each module does, what it may and may not
do, and how one tick flows through them. For why things are the way they are (the
measurements, the balance, the lessons), read
[guard-design-notes.md](guard-design-notes.md). To run it, read
[../guard/run.md](../guard/run.md).

All the code is under `src/crazyswarm2/crazyflie_shows/crazyflie_shows/`.

## One tick

Every 50 ms (20 Hz), in this order:

1. **Observe.** The engine takes every drone's position from mocap, or from its
   setpoint in the simulator, and estimates its velocity from those positions.
2. **Two private views.** It builds a separate copy of the world for each team. Your
   own drones carry what you commanded; the other team's carry only what a camera
   could see.
3. **Ask both strategies.** Each returns a velocity request for its own active
   drones. Neither sees the other's requests.
4. **Cap the requests** at the team's speed and the acceleration limit.
5. **One joint safety solve.** The safety layer makes the smallest change to *all*
   requests together so that no pair gets too close, nobody enters the VIP's
   keep-out, and everyone stays inside the room and the height band.
6. **Integrate into setpoints.** These go out over the radio, or to the simulated
   drones in `plan_guard`.
7. **Referee.** It judges the *aircraft* positions: tags, strikes, the clock.
8. **Retire.** Tagged and striking drones are handed to the landing commander and
   become obstacles for everyone else until they are down.

## 1. `guard/world.py`: what a strategy may know

- **`Agent`:** name, team, observed position, velocity, status and outcome.
  - Velocity, for your own team, is what you commanded. For an opponent, it is
    estimated from its observed positions, never its command.
  - Status is active or retiring. Outcome is downed or struck.
- **`View`:** the time, the VIP's position and velocity, every agent, the arena, the
  config (limits and rules), and the public events so far.
- **`Arena`:** clearance to the edge, which way is inward, and room above and below.

Nothing in a View is live: every one is a copy made for one team for one tick.

## 2. `guard/policies/`: the strategies

Each team's brain, swappable by name.

- **Contract:**
  - `act(view)` returns a velocity per active drone of your own team.
  - `reset(view, rng)` is called once, with your team's own random stream.
  - `DEFAULTS` lists your tunables. Passing a misspelled one is an error, not a
    silent default.
  - `labels` holds a word per drone, shown in logs and RViz.
- **Plugging in:** decorate the class with `@register`, then choose it by name
  (`-p defense:=...`, `-p attack:=...`). To use a strategy without editing the
  package, put it in any importable module and pass `-p policy_module:=...` (show)
  or `--policy-module` (planner). The template is in `policies/__init__.py`.
- **What a strategy cannot do:**
  - command the other team;
  - exceed its speed or acceleration limits;
  - get past the safety layer.

  A buggy strategy costs matches, not drones.
- **`common.py`** holds shared helpers: a braking-law `seek`, a smooth minimum,
  assignment, and room and band projections.

Built in:

| Name | Team | What it does |
|---|---|---|
| `shell` | defence (default) | Urgency-weighted 3D intercepts, pincers when outnumbering, idle posts above, below and around the VIP |
| `ring` | defence (baseline) | The escort's idea: a flat ring that turns to face the nearest threat |
| `coordinated` | attack (default) | A team play (stage, commit together or behind a decoy, regroup), with each attacker planning 3D options scored by STL-style robustness, plus feints and evasion |
| `direct` | attack (baseline) | Straight at the VIP, all at once |

## 3. `guard/safety_layer.py` + `cbf.py`: what the drones are allowed to do

- **`cbf.py`** is AirStack's CBF solver, copied byte for byte. A test checks its hash
  against upstream. It is never edited here: change it in AirStack and re-copy. It
  is the bridge for flying Crazyflies under AirStack later.
- **`safety_layer.py`** builds the constraints the solver enforces:
  - **every pair of aircraft:** an ellipsoidal keep-out, taller than it is wide,
    because a drone in another's downwash loses thrust;
  - **the VIP and drones being landed:** fixed obstacles, so only the active
    Crazyflies dodge;
  - **the room:** one constraint per nearby wall edge, plus the floor and the
    ceiling.
- **The backstop:** a clamp after integration catches a solve that failed, and
  counts every firing. It has never fired.

It knows nothing about strategies or rules, and nothing above it can turn it off.

## 4. `guard/rules.py`: the referee

One fixed rule set today:
- A defender in tag range of an attacker for long enough downs it.
- An attacker close to the VIP for long enough strikes.
- The attack wins on `strikes_to_win` strikes.
- The defence wins by downing every attacker or holding until the clock runs out.

`tagging:=false` turns tags off and leaves only the clock. The referee judges
aircraft positions, never setpoints, and never knows which strategies are playing.

## 5. `guard/engine.py`: one tick

Runs the eight steps above, in that fixed order, and keeps the safety statistics:
corrections, emergencies, unconverged solves and backstop firings. It also enforces
the boundary between the teams: private copies, opponents observed not asked, and
separate random streams. It is pure Python, and identical offline and on drones.

## 6. `guard/config.py`: the shared contract

Everything both strategies are held to:
- the room and the height band;
- speed and acceleration limits;
- the separation floor and the safety layer's keep-outs;
- the watchdogs;
- the rule numbers.

`problems()` refuses an inconsistent set, for example a tag range inside the
keep-out (nobody could ever be tagged), or a separation floor below anything with
flight evidence. Field names match the escort's config, so the containment check
and the room helpers are shared, not copied.

## 7. `guard/viz.py`: the RViz picture

It draws:
- the room outline;
- the VIP with its keep-out and strike sphere;
- drones coloured by team, grey once out of play, with their keep-outs, trails and
  behaviour labels;
- a scoreboard.

Publishing is best effort: a failed marker costs a picture, never a flight. Open it
with `rviz2 -d <share>/crazyflie_shows/data/guard.rviz`.

## 8. The programs

- **`plan_guard`** (offline, no drones): whole matches against simulated drones
  over many seeds, and a **safety verdict** that is the gate before flying. It also
  has:
  - `--matrix`: every defence against every attack;
  - `--rviz`: live replay in RViz;
  - `--marks`: where to stand the drones;
  - `--list`: the strategies.
- **`guard_show`** (the flight): preflight, arming, takeoff, the lift to start
  height, then the engine on live mocap at 20 Hz. It lands drones as they are tagged
  or strike, and an abort lands everything. Its watchdogs cover:
  - **VIP pose lost:** hold, then land;
  - **each drone:** stale mocap, outside the room, or not following its setpoint
    (the escort's check, shared);
  - **near miss:** two *measured* aircraft inside the near-miss fraction of the
    floor.

## Next: rules as a module

Rules will become pluggable like strategies:
- **`rules/` with a registry:** `tag` (today), `timer`, `pressure` and `zone`.
  - **`pressure`:** a graded local-majority counter. It applies to both teams, so
    defenders can be downed too.
  - **`zone`:** home ground, as in capture the flag.
- **The referee and strategies share one definition.** Each rule set states its win
  conditions as STL-style formulas. The referee checks them true or false; strategies
  plan with the same formulas' robustness, a score of how close each one is to
  coming true.
- **The matrix grows a dimension:** `plan_guard --matrix` compares defence × attack
  × rules.

The safety layer stays underneath, untouched by any rule set.
