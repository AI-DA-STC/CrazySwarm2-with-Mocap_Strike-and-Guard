# Running the guard show

Defenders protect a VIP (a fixed point, or a hand-flown DJI) from attackers. This page
is only what differs from the shared [flight day](../02-flight-day.md). The game:
[how-it-works.md](how-it-works.md). Guests: [presenting.md](presenting.md).

![Guard flight day, in order](../diagrams/31-guard-flight-day.png)

## 1. Check it with no drones

```bash
ros2 run crazyflie_shows plan_guard --defenders 4 --attackers 3
```

It plays a dozen matches against simulated drones and ends in **SAFE on every
seed** or **SAFETY FAILED**. Do not fly a configuration that fails.

To watch the matches in RViz:

```bash
rviz2 -d install/crazyflie_shows/share/crazyflie_shows/data/guard.rviz &
ros2 run crazyflie_shows plan_guard --rviz --matrix
```

`--matrix` plays every defence against every attack, and `--matrix --rules all` does
that under every rule set. `plan_guard --list` names them all.

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
`-p vip_mode:=mocap` to protect the DJI, and `-p paced:=true` to wait for Enter at each
gate:

![The guard match, step by step](../diagrams/32-guard-match-sequence.png)

Or use the web console (`./console/run.sh`), **Missions → Guard (N v M)**: every
choice is a field, the gates are buttons, and the 3D view shows the match.

For a new set-up on real drones, start small: 1 v 1, slow and wide apart, then add
drones and speed one step at a time.

**Speed and the onboard controller.** Both teams fly 1 m/s, on the Mellinger controller
by default. To fly the standard controller (`-p controller:=pid`, or **pid** in the
console), slow both teams to 0.6 m/s (`-p v_max_defense:=0.6 -p v_max_attack:=0.6`, or
the console's two speed fields) and check it with `plan_guard` first. Why:
[how-it-works.md](how-it-works.md#why-the-drones-run-late-and-what-to-do-about-it).

## Choosing the strategies

Add `-p defense:=<name> -p attack:=<name>` (`--defense`, `--attack` for the planner):

| Defence | Attack |
|---|---|
| `shell` (default), `zone`, `hunter`, `ring` | `coordinated` (default), `flood`, `wolfpack`, `direct` |

What each does, and which pairings are even:
[how-it-works.md](how-it-works.md#the-strategies).

## Choosing the rules

Add `-p rules:=<name>` (`--rules <name>` for the planner): `tag` (default), `pressure`,
`zone`, `zone_pressure` or `timer`, explained in
[how-it-works.md](how-it-works.md#the-rules).

**Contested strikes:** `-p strike_block:=0.8` (the console's **Contested strikes**
field; `--rparam strike_block=0.8` for the planner) makes a defender within 0.8 m of an
attacker stop its strike. It works with every rule set and is off (`0`) unless set.

Check every new pairing or rule set with `plan_guard` before flying it.

## What you will see

**Form-up** (described in [how-it-works.md](how-it-works.md#the-start-of-a-match)). It
starts just before START, after the DJI gate when there is one. The show prints
`NOT A FAIR START yet` until every attacker is far enough from the defenders, then
`fair start`; only then press START. Under `timer` nobody can be taken out, so there is
no check. Options: `-p form_up_attackers:=follow` (the console's **Attackers during the
form-up**) makes the attackers follow the VIP too, on an arc on their own side;
`-p form_up:=false` (`--no-form-up` for the planner) starts from the floor marks.

**The lights and the finale:** [how-it-works.md](how-it-works.md#what-the-lights-mean).
The finale also goes through the safety layer; `-p finale:=false` turns it off.

**In RViz or the console's 3D view**, the map shows what each drone means to do:

| You see | It means |
|---|---|
| blue line ending in a bar across | a defender **blocking** an attacker's way in |
| blue curved arrow | a defender coming round the side (**pincer**) |
| blue diamond | a defender's **post** while nothing is coming |
| red dashed line to a small circle | an attacker going to its **staging** point |
| thick red arrow | an attacker **striking**; magenta is the **decoy** |
| dashed amber arrow | an attacker **feinting** (showing one side, going for another) |
| faint red lines out from the VIP | the attack's **lanes**: dashed while staging, arrows once it commits |
| a faint bubble round a drone | the safety layer is changing that drone's path right now |

Each label shows how close the drone is to being taken out (`d40%`), and an
attacker's how close it is to striking (`s40%`). The VIP turns green (secure) or
red (compromised) at the end.

**Near misses** pause the match, or land everything
([how-it-works.md](how-it-works.md#layers-of-safety)). After each flight the show
prints any near misses and the closest pair, and where the run's trace was saved.

Ctrl-C (or the console's Abort) lands everything where it is.

To write your own strategy or rule set: [details/modules.md](details/modules.md).
