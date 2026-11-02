# The serpent show

A fast, three-dimensional, one-minute show for cf1-cf5, built for the big arena.
Code: `src/crazyswarm2/crazyflie_shows/crazyflie_shows/serpent.py` (the plan, pure)
and `serpent_show.py` (flies it through `constellation_show.run`, the same loop,
checks and abort as the constellation).

## What it does

| phase | what the audience sees |
|---|---|
| takeoff, settle | all five up to 1 m over their marks |
| queue up | they fly into a line along a big loop, nose to tail, ~1.4 m apart |
| **serpent** | one lap of the room at up to ~1.9 m/s, every drone on the same 3D path a fixed distance behind the one in front, climbing and diving over two hills (1.3 to 3.1 m) |
| form the scythe | the line pivots into a tilted spoke from the centre outwards, 1.2 m at the hub to 3.6 m at the tip |
| **scythe** | the spoke sweeps one full turn round the room |
| home, land | back over the marks |

About 65 s on the wall clock. Print the exact timeline and every budget with
`ros2 run crazyflie_shows plan_serpent` (add `--plot out.png` for a top view).

## How it stays safe at speed

- **It sizes itself to the room.** The centre is the point furthest from the
  arena's edge (the polygon's inscribed-circle centre); the loop radius and the
  scythe's reach are the largest that keep `SerpentConfig.margin` (0.6 m) plus the
  tracking margin from every edge. A smaller room gets a smaller show, or a clear
  refusal.
- **Plan-view separation is enforced**, so no drone ever passes over another and
  downwash never stacks. In both figures the gaps are constant: an arc along the
  loop, a radial gap along the spoke.
- **Speeds and accelerations are checked on the uploaded trajectories**, not the
  ideal paths, against `safety.MAX_SPEED` / `MAX_ACCEL`. The serpent lap is 21 s,
  which puts the peak near 1.86 m/s (93% of the 2.0 m/s limit). Shorten it and the
  planner will tell you when you cross the limit.
- The morph into the scythe is chosen (heading and who goes where) so that the
  flight home afterwards is also clear.

## Verified (2026-11-02)

- `plan_serpent` passes on the marks the constellation flew from.
- Simulator, three full runs on a private ROS domain: landed on time. The recorded
  flight, compared with the plan, tracked within 21 cm (serpent) and 19 cm (scythe).
  The closest pair flown was 1.06 m (3D) and 0.92 m (plan view), as planned. Every
  drone landed within 2 mm of its mark.
- **Flown on hardware 2026-11-02** (first run, operator-run, reported a success). Still
  rehearse with `-p dry_run:=true` after moving the marks.

## Before flying

The usual flight-day steps (docs/02-flight-day.md), then:

1. Put cf1-cf5 on their marks, anywhere inside the arena polygon; then sync the
   positions and run `plan_serpent`. The marks set the queue-up and home legs.
   The tightest moment is usually the flight home.
2. `ros2 run crazyflie_shows serpent_show --ros-args -p dry_run:=true` (every check,
   nothing armed), then without `dry_run`.
