# Mission windows

Each demo's own screen in the web console. Start the console with `./console/run.sh`,
open http://localhost:8077, then pick the demo under **Dashboard → Missions** (it opens in
its own browser window, e.g. `/mission?m=crazyflie_shows/escort`).

Everything on a window is defined by one file per demo,
`src/crazyswarm2/crazyflie_shows/missions/<demo>.yaml` (`escort.yaml`, `stl.yaml`): the
choices offered, the prompts that become buttons, the status tiles, the teleop pad. The show itself never reads that
file; it only describes how to *run* the show. The rest of the console is described in
[console.md](console.md).


![The escort mission window, waiting at a gate](../img/mission-escort.png)

The escort, paced, stopped at its ARM gate (simulator backend):

| # | What it is |
|---|---|
| 1 | **The run state** — READY / RUNNING / **WAITING FOR YOU** / LANDING / ENDED, or RUNNING OUTSIDE THE CONSOLE when the census finds the show already running from a terminal. |
| 2 | **Link pills** — the server (and whether it is the simulator), the foxglove bridge behind the 3D view, the pose stream this window is receiving, and the console event stream. |
| 3 | **The scene** — the measured arena from `arena.yaml`, the parking marks from `crazyflies.yaml`, every drone with its trail and altitude, and the show's own markers. |
| 4 | **View controls** — 3D or Plan (x right, y up: the orientation of `plan_escort --plot` and of the teleop keys), reset, trails. |
| 5 | **The gate** — the script's own prompt, as buttons. `Enter` presses Continue; `q` lands. The panel glows and the header changes, so a waiting show is visible across the room. |
| 6 | **Indicators** — pulled out of the script's stdout by the spec's regexes. |
| 7 | **Fleet tiles** — supervisor state and battery from the console's health sweep, altitude from the live pose feed. |
| 8 | **The timeline** — the lines the spec calls events, interleaved with every fleet command the server acted on (tagged FLEET), wall-clock stamped to lay against a video. |
| 9 | **Raw output and a stdin line** — the script and each helper, on their own tabs. |
| 10 | **E-STOP** — the same one-click, answered e-stop as the console header. |

