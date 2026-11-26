# Mission windows

Each demo's own screen in the web console. Start the console (`./console/run.sh`, open
http://localhost:8077) and pick the demo under **Dashboard → Missions**; it opens in its
own browser window, e.g. `/mission?m=crazyflie_shows/escort`. `/mission` alone lists every
window, and a spec that does not validate is listed with its error. The built-in **Any
flight script** window runs any discovered script with the generic `>>>` gate.

Everything on a window comes from one file per demo,
`src/crazyswarm2/crazyflie_shows/missions/<demo>.yaml`. The show never reads that file; it
only says how to *run* the show. A new demo is a new YAML file, not a console change. The
rest of the console: [console.md](console.md); its internals:
[console/README.md](../../console/README.md).

## The window

![The escort mission window, waiting at a gate](../img/mission-escort.png)

The escort, paced, at its ARM gate (simulator backend). Each callout and the widget behind
it (the names the spec's `layout:` uses):

| # | Widget | What it shows / does |
|---|---|---|
| 1 | (header) | **Run state**: READY / RUNNING / **WAITING FOR YOU** / LANDING / ENDED, or RUNNING OUTSIDE THE CONSOLE when the show was started from a terminal. |
| 2 | (header) | **Link pills**: the server (and whether it is the simulator), the foxglove bridge behind the 3D view, the pose stream, the console event stream. |
| 3, 4 | `scene` | Live 3D view: the spec's boundary (below), the parking marks from `crazyflies.yaml`, every drone with a trail and altitude label, every other `/poses` rigid body (a VIP hat, an outside attacker), and the show's own markers. **3D** orbits; **Plan** is top-down with x right and y up, the orientation of `plan_escort --plot` and the teleop keys. A drone drawn from its onboard estimate (no mocap, as in the simulator) is labelled `(est)`; with mocap the estimate is a wireframe ghost. |
| 5 | `gate` | The script's prompt as a card with buttons (`Continue`, `Land now (q)`, ...). `Enter` presses the button marked `key: Enter`. A prompt with no newline (an `input()`) shows too, with a text box. The panel glows and the header changes, so a waiting show is visible across the room. |
| 6 | `indicators` | Status tiles pulled from the script's output by the spec's regexes: phase, leg, ring, geofence... |
| 7 | `fleet` | Per drone: supervisor state and battery from the console's health sweep, live altitude from the pose feed, and with mocap the estimate-vs-mocap error. |
| 8 | `events` | Timeline: the lines the spec calls events, plus every fleet command the server acted on (tagged FLEET), wall-clock stamped to lay against a video. |
| 9 | `output` | Raw output of the script and each helper, on their own tabs, with a stdin line. |
| 10 | (header) | **E-STOP**: the same one-click e-stop as the console header ([console.md](console.md#e-stop-stop-and-abort)). |
| – | `launch` | The **Run** panel, below the fleet tiles: the operator's choices (from `options:`, each one stored setting shared with every console page), the simulation-clock switch, the exact command line (updated as you choose, shown again at confirm), Start, which becomes **Abort & land** and **Kill** while the show runs, and the helper processes this choice implies, with their own start/stop. |
| – | `teleop` | A key pad for a helper such as `escort_teleop` (same node and clamps as in a terminal), shown when a choice needs one: |

![The teleop pad in a mission window](../img/mission-teleop.png)

**1** the helper and whether it runs; it starts and stops with the mission. **2** the pad:
hold a key to move, release to stop. **3** opt-in keyboard mode, so the physical keys
drive it. The pad stays **locked** until the script prints the spec's `enable_after` line
(for the escort, `ESCORT LIVE`: start the teleop, then touch nothing until the show is
live).

**A clean scene** for recording or a projector: add `&clean=1` to the URL (e.g.
`/mission?m=crazyflie_shows/guard&clean=1`). The scene drops what is about the rig rather
than the show: trails (the console's and a show's own `trail` markers), parking marks, the
escort's geometry circle, the arena's text tags, world axes, view bar, legend, the "no
poses yet" notice and the console's altitude tags. A show's own labels stay.

## What each button sends

| Button | What happens | Terminal equivalent |
|---|---|---|
| **Start** | `POST /api/mission/start`: the autostart helpers first, 1.5 s later the script, each `ros2 run <pkg> <exe> --ros-args -p ...`, every argv shown at confirm and logged. Refused while another flight script runs. | The same `ros2 run` lines, one terminal each, helpers first |
| **gate button** | The button's `send` line plus a newline to the script's pty (`Continue` is a bare Enter). | Enter (or `q`) in the script's terminal |
| **Abort & land** | **One** SIGINT to the script's process group, nothing after it. The show's `abort.py` lands the drones where they are. | Ctrl-C **once** |
| **Kill** | A separate, confirmed SIGKILL. | `kill -KILL -<pgid>` |
| **teleop pad / keys** | The key (no newline) to the helper's pty, re-sent every 90 ms while held, a space on release. | Hold the key in `escort_teleop`'s terminal |

Every value is checked before anything runs: a select must be one of its choices, a
number must parse, a text value may not contain spaces, and the "more ROS parameters"
field must be `name:=value` pairs. `ros2 run` silently ignores a misspelled parameter and
flies the default, so a typo is refused instead.

**The simulation clock** is on every window without being declared. It defaults to what
the running stack is (`/clock` present means sim) and adds `use_sim_time:=true` to the
script **and every helper**.

## The spec format

One YAML file per mission. Only `title` and `run` are required. The shipped
`crazyflie_shows/missions/escort.yaml` (gates, two teleop helpers, markers) is the worked
example. An edit needs no console restart and, with the `--symlink-install` build, no
rebuild.

```yaml
mission: 1                      # spec version; the console refuses others
title: Escort demo
summary: >                      # shown on the mission card
  One paragraph: what it is, what to check first.
docs: docs/escort/details/reference.md   # shown as a pointer, nothing reads it
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
view: escort_view.mjs           # optional custom module next to the spec
```

**The boundary (`arena:`)** is what the view draws as the edge of the flight area. It is
only a picture: nothing enforces it, so draw what the show's own checks use.

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

A `rect` or `circle` takes an optional `label`, `ceiling` (m; draws the cage top), `color`
(`'#rrggbb'`, default the room's amber) and `dashed`. A spec **without** `arena:` draws
nothing (`missions.DEFAULT_ARENA` is `none`). `escort.yaml` says `arena: room`; `stl.yaml`
draws its game square. A spec cannot import the show, so a custom boundary's numbers are
copied into it: say in a comment where they come from, and keep the two in step.

**Regexes** run in the browser (JavaScript) and are validated by the console (Python) when
the spec loads. Named groups work either way, `(?P<name>...)` or `(?<name>...)`. A
**leading** `(?i)` is allowed; any other inline flag is refused, because JavaScript has
none.

---

Full earlier text: `git show 678bac1:docs/rig/mission-window.md`
