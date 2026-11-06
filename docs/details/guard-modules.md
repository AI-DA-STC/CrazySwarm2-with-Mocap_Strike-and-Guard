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
7. **Referee.** It fills and drains every drone's meters from the *aircraft*
   positions, using the rule set in play, and declares downs, strikes and the result.
8. **Retire.** Tagged and striking drones are handed to the landing commander and
   become obstacles for everyone else until they are down.

   Under rule sets that can down defenders, downed defenders are landed the same
   way.

## 1. `guard/world.py`: what a strategy may know

- **`Agent`:** name, team, observed position, velocity, status and outcome.
  - Velocity, for your own team, is what you commanded. For an opponent, it is
    estimated from its observed positions, never its command.
  - Status is active or retiring. Outcome is downed or struck.
- **`View`:** the time, the VIP's position and velocity, every agent, the arena, the
  config (limits and safety), the rule set in play, everybody's meters, and the public
  events so far.
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
  - `intents` (optional) holds an `Intent(kind, goal, target)` per drone: what move
    it is making, where it is heading and which opponent it is about. `plan`
    (optional) holds the team's play (`phase`, `lanes`, `decoy`). Both are for the
    picture and the LEDs only. The engine passes them to the viz in the `Tick`,
    never to the other strategy. `DEFENSE_KINDS` / `ATTACK_KINDS` in
    `policies/__init__.py` list the kinds the viz has symbols for.
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
| `zone` | defence | Each defender owns a sector (and height layer) of the VIP's sky that turns toward the attack; engages only inside it, helps a neighbour only where the rules say a 2 v 1 downs the attacker |
| `hunter` | defence | A pair flanks one attacker out at range (only a target the rules say two hunters down, from spots where neither is outnumbered); the rest guard close. Everyone guards under `timer` |
| `ring` | defence (baseline) | The escort's idea: a flat ring that turns to face the nearest threat |
| `coordinated` | attack (default) | A team play (stage, commit together or behind a decoy, regroup), with each attacker planning 3D options scored by STL-style robustness, plus feints and evasion |
| `flood` | attack | Spread to evenly spaced bearings, then all charge at once with a sideways weave; regroup from the gaps when all stall |
| `wolfpack` | attack | Gang 2 v 1 on the loneliest defender first (never where a wolf is outnumbered), strike from spread lanes once the defence is halved; straight to the strike where defenders cannot be downed |
| `direct` | attack (baseline) | Straight at the VIP, all at once |

Every built-in sets `labels`, `intents` and (where it has a team phase) `plan`.
Tests: `test/test_guard_strategies.py` (registration, an intent per active drone,
only its own team commanded, deterministic per seed, a short safe match each).

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

## 4. `guard/rules/`: the rules and the referee

Rule sets plug in by name like strategies (`-p rules:=...`, `--rules`), and
`plan_guard --list` names them.

**Everything is a meter.** Each drone has a *down* meter, and each attacker a
*strike* meter, running from 0 to 1. A full meter is an event: the drone is downed
and lands, or the attacker strikes, scores and lands. A rule set says only three
things:
- **how fast** each meter fills given where everybody is (`down_rates`,
  `strike_rates`);
- **how fast it drains** when nothing fills it (`drain`): instantly for a plain
  clock, slowly for a counter;
- **who has won** (`result`): the attack on `strikes_to_win` strikes or when no
  defender is left; the defence when no attacker is left or the clock
  (`duration`) runs out.

Built in. An attacker strikes in all of them by holding inside `strike_radius` of
the VIP for `strike_time`.

| Name | Who can be downed | How the down meter fills |
|---|---|---|
| `tag` (default) | attackers | while any defender is in reach; resets the moment none is |
| `timer` | nobody | never: the defence can only deny |
| `pressure` | both teams | at (opponents in reach − teammates in reach − 1) per `down_time`, never below 0; drains slowly otherwise |
| `zone` | both teams | like `tag`, but only on the other team's ground: attackers inside `home` of the VIP, defenders outside it |
| `zone_pressure` | both teams | like `pressure`, on the other team's ground |

`pressure` is the graded local majority:
- 1 v 1 and 2 v 2 are standoffs, so there are no mutual kills;
- a drone outnumbered two to one falls in `down_time`, and three to one twice as fast;
- an escaped drone is still weakened while its meter drains.

**One definition, two uses.** The **referee** integrates the meters from the
aircraft positions to decide what happened. **Strategies** get the same rule
object in their View, plus everybody's current meters (public, like a scoreboard).
They call the same rate functions on *predicted* positions while planning, so one
strategy plays under any rule set without knowing which.

**Rules never touch safety.** The safety layer sits underneath every rule set, and
each rule set's `problems()` refuses numbers that could only be met by contact: a
reach inside the keep-out, or a strike radius inside the VIP's.

To write one: subclass `Rules`, then set `name`, `DEFAULTS` and `DOWNABLE`,
implement `down_rates` (and `drain` if it is not a plain reset), and decorate it
with `@register`. The built-in sets are in `rules/standard.py`.

## 5. `guard/engine.py`: one tick

Runs the eight steps above, in that fixed order, and keeps the safety statistics:
corrections, emergencies, unconverged solves and backstop firings. It also enforces
the boundary between the teams: private copies, opponents observed not asked, and
separate random streams. It is pure Python, and identical offline and on drones.

## 6. `guard/config.py`: the shared contract

Everything both strategies are held to, under every rule set:
- the room and the height band;
- speed and acceleration limits;
- the separation floor and the safety layer's keep-outs;
- the watchdogs.

