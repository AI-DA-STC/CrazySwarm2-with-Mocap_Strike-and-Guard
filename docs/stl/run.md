# STL: run it

Five defenders against five intruders, ten drones. What it is and why:
[how-it-works.md](how-it-works.md). The steps every demo shares are in
[flight day](../02-flight-day.md); this page adds the STL game's own.

The game names its own ten drones (`DEFENDER_CF_NAMES` and `INTRUDER_CF_NAMES` in
`crazyflie_shows/stl_game.py`; `plan_stl` prints them), and its own start slots
(`DEF_POS_INIT`, `INTRUDER_POS_INIT`). The intruders use the **second Crazyradio**.

## Check a game (no drones, no simulator)

```bash
ros2 run crazyflie_shows plan_stl          # plays seeds 0-19 against the yaml marks
ros2 run crazyflie_shows plan_stl --seed 7 # one seed
```

As shipped, this ends `PLAN REFUSED`. That is expected: see the first
[honest limit](how-it-works.md#honest-limits).

## In the simulator

Use a copy of the fleet file for the session:

1. Copy `src/crazyswarm2/crazyflie/config/crazyflies.yaml` to, say, `~/stl_fleet.yaml`.
2. In the copy, set `enabled: true` for the game's ten drones and `false` for the rest.
3. Set each one's `initial_position` to its start slot (the coordinates are in
   `DEF_POS_INIT` / `INTRUDER_POS_INIT`; `plan_stl` points there when the start move
   fails).

```bash
ros2 launch crazyflie launch.py backend:=sim crazyflies_yaml_file:=$HOME/stl_fleet.yaml
ros2 run crazyflie_shows plan_stl --yaml ~/stl_fleet.yaml --min-sep 0.04   # must end "PLAN OK"
ros2 run crazyflie_shows stl_show --ros-args -p use_sim_time:=true -p seed:=0 -p min_sep:=0.04
```

`min_sep:=0.04` lowers the separation floor far enough for the shipped game to pass: fine
in the simulator, never on real drones.

## On real drones

Plug in the second Crazyradio, and edit `crazyflies.yaml` itself as in steps 2-3 above
(the server reads only that file). Afterwards set the intruders back to `enabled: false`,
or every other launch needs the second radio.

1. **Place the drones** on their start slots, defenders near the goal edge, intruders on
   the opposite side, and record their marks
   ([flight day 1](../02-flight-day.md#1-place-the-drones-and-record-where-they-are)).
2. **Check the plan:** `ros2 run crazyflie_shows plan_stl`. The shipped game refuses at
   the default 15 cm floor; flying it anyway means deciding to use `min_sep:=0.10`
   ([honest limits](how-it-works.md#honest-limits)).
3. **Scan, launch, preflight** ([flight day 2-4](../02-flight-day.md#2-radio-scan)). All
   ten must say GO.
4. **Dry run:** `ros2 run crazyflie_shows stl_show --ros-args -p dry_run:=true`
5. **Fly** a seed that passed `plan_stl --seed N`:
   ```bash
   ros2 run crazyflie_shows stl_show --ros-args -p seed:=7 -p min_sep:=0.10
   ```

There are no prompts: once armed, the game runs to the end
([step by step](how-it-works.md#the-flight-step-by-step)). **Ctrl-C** lands all ten at any
time.

## In the web console

**Missions → STL pursuit-evasion** shows the game square, each intruder's result as it
happens, the seed and the closest approach. It has no gates; **Abort & land** is Ctrl-C.

More settings, and what to do when a new version of the game arrives:
[details/design-notes.md](details/design-notes.md).
