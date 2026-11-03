# Running the guard show

Defenders protect a VIP (a fixed point, or a hand-flown DJI) from attackers. You
choose how many of each, and which strategy each team uses. A safety layer sits
under both strategies and keeps every drone apart, out of the DJI's way and
inside the room, whatever the strategies ask for.

The shared steps (power, mocap, scanning, syncing) are in
[../02-flight-day.md](../02-flight-day.md). This page is only what is different.

## 1. Check it with no drones

```bash
ros2 run crazyflie_shows plan_guard --defenders 4 --attackers 3
```

It plays a dozen matches against simulated drones and ends in **SAFE on every
seed** or **SAFETY FAILED**. Do not fly a configuration that fails.

To see the matches, open RViz and add `--rviz`:

```bash
rviz2 -d install/crazyflie_shows/share/crazyflie_shows/data/guard.rviz &
ros2 run crazyflie_shows plan_guard --rviz --matrix
```

`--matrix` plays every defence strategy against every attack strategy in turn, and
`--matrix --rules all` does that under every rule set.
`ros2 run crazyflie_shows plan_guard --list` names them all.

## 2. Stand the drones on their marks

```bash
ros2 run crazyflie_shows plan_guard --marks --defenders 4 --attackers 3
```

Defenders go round the VIP, attackers on the far side from the operator. Sync the
positions and run `plan_guard` again.

## 3. Simulator, then a dry run, then fly

```bash
ros2 launch crazyflie launch.py backend:=sim
ros2 run crazyflie_shows guard_show --ros-args -p use_sim_time:=true \
    -p defenders:=cf1,cf2,cf3,cf4 -p attackers:=cf5,cf6,cf7
```

On the drones, run the same command without `use_sim_time`, first with
`-p dry_run:=true` (every check, nothing armed), then for real. Add
`-p vip_mode:=mocap` to protect the DJI. With `-p paced:=true` the show waits for
Enter before arming, before the match starts and before landing. With the DJI, it
also waits while the pilot takes it off and lands it; the drones hold and keep
out of its way during every wait.

Or use the web console (`./console/run.sh`), **Missions → Guard (N v M)**: every
choice is a field, the waits are buttons, and the 3D view shows the match.

For the first sessions on real drones, follow the ladder in
[../details/guard-design-notes.md](../details/guard-design-notes.md) ("Before the
first hardware flight"): start 1 v 1, slow and wide apart.

## Choosing the rules

Add `-p rules:=<name>` (`--rules <name>` for the planner):

| Rules | In one line |
|---|---|
| `tag` (default) | a defender that stays close to an attacker long enough takes it out |
| `pressure` | either side takes a drone out by outnumbering it nearby; one against one is a standoff |
| `zone` | like `tag`, but each side can only be taken out on the other side's ground |
| `zone_pressure` | like `pressure`, on the other side's ground |
| `timer` | nobody is taken out; the defence must hold until the clock runs out |

Check a rule set with `plan_guard --rules <name>` before flying it.

## What you will see

Defenders are blue and attackers red. A drone that is **taken out** turns amber and
lands; depending on the rules, that can happen to either side. An attacker that
holds close to the VIP **strikes** and lands too. The attack wins on a strike. The
defence wins by taking out every attacker, or by holding until the clock runs out.

In RViz, each drone's label shows how close it is to being taken out (`d40%`), and
an attacker's how close it is to striking (`s40%`).

Ctrl-C (or the console's Abort) lands everything where it is.

How it is put together: [../details/guard-modules.md](../details/guard-modules.md).
Why, what was measured, and how to write your own strategy or rule set:
[../details/guard-design-notes.md](../details/guard-design-notes.md).