The rule numbers live with each rule set, not here.

`problems()` refuses an inconsistent set, for example a tag range inside the
keep-out, or a separation floor below anything with flight evidence. Field names match the escort's config, so the containment check
and the room helpers are shared, not copied.

## 7. `guard/viz.py`: the picture, as an operations map

The same markers go to RViz and to the console's 3D view. Its module docstring
has the full symbol table. In short:
- **Who is who:** a team-coloured halo and a label per drone. The drone itself is
  the real one (TF / `/poses`); only `plan_guard --rviz`, which has no real
  drones, adds a body sphere (`GuardViz(bodies=True)`).
- **What each drone means to do:** its `Intent` as a symbol: a block's screen
  bar, a pincer's hook, a staging circle, a strike arrow, and so on. A dotted
  line runs to the opponent it is about.
- **The attack's plan:** its lanes as axes of advance, and the phase on the
  scoreboard (`attack COMMITTED behind decoy cf11`).
- **The safety layer at work:** a drone's keep-out shows only on the ticks the
  CBF changed its command (`Match.corrected`).
- **Events and result:** a ring bursts where a drone is downed, and at the VIP
  on a strike. The VIP turns green or red under a banner.

Markers that were drawn last tick and not this one are deleted at once, so a
changed intent never lingers. `guard_show` publishes at about 10 Hz (events between
two publishes are carried to the next), and the console's 3D view draws only the
newest snapshot per browser frame (`latestOnly` in the mission window): at 20 Hz with
every message drawn, it fell 3.3 s behind a match (2026-11-06). Publishing is best effort: a failed marker costs
a picture, never a flight.

## 7a. `guard/finale.py`: the end, made obvious

After the result, the same for every strategy and rule set:
1. **Rally.** The winners take a formation round the VIP. The losers sink to
   `floor + loser_dz`, fly home to their marks and are landed there.
2. **Emote.**
   - Defence wins: an honour guard turning with a Mexican wave.
   - Attack wins: a capture ring squeezing in and out. The attacker whose strike
     won is reinstated (`Match.reinstate`) instead of landed.
3. **Home.** The winners fly to their marks at start height and hold. A mark
   with a downed drone on it is moved aside.

Every move is `Match.steer`: requests to goals, through the same safety
layer, with no strategy, referee or match clock. Losers are handed to the
landing commander with `Match.retire`. The formation is VIP-relative, so a
moving DJI drags it along.

Lights, per drone: `win` (green), `team` (its colour), `off`. `check()`
refuses a ring inside the VIP keep-out or a speed above either team cap.
`plan_guard` flies the finale on its stand-in aircraft and checks it like the
match (`--no-finale` to skip; `--matrix` never flies it).

## 7b. `guard/watch.py`: the near-miss watch

It runs on the *measured* aircraft every tick in `guard_show`, gates included:
- **Mocap glitch:** a pose that jumps more than `mocap_jump_m` in one tick, plus
  what the drone could have flown through any missing frames. The drone is
  flown on its setpoint for two ticks, and the glitch is counted. It is not a
  near miss.
- **Soft near miss** (`near_miss_ratio` of the floor ellipsoid, for
  `near_miss_ticks` ticks in a row): the match pauses and every drone holds
  through the safety layer. Play resumes once every pair is back outside
  `near_miss_clear_ratio`.
- **Hard near miss** (`near_miss_land_ratio`), or a pause longer than
  `near_miss_pause_s`: everything lands. `near_miss_pause:=false` restores the
  old rule, where a soft near miss lands everything.

Each near miss is printed with its evidence: the measured gap, the setpoint gap
at the same tick, and each drone's tracking error. These separate "the plan put
them there" from "the aircraft lagged the plan".

## 8. The programs

- **`plan_guard`** (offline, no drones): whole matches against simulated drones
  over many seeds, and a **safety verdict** that is the gate before flying. It also
  has:
  - `--matrix`: every defence against every attack; with `--rules all`, under every
    rule set;
  - `--rviz`: live replay in RViz. With `--matrix --rules all` it rotates through
    every pairing and rule set, and shows each drone's meters (`d40%` down,
    `s40%` strike);
  - `--marks`: where to stand the drones;
  - `--list`: the strategies.
- **`guard_show`** (the flight): preflight, arming, takeoff, the lift to start
  height, then the engine on live mocap at 20 Hz. It lands drones as they are tagged
  or strike, and an abort lands everything. Its watchdogs cover:
  - **VIP pose lost:** hold, then land;
  - **each drone:** stale mocap, outside the room, or not following its setpoint
    (the escort's check, shared);
  - **near miss:** two *measured* aircraft too close: a pause, or a landing if
    much closer (7b above).

  It also drives the LEDs:
  - role lights mid-match: white while scoring, magenta for the decoy, dark when
    out of play; `role_lights:=false` turns them off;
  - the finale's lights.

  Each change is sent once, at most every 0.25 s per drone.

  `controller:=mellinger` sets `stabilizer.controller` 2 on the flying drones
  before arming and back to 1 (PID) after, landing or abort (`set_controller`,
  in a `finally`). Every tick drains the node's ready callbacks (`drain`, shared
  with the escort in `escort_show.py`), so `/poses` is never queued behind the
  drones' own pose and status topics. `trace:=true` (the
  default) writes every tick's measured and commanded position, phase and intent
  per drone to `guard_trace.csv` in the flight's folder
  ([flight-logs.md](flight-logs.md)).
