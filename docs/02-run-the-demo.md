# 2. Run the demo

Always run the simulator first: it uses the same show script as a real flight. Open
every terminal as shown in [setup step 5](01-setup.md#step-5-open-a-terminal-the-right-way).

## Part 1: the simulator

No drones, no cameras, nothing can crash.

**Terminal 1**: start the simulated drones.

```bash
ros2 launch crazyflie launch.py backend:=sim
```

RViz opens and shows the drones on the floor. A small "preflight" window also opens;
in the simulator you can ignore it.

**Terminal 2**: check the plan, then run the show.

```bash
ros2 run crazyflie_shows plan_escort                 # must end "static case OK"
ros2 run crazyflie_shows escort_show --ros-args \
    -p use_sim_time:=true -p vip_mode:=point -p paced:=true
```

The show prints a prompt starting `>>>` at every stage and waits. Press **Enter** to go
on, or type **q** then Enter to land. In RViz you will see the ring form, the attacker
move in, and the ring turn to block it.

Three rules for the simulator:

- `use_sim_time:=true` is required in the simulator and must **never** be used on real
  drones.
- **Restart terminal 1 between runs.** The simulator cannot start a second run on the
  same drones; it looks like the show hanging at "gathering onto the ring".
- There are no lights and no camera data, so the simulator checks the logic, not the
  tracking.

## Part 2: real drones

![Flight day, in order](diagrams/12-flight-day.png)

### Once, before the first flight

- **Motive:** create one rigid body per drone, named exactly as in
  `src/crazyswarm2/crazyflie/config/crazyflies.yaml` (`cf1`, `cf3`, ...). Point the drone's
  nose along the room's **+X** axis when you create it.
  How: [details/mocap.md](details/mocap.md#2-defining-rigid-bodies).
- **Motive:** set streaming to **Multicast** at **50 Hz**.
- **For a DJI VIP:** create a rigid body for it too (asymmetric markers), and note its name.
- **The fleet:** the four drones you fly have `enabled: true` in `crazyflies.yaml`, the
  rest `false`. The show picks the roles itself: the three drones nearest the VIP
  defend, and the farthest one attacks.

### Step 1: check the plan (no drones needed)

```bash
ros2 run crazyflie_shows plan_escort           # must end "static case OK"
ros2 run crazyflie_shows plan_escort --marks   # prints where each drone must stand
```

### Steps 2 and 3: place the drones and record where they are

Start the cameras **without** the drone server, so nothing can arm:

```bash
ros2 launch crazyflie launch.py server:=False                 # terminal 1
python3 scripts/place_drones.py                              # terminal 2
```

`place_drones.py` draws each drone's floor mark in RViz. Add a MarkerArray display on
the topic `/escort/marks`. Slide each drone onto its mark, nose along +X. Then record
the real positions:

```bash
python3 scripts/sync_initial_positions.py --dry-run   # preview
python3 scripts/sync_initial_positions.py             # write
ros2 run crazyflie_shows plan_escort --marks          # must end "MARKS OK"
```

Stop terminal 1 (Ctrl-C) when done.

### Step 4: radio scan

```bash
./scripts/scan_fleet.sh          # every enabled drone must say GO
```

Do not skip this. If one enabled drone does not answer, the server hangs forever at
start, without any error message.

### Step 5: launch

```bash
ros2 launch crazyflie launch.py
```

This starts the camera receiver, the drone server, RViz and the preflight window.

### Step 6: preflight go / no-go

In the preflight window, check every drone (← / → switches drone):

| Check | Fly | Do not fly |
|---|---|---|
| Battery | green, above 3.8 V | red, below 3.7 V |
| `mocap [Hz]` | flat at about 50 | dropping, or 0 |
| Yaw error (`err.yaw`, dashed) | within ±5° | above 20°, or a red banner |

A yaw error means the Motive rigid body was created with the drone pointing the wrong
way. Recreate it. Screenshots of good and bad: [details/preflight-gui.md](details/preflight-gui.md).

### Step 7: dry run

```bash
ros2 run crazyflie_shows escort_show --ros-args -p dry_run:=true
```

Runs every check and prints the plan, but arms nothing.

### Step 8: fly

First flights, with a fixed point as the VIP and nobody in the room:

```bash
ros2 run crazyflie_shows escort_show --ros-args \
    -p vip_mode:=point -p paced:=true
```

With the DJI as the VIP (replace `dji` with its rigid-body name):

```bash
ros2 run crazyflie_shows escort_show --ros-args \
    -p vip_mode:=mocap -p vip_name:=dji -p paced:=true
```

The show waits for **Enter** at every stage:

![The show, step by step](diagrams/10-show-sequence.png)

**Brief the pilot:** take off only when asked, fly under the ring, keep inside the
middle of the arena (about 0.9 m from the centre), and **hold still while the attacker
is pressing**. [Why](03-how-it-works.md#the-speed-budget).

### Stopping

| Situation | Do this |
|---|---|
| Waiting at a prompt | type `q`, press Enter: normal landing |
| Any time | **Ctrl-C**: every drone lands under control |
| A drone is misbehaving | **E-STOP** (`e` in the preflight window): motors off, drones drop |

After an E-STOP, unplug and re-plug **every** drone's battery. Until you do, the drones
refuse to arm, and there is no error message.

## The web console (optional)

Prefer buttons to terminals? Run `./console/run.sh`. It opens http://localhost:8077, then
choose **Missions → Escort demo**. Every prompt becomes a button, a 3D view shows the
ring, and **Abort & land** does the same as Ctrl-C. Each button shows the exact command
it runs.

![The escort mission window](img/mission-escort.png)

More: [details/console.md](details/console.md).

## Testing without a DJI

You can steer a pretend VIP, or the attacker, with the keyboard instead. See
[details/operator-reference.md](details/operator-reference.md#teleop-no-dji-nobody-in-the-room).
All show settings are listed in the same file.
