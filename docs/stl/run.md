# STL: run it

Five defenders against five intruders, ten drones. What it is and why:
[how-it-works.md](how-it-works.md). The steps every demo shares (simulator rules, radio
scan, launch, preflight, stopping) are in [flight day](../02-flight-day.md); this page adds
the STL game's own.

## Check a game (no drones, no simulator)

```bash
ros2 run crazyflie_shows plan_stl          # plays seeds 0-19 against the yaml marks
```

As shipped, this ends `PLAN REFUSED`. That is expected: see the first
[honest limit](how-it-works.md#honest-limits). `plan_stl --seed N` checks one seed.

## In the simulator

The simulator needs the ten STL drones enabled and standing on their start slots. The
easiest way is a copy of the fleet file for the session:

1. Copy `src/crazyswarm2/crazyflie/config/crazyflies.yaml` to, say, `~/stl_fleet.yaml`.
2. In the copy, set `enabled: true` for `cf1, cf2, cf4, cf5, cf8` (defenders) and
   `cf10`-`cf14` (intruders), and `false` for the rest.
3. Set each one's `initial_position` to its start slot. `plan_stl` prints the slots
   when a mark is off; they are `DEF_POS_INIT` and `INTRUDER_POS_INIT` in
   `src/crazyswarm2/crazyflie_shows/crazyflie_shows/stl_game.py`.

```bash
ros2 launch crazyflie launch.py backend:=sim crazyflies_yaml_file:=$HOME/stl_fleet.yaml
ros2 run crazyflie_shows plan_stl --yaml ~/stl_fleet.yaml --min-sep 0.04   # must end "PLAN OK"
ros2 run crazyflie_shows stl_show --ros-args -p use_sim_time:=true -p seed:=0 -p min_sep:=0.04
```

`min_sep:=0.04` lowers the separation floor far enough for the shipped game to pass. That
is fine for a simulator test, never for real drones.

## On real drones

**Before you start:** plug in the **second Crazyradio**: cf10-cf14 use it. Then edit
`crazyflies.yaml` itself as in steps 2-3 above, because the server reads only that file.
Switch the intruders back to `enabled: false` afterwards, or every other launch will need
the second radio.

1. **Place the drones** on their start slots: the 5 defenders near the goal edge, the 5
   intruders on the opposite side. Record their marks
   ([flight day 1](../02-flight-day.md#1-place-the-drones-and-record-where-they-are)).
2. **Check the plan:** `ros2 run crazyflie_shows plan_stl`. With the shipped game this
   refuses at the default 15 cm floor. Flying anyway needs a deliberate decision to use
   `min_sep:=0.10` (see [honest limits](how-it-works.md#honest-limits)).
3. **Scan, launch, preflight**: [flight day 2-4](../02-flight-day.md#2-radio-scan). All ten
   drones must say GO.
4. **Dry run:** `ros2 run crazyflie_shows stl_show --ros-args -p dry_run:=true`
5. **Fly** (choose a seed that passed `plan_stl --seed N`):
   ```bash
   ros2 run crazyflie_shows stl_show --ros-args -p seed:=7 -p min_sep:=0.10
   ```

There are no prompts: once armed, the game runs to the end (about 30 seconds from take-off
to landing). **Ctrl-C** lands all ten at any time.

## In the web console

**Missions → STL pursuit-evasion** shows the game square, each intruder's result as it
happens, the seed and the closest approach. It has no gates; **Abort & land** is Ctrl-C.

More settings and the procedure for a new version of the game:
[details/stl-design-notes.md](../details/stl-design-notes.md).