| Widget | What it shows / does |
|---|---|
| `scene` | Live 3D view (three.js): the measured arena from `arena.yaml` (radius_tested amber, radius_lost red, the ceiling as a cage), parking marks from `crazyflies.yaml`, every drone with a trail and altitude label, every other `/poses` rigid body (a VIP hat, an external adversary), and the show's own RViz markers. **3D** orbits; **Plan** is a top-down view with x right and y up — the orientation of `plan_escort --plot` and of the teleop keys. A drone drawn from its onboard estimate (no mocap, e.g. the simulator) is labelled `(est)`; with mocap, the estimate is a wireframe ghost and the fleet tile shows the estimate-vs-mocap error. |
| `gate` | When the script stops for the operator, its prompt becomes a big card with buttons (`Continue`, `Land now (q)`, ...). `Enter` presses the button marked `key: Enter`. A prompt printed without a newline (an `input()`) also shows, with a text box. |
| `indicators` | Status tiles pulled from the script's own output by regex: phase, leg, ring state, geofence... |
| `teleop` | An on-screen key pad (hold to move) plus an opt-in keyboard mode, driving a helper process such as `escort_teleop` — the same node, with the same clamps, as in a terminal. Can stay **locked** until the script prints a line (`enable_after`). |
| `fleet` | Per-drone tiles: supervisor state and battery from the console's health sweep, live altitude from the 3D feed. |
| `launch` | The operator's choices (from `options:`), the simulation-clock switch, the exact command line, Start / **Abort & land** / Kill, and the helper processes. |
| `events` | A timeline of the lines that matter (the spec's `events:` patterns), wall-clock stamped so they can be laid against a video. |
| `output` | Raw output of the script and each helper, with a stdin line. |

The header carries the run state, the link pills and the **E-STOP** — the same
one-click, answered-within-3-s e-stop as the console header.

**The launch panel** is where a run starts, and it is the only place the window
builds a command:

![The mission window's Run panel](../img/mission-run-panel.png)

**1** the operator's choices, from the spec's `options:` (each one a stored
setting, shared with every other window on this console). **2** the exact
command line that will run — it updates as you choose, and the confirm step
shows it again. **3** Start, which becomes **Abort & land** and **Kill** while
the show runs. **4** the helper processes this choice implies, with their own
start/stop.

**The teleop pad** appears when a choice needs one (here VIP = `manual`), and
drives the same `escort_teleop` node a terminal would:

![The teleop pad in a mission window](../img/mission-teleop.png)

**1** the helper and whether it is running — it starts and stops with the
mission. **2** the pad: hold a key to move, release to stop. **3** the opt-in
keyboard mode, so the physical keys drive it; the pad stays **locked** until the
script prints the spec's `enable_after` line (for the escort, `ESCORT LIVE` —
the operator rule "start the teleop, then touch nothing until the show is live").

## Editing a mission file: the spec format

One YAML file per mission. Everything except `title` and `run` is optional. The
shipped `crazyflie_shows/missions/escort.yaml` (gates, two teleop helpers,
markers) is the worked example. A spec edit needs no console restart and, with the
workspace's `--symlink-install` build, no rebuild.

```yaml
mission: 1                      # spec version; the console refuses others
title: Escort demo
summary: >                      # shown on the mission card
  One paragraph: what it is, what to check first.
docs: docs/details/escort-reference.md   # shown as a pointer, nothing reads it
run: escort_show                # executable in THIS package, or "pkg exe"
flight: true                    # moves drones -> confirm step shows the commands
abort: sigint                   # how "Abort & land" ends it: sigint | q

options:                        # the operator's choices, each becomes -p name:=value
  - name: vip_mode              # ROS parameter name (or set `param:` to differ)
    label: VIP
    choices:                    # a select; a mapping gives each choice a description
      point: a fixed point at the mark
      manual: a point you steer
    default: point
  - name: paced
    type: bool                  # select | bool | number | text
    default: true
  - name: dry_run
    type: bool
    default: false
    omit_default: true          # leave it off the command line while it is the default
  - name: vip_name
    type: text
    default: operator
    when: {vip_mode: mocap}     # only shown, and only passed, when this holds

helpers:                        # extra processes that go with the mission
  vip_keys:
    label: VIP keyboard
    run: escort_teleop
    params: {target: vip}       # fixed -p values
    when: {vip_mode: manual}    # only offered when this holds
    autostart: true             # started (1.5 s) before the main script
    teleop: planar              # key pad: planar (wasd, space, c) | spatial (+ q/e)
                                # | a list of {label, key, kbd, cell: [col,row], hold}
    enable_after: 'ESCORT LIVE' # pad locked until the main script prints this

topics:
  markers: [/escort/markers]    # visualization_msgs/MarkerArray topics to draw

arena: room                     # the boundary the 3D view draws -- see below

gate:                           # `gate: false` for a show that never waits
  prompt: '^\s*>>>\s*(?P<text>.+)$'   # a line that opens a gate; group `text` is shown
  until: '\[q\]\s*land'         # the line that ends the prompt block (lines between = details)
  partial: '(\?|:|>)\s*$'       # an unterminated line that counts as a prompt
  buttons:
    - {label: Continue, send: '', key: Enter, tone: primary}   # send = the line written to stdin
    - {label: Land now (q), send: q, tone: danger}

indicators:                     # several rules may share a label; the latest match wins
  - {label: Phase, match: 'ESCORT LIVE', value: LIVE, tone: {LIVE: ok}, initial: idle}
  - {label: Leg, match: '>>> leg (\d+/\d+) (STARTED|COMPLETE)', value: '$1 $2'}
  - {label: Figure, match: '\[t\+\s*[\d.]+s\]\s*(?P<fig>.+)$', value: '$fig'}

events: ['\[t\+', 'GEOFENCE', '\*\*\*']   # lines that get a timeline row

layout:                         # which widgets, where. Defaults shown.
  main: [scene]
  side: [gate, indicators, teleop, fleet, launch]   # teleop:vip_keys = just that helper
  bottom: [events, output]
view: escort_view.mjs           # optional custom module next to the spec (section 5)
```

**The boundary (`arena:`).** What the 3D (and 2D) view draws as the edge of
the flight area. It is a picture: nothing reads it to enforce anything, so draw
what the show's own checks use.

```yaml
arena: room                     # the measured room in arena.yaml (what safety.py and
                                #   the escort planner check)
arena: none                     # nothing; grid and axes only
arena:                          # a boundary of the mission's own
  rect: [-2.0, -2.0, 2.0, 2.0]  # x0, y0, x1, y1 in metres, world frame
  label: STL game square 4 x 4 m
arena:                          # or several, drawn together
  - room
  - {circle: [0.0, 0.0, 1.5], label: inner zone, color: '#58a6ff', dashed: true, ceiling: 2.0}
```

A `rect` or `circle` takes an optional `label`, `ceiling` (m; draws the cage
top), `color` (`'#rrggbb'`, default the room's amber) and `dashed`. A spec
**without** `arena:` gets `missions.DEFAULT_ARENA`, which is `none`: a window draws
the measured room only when its spec asks. `escort.yaml` says `arena: room`;
`stl.yaml` draws its game square. A custom boundary's numbers are written in the
spec, since a spec cannot import the show; say in a comment where they come from
and keep the two in step.

**Regexes.** The patterns run in the browser (JavaScript), and are validated by
the console (Python) when the spec loads. Write named groups either way —
`(?P<name>...)` or `(?<name>...)` — the console translates. A **leading** `(?i)`
is allowed (case-insensitive); any other inline flag is refused, because
JavaScript has none. A spec that does not validate is listed with its error
rather than silently dropped.

**Values the operator picks are validated** against the spec before anything
runs: a select must be one of its choices, a number must parse, a text value may
not contain spaces, and the free-form "more ROS parameters" field must be
`name:=value` pairs. `ros2 run` silently ignores a misspelled parameter and flies
the default, so a typo is refused instead.

**The simulation clock** is not an option you declare: every mission window has
it, defaulting to whatever the running stack is (`/clock` present = sim), and it
adds `use_sim_time:=true` to the main script **and every helper**.

---
