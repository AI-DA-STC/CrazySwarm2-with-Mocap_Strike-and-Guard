# Escort: design notes (what was decided, what broke, what is open)

The dated record. The ideas and the maths are in [theory.md](theory.md); every setting,
command and number is in [reference.md](reference.md).

> **Frame warning.** A Motive recalibration rotates the world frame (on 2026-10-08 by
> +91.59 degrees, [mocap.md 2c](../../rig/mocap.md#2c-the-world-frame-the-measured-arena-and-what-a-recalibration-breaks)),
> and the rig moved to the big arena on 2026-11-02. Numbers below are as of their
> date. **For any current mark, offset or radius, print it** (`plan_escort --marks`,
> `plan_escort`, the `EscortConfig` source).

Code is under `src/crazyswarm2/crazyflie_shows/`:

| File | What it is |
|---|---|
| `crazyflie_shows/escort.py` | the whole control law, pure Python, no ROS |
| `crazyflie_shows/plan_escort.py` | offline verification: simulates the encounter and refuses bad numbers |
| `crazyflie_shows/escort_show.py` | the flight script (mocap + radio) |
| `crazyflie_shows/escort_teleop.py` | keyboard-steered virtual VIP or adversary |
| `crazyflie_shows/escort_viz.py` | RViz markers for the ring and the threat |
| `scripts/place_drones.py` | floor-placement helper for the marks |
| `scripts/watch_escort.py` | read-only run monitor |

## What the sources support, and what is ours

Backed by published work: the escort ring (circular formation around a leader that holds
while the leader moves, arXiv 2212.12554, built on Olfati-Saber), encirclement of a moving
target at a stand-off distance (IET CTA 2022), and the vertical-separation rule: downwash
from a drone above costs the one below enough thrust to matter, negligible only above
`dz/l > 19`, about 0.62 m for a Crazyflie (arXiv 2507.09463, arXiv 1704.04852).

Ours, not from any source: **using three defenders at all.** Every defender paper in the
2026-09-22 survey is one defender against one attacker, so the ring is verified by
`plan_escort` rather than backed by a citable guarantee.

Deliberately not used: the equal-spacing orbit law flown on Crazyflies under Vicon
(arXiv 2103.11574). It assumes agents much faster than the target: above ~3 m/s for a
walking person.

## What flew, and what broke (as of 2026-10-08)

Sourced from commit messages, code comments, operator cards and the maintainer's notes.
There was no flight log yet, so treat dates and outcomes as the best record, not a data set.

- **2026-10-07, hardware, DJI as the VIP.** The attacker got through: `be27585` engages
  earlier (`alert_radius` 1.88 → 2.10 m, `release_radius` 2.00 → 2.22 m). The attacker
  flew away: `bc24892` added per-drone containment (below); until then only the VIP had a
  geofence and a staleness watchdog, and `self_stale_s` was dead config. Geofence
  episodes now print wall-clock times, because matching LED changes to the video had been
  impossible.
- **2026-10-08, hardware, shown to guests.** Several runs with the reactive attacker
  (the default since); the last run was clean. That morning Motive was recalibrated
  (+91.59 degrees), which silently broke `vip_offset`, the attacker's absolute bearings and a
  private copy of the arena centre (0.41 m off; the planner still passed). Fixed in
  `f6ab833` and `c38f0ab`; the lesson is in [theory.md §11](theory.md#11-lessons-that-generalise).
- **Never measured on hardware:** a separation margin for the escort; how often a
  head-worn rigid body drops out of mocap.

## Decision log (closed)

Oldest first: what was decided, the number behind it, the outcome.

- **2026-09, the law.** The ring rotates and the drones never swap slots (slot order fixed
  at the gather, by bearing). **The blocker stays on the ring and does not pursue**: a
  pure-pursuit law is in the docstrings as the alternative, but chasing an attacker next
  to a person spends the whole separation budget to look slightly more aggressive.
- **2026-09, clamp order** (found by `plan_escort`, not by reasoning): slew, then
  separations, VIP clamp last. A single pass let the push away from the attacker put a
  defender 1.27 m from the VIP against the then 1.50 m minimum.
- **2026-09, bad poses are ignored.** A defender pose more than `ring_radius` from its own
  setpoint (stale estimate, flipped rigid body, fallback source) is not believed: the
  setpoint is used and the log says so. Acting on it made the guard shove setpoints
  around (found in sim); on hardware the same input is the fly-away case.
- **2026-09-23, first full sim run** (takeoff, gather, 40 s streamed escort with the
  script, land, disarm): clean, and it found the gather/resync bug and the arena squeeze.
- **2026-09-24, the gather is checked.** Defenders and attacker fly onto the ring together
  on straight goTo legs with no onboard avoidance, the shape of the 2026-08-04 collision.
  The legs are now checked against `safety.PLAN_SEPARATION` (0.90 m) by the closed-form
  routine of [theory.md §6](theory.md#6-defence-in-depth-the-safety-layers-in-time):
  before arming from the yaml marks, and after takeoff from live poses (a refusal lands).
  It was real: with that day's marks and the old name-order roles, cf5 outbound and cf3
  inbound closed to **0.00 m**; the defenders alone cleared 1.27 m, so the attacker must
  be in the check. `escort.adversary_start_problem` refuses an attacker that starts inside
  `ring_radius + min_adv_sep`.
- **Roles by geometry** (`escort.pick_roles`), replacing name order after that near
  collision: the three drones nearest the VIP mark defend, the farthest attacks.
- **2026-10-01, the old room measured, everything fitted down to it.** Walking cf1 through
  the volume (`scripts/measure_arena.py`, 8067 samples) and flying it
  (`scripts/arena_flight_sweep.py`): first sustained dropout at 2.24 m, 72 waypoints clean
  inside 2.00 m at 1.20 and 1.95 m altitude, worst 45-degree sector 2.15 m. The escort
  planned to `ARENA_RADIUS_PLAN` 1.90 m and `ceiling` 1.85 m. The ring shrank 1.5 →
  1.2 → 1.0 m (the last step asked for on sight: 1.2 m read as a loose circle) and the
  alert/release radii came down from 2.6/2.9 m. The smaller ring forced
  `wall_half_angle` 50 → 58 degrees: the wall chord fell to 0.85 m at 50 degrees, under the 0.90 m
  budget; 58 degrees holds 0.97 m.
- **2026-10-06, three changes, each measured** (why: [theory.md](theory.md)): the
  attacker gives way, not the defenders (`defenders_yield` False, `defender_yield_floor`
  0.70 m; §5.3); the ring rides above the DJI (`vip_height_offset` +0.30 m, was level;
  §7); no threat prediction (`threat_lead_s` 0.0; §4.2).
- **2026-10-07, containment for every drone** (`escort.contain_check`): a per-drone
  staleness watchdog, a trip when a drone's measured pose passes the arena edge by
  `contain_margin`, and a trip when it stays `track_error_m` off its own command for
  `track_error_s`. It covers the attacker and an `adversary:=external` drone too.
- **The reactive attacker is capped like a defender.** `escort_show` passes its setpoint
  through a `SetpointGuard` built from the same `EscortConfig`, so it flies at the
  defenders' `v_max` and `a_max`, not its planner's 0.80 m/s; `plan_escort` skips that
  guard and so verifies the harder attacker.
- **2026-10-12, VIP-speed sweep (old room):** `--sweep` held only 0.00 m/s against the
  reactive attacker and 0.15 m/s against the script. What bound: against the reactive
  attacker, defenders yield only inside 0.70 m while the verdict wants
  `min_adv_sep - 0.05` = 0.75 m; against the script, `min_vip_dist` equals `ring_radius`,
  so any inward lag is a violation (0.93 m from a 1.00 m floor at 0.30 m/s).
- **Old-room VIP offset (closed by the move).** A centred VIP left the attacker
  `arena_radius - (ring_radius + min_adv_sep)` of stand-off, so the arena clamp dragged it
  inside the alert radius at once (the first sim run began blocked). The VIP therefore
  sat off-centre toward the operator, at the price of a lopsided pilot box.
- **2026-11-03, the big arena.** The usable floor is the polygon in `arena.yaml`, about
  twice the area of the largest circle that fits in it.
  - One definition of "inside": `escort.room_clearance` is the signed distance to the
    polygon less `TRACKING_MARGIN`; `clamp_to_room`, `room_inward` and `vip_room` are
    built on it, and every check that used a radius about room centre goes through them
    (setpoint clamp, the attacker's clamp and wall push, containment, the geofence,
    script and station checks, the planner, the teleop clamp, `watch_escort`). Without a
    `polygon:` key each reduces to the old radius arithmetic; `plan_escort` gives the same
    numbers with the key removed. `cfg.arena_radius` still applies when set tighter.
  - The clamp still pulls radially toward room centre, which is exact only while the
    room is star-shaped about that centre: checked on a 20,000-point grid for this
    polygon; re-check if `polygon:` changes shape a lot. `check_config` refuses a centre
    outside the room.
  - Layout: the pilot stands on +x facing -x; the DJI sits at the middle of the room
    (cf5's mark of 2026-11-02, so `vip_offset` is that mark minus room centre). The
    attacker's bearings (`AdversaryScript.legs`, `ReactiveAdversary.bearing`) went back
    to 145 degrees, the September/October geometry. `--marks` stands the attacker on its entry
    bearing.
  - The walking-case failure was not caused by the move: the pre-move code with the
    pre-move `arena.yaml` fails identically, and a sweep of `arena_radius` from 1.9 to
    3.95 m fails at every size.
  - Not changed: `ceiling` (1.85 m) and every encounter number. The ceiling no longer
    binds, but raising it is a choice about how high a hand-flown DJI may drag the ring.

**Staging, as planned in 2026-09** (the live demo then flew with a hand-flown DJI as the
VIP instead of a hat):

| Stage | What runs | Gate to the next one |
|---|---|---|
| 1 | sim, static VIP point, reactive attacker | the block reads clearly in RViz |
| 2 | hardware, static VIP point, nobody in the volume | separations match `plan_escort` |
| 3 | hat on a pole, carried, then worn; walk slowly | hat never drops out of Motive for > 0.4 s |
| 4 | attacker Crazyflie, reactive or scripted | the blocker gets between them every time |
| 5 | teleoperated attacker (`adversary:=external`) | the operator can fly it without chasing the ring |
| 6 | dress rehearsals | |

Full earlier text: `git show 678bac1:docs/escort/details/design-notes.md`

## Decisions still open

Each has a working default and is someone's call, not the code's. `plan_escort` prints the
consequences of whatever is chosen.

1. **Speed cap vs a moving VIP.** `v_max` 0.6 m/s is inherited from the follow-drone
   prototype. Turning the ring spends `R * phase_rate` of it, which leaves 0.30 m/s for
   following the VIP at rest and 0.05 m/s while blocking
   ([theory.md §4.3](theory.md#43-the-speed-budget-the-central-trade-off)). In the big
   arena `--sweep` (every separation held for a whole run) clears **0.20 m/s** against
   both attackers (re-run 2026-11-26). The default 0.30 m/s walking case passes against
   the reactive attacker only because the ring barely engages while the VIP walks, and
   fails against the script. A normal walk is 1.0–1.4 m/s, so the pilot is briefed to
   **hold the DJI still while the attacker is pressing**. Options, cheapest first: walk
   slowly; slow the ring (a lazier block); shrink `R` (less room around the VIP); raise
   `v_max` (a safety decision about flying faster near a person, which needs a written
   argument).
2. **A person as the VIP.** `R` = 1.0 m is a stand-off to a DJI. `min_vip_dist` tracks
   `R` exactly, so the guard sits on its own boundary with no margin. `h` = 1.2 m is chest
   height. **If a HUMAN ever stands in as the VIP, put `R` back to 1.5 m** and re-run
   `plan_escort`.
3. **A DJI standoff is still unset.** `min_vip_dist` (1.0 m) was chosen to fit a room, and
   the attacker's 0.80 m keep-out from the VIP is a reused constant; neither was measured
   against what a DJI's prop wash does to a 30 g Crazyflie. The mitigation in place is
   vertical (`vip_airborne`, `vip_height_offset`).
4. **The DJI as an attacker.** Not tried: nothing has verified its prop-wash risk to 30 g
   drones, its indoor stability without GPS, or the netting it would need. A Tello tracks
   as an ordinary rigid body, so `adversary:=external` already supports one.
5. **Attacker tracking near the arena edge (old room).** The attacker's station was about
   1.84 m from the arena centre, the setpoint clamp 1.90 m, and tracking was lost at
   2.24 m (`ARENA_RADIUS_LOST`). The maintainer's notes list four candidate explanations,
   confounded with each other; none has been isolated. `scripts/watch_escort.py` logs
   the evidence on every run.
6. **Proven separations.** The safety filter is a heuristic projection
   ([theory.md §5.4](theory.md#54-what-it-is-not-a-control-barrier-function)); a CBF
   filter would prove them.
7. **The verifier's models.** `plan_escort` models each drone as an assumed first-order
   lag (fit it from logged hardware runs and add a tracking margin), and skips the
   attacker's safety filter (route it through the same filter offline).
8. **Attacker starved during a VIP dropout.** A known code path, parked: stream the
   attacker in that hold branch too.
9. **Radio budget.** A healthy drone shows ~175 packets/s sent and ~168 unicast received
   ([known-issues.md](../../rig/known-issues.md), 2026-10-05), so four drones at 20 Hz of
   setpoints are a real fraction of the link. Whether the stream contributed to any
   telemetry stall is unmeasured.
10. **Yaw is 0 for every drone.** Defenders do not face the VIP or the threat: better
    looking, more to go wrong, so left out.
