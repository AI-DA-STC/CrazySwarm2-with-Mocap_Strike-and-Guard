# The mission console: buttons and the commands they run

`console/` is an optional browser front end for this rig. Every button runs the same
`ros2` or shell command you could type, shows it before and while it runs, and logs it;
the Command log exports the session as a shell script. The aim is that you learn the
commands and stop needing the GUI, so this page gives the terminal equivalent of every
button. Where this page and the command the console displays disagree, **the displayed
command is the truth** and this page is the bug.

- Start it with `./console/run.sh` and open http://localhost:8077. Options, what `run.sh`
  does, and why `--host 0.0.0.0` is unsafe: [console/README.md](../../console/README.md),
  which also owns the internals.
- Each demo's own window: [mission-window.md](mission-window.md).
- The console is **not a safety layer**: it will run a show that should not fly. The
  refusals live in the shows, the planners and `sync_initial_positions.py`.

## The dashboard

![The console dashboard, with numbered callouts](../img/console-dashboard.png)

*(simulator backend, so the drone tiles read "no telemetry topics".)*

| # | What it is |
|---|---|
| 1 | **Verdict**: ALL SYSTEMS GO / ATTENTION / FAULT and the headline behind it. Click for System health. |
| 2 | **Telemetry pills**: server, mocap, `/poses` (with a sparkline, so a dropout shows as a dive), fleet size, ROS domain, time since the last probe. |
| 3 | **E-STOP**: one click, no confirmation, answered within 3 s. On every tab. [E-STOP](#e-stop-stop-and-abort) |
| 4 | **Fleet row**: one tile per drone plus the radio. A drone tile gives the supervisor state in words (`FLYING`, `armed`, `ready to arm`, `E-STOPPED`, `FLIPPED`, `CRASHED`, `cannot arm yet`, or combinations), battery voltage and bar, link strength and unicast latency. The bar's length is charge (3.3 V empty to 4.2 V full); its colour uses the health check's thresholds (3.8 V warning, 3.7 V critical). |
| 5 | **Needs attention**: every failing or warning check as a chip. |
| 6 | **Stepper**: the five steps of a session, which follows the rig (below). Click a step to see its buttons anyway; the choice holds until the rig changes state. |
| 7 | **This step's buttons**. The tooltip is the real argv; `⋯` opens the full card in Control. A button that cannot work now is dimmed, with the reason at the end of the row. |
| 8 | **More**: every action, ranked by how often you have run it; ☆ pins it beside the step buttons. |
| 9 | **Missions**: one chip per mission window, each opening its own browser window. *not built* when its package is not. |
| 10 | **Processes**: everything this console started, plus rig processes started outside it (amber, with their domain; select one to Stop or Kill it). **Fleet commands**: every command the server acted on, from anyone. |
| 11 | **Stop / Kill / Copy / follow** for the selected process. |
| 12 | **Stdin line**: what you type plus a newline goes to the process. An empty line is a bare Enter, which a paced show's gate waits for. A prompt with no newline (`input('...: ')`) shows at the bottom of the pane. |

Every tile, chip and pill links to the check behind it.

**The stepper follows the rig.** Nothing up: *before the server* (scan the fleet, read a
battery, *Start mocap only*). Mocap up, no server: *fleet positions* (preview and apply the
position sync, then *Restart with the server*, because the server reads
`crazyflies.yaml` only when it starts). Server up: *check* until the `/all/*` services
exist, then *fly*. A launch is refused, with the reason, while ANY stack is up, mocap-only
included, on any ROS domain: a second launch would start a second mocap node on UDP 1511.

## The tabs

| Tab (keys `1`…`5`) | What it is |
|---|---|
| **Dashboard** | The cockpit above, and the only process view. |
| **System health** | The probe graph: [the health diagram](#the-health-diagram). |
| **Control** | One card per action, grouped Launch, Preflight, Fleet position, Flight, Commands, Parameters, Recovery, each with a *why* and a "how to read this command". |
| **Config** | `crazyflies.yaml` as a table (enable, URI, position, type, add or remove a drone), plus a raw editor for `crazyflies.yaml`, `motion_capture.yaml`, `server.yaml` and `teleop.yaml`. Every write is parse-checked, shown as a diff, backed up to `console/backups/`, and keeps the file's comments. The server reads `crazyflies.yaml` only at launch: restart it after a change. |
| **Command log** | The session; *Download as a shell script* writes it with a prelude (the two `source` lines as comments, then `cd <repo>`). **Usage across sessions** shows what was run, from where and how often. |

`Ctrl-K` or `/` opens a palette over every action, health check, config file, mission and
tab. `Enter` runs the highlighted action through the same confirm step as its button;
`Shift-Enter` opens its card. `r` re-runs every probe, `?` lists the keys, `Esc` closes
whatever is open. **E-STOP has no shortcut**, so a stray key never cuts the motors.

**Restart the console after updating it** or after `./scripts/build.sh`: the page reloads
from disk but the backend does not, so a reloaded page can hit routes the old process
lacks (an *out of date* banner says so), and a package built after the console started is
flagged **BUILT AFTER THIS CONSOLE STARTED** until you restart it from a sourced shell.

## GUI action → terminal command

Run the terminal equivalents from the repo root, in a sourced shell
([setup step 5](../01-setup.md#step-5-open-a-terminal-the-right-way)) with no conda.

- **Needs** is the action's precondition. `server stopped` means no crazyflie server may
  run, because only one process can own a Crazyradio. **It warns, it does not lock**: the
  button dims and the card and confirm dialog say why, but the backend still runs what you
  confirm.
- **confirm** means a modal shows the argv first. That happens for every action that
  moves drones or cuts motors, and for any action whose precondition is unmet.

`<angle brackets>` are card fields; the defaults shown are the card defaults. An empty
number field falls back to its default.

### Launch and recovery

| GUI path | Needs | Exact command | Notes |
|---|---|---|---|
| Launch → **Start the stack** | no stack running | `ros2 launch crazyflie launch.py backend:=cpp rviz:=True preflight:=True foxglove:=True teleop:=True mocap:=True gui:=False debug:=False` | Always all eight; `mocap_hostname:=<ip>` only when that field is set. `backend` is `cpp`, `cflib` or `sim`. No spaces around `:=`. |
| Launch → **Start mocap only (no server)** | no stack running | `ros2 launch crazyflie launch.py server:=False rviz:=True foxglove:=True` (+ `mocap_hostname:=<ip>`) | No server: nothing owns the radio, nothing can arm. The state the position sync wants. The launch's default `preflight:=True` still applies. |
| Launch → **Restart with the server** | any · confirm | `bash -c './console/stop_stack.sh && exec ros2 launch crazyflie launch.py <Start the stack's arguments>'` | Stops any stack (checking UDP 1511 is free), then starts the full one with *Start the stack*'s saved choices, backend included. One command, so no second mocap node can start in between. |
| Launch → **Start the simulator stack** | no stack running | `ros2 launch crazyflie launch.py backend:=sim` | Needs `./scripts/setup_sim_firmware.sh` once. |
| Launch → **Stop the stack** | any · confirm | `./console/stop_stack.sh`, or `--hard` to skip to SIGKILL | Signals launcher, server, mocap node, preflight GUI, bridge and RViz (SIGINT → SIGTERM → SIGKILL), then **checks UDP 1511 is released**: a bare Ctrl-C on `ros2 launch` often leaves the mocap node holding it. |
| Launch → **Rebuild the workspace** | any | `./scripts/build.sh [<package>]` | Restart the console afterwards. |
| Recovery → **Kill leftover mocap nodes** | any · confirm | `bash -c 'pkill -f motion_capture_tracking_node; sleep 1; pgrep -af motion_capture_tracking \|\| echo "clear"'` | Killing a `ros2 run` wrapper does not kill the node. |
| Recovery → **Kill a hung stack** | any · confirm | `bash -c 'pkill -f "ros2 launch crazyflie"; pkill -f crazyflie_server; pkill -f motion_capture_tracking_node; sleep 1; pgrep -af "crazyflie_server\|motion_capture_tracking" \|\| echo clear'` | The silent mid-connect hang and a wedged upload ignore SIGINT. |
| Recovery → **Restart the ros2 daemon** | any | `bash -c 'ros2 daemon stop; ros2 daemon start; ros2 daemon status'` | When `ros2 node list` is empty while nodes plainly run. |
| Recovery → **Show the ROS environment** | any | `bash -c 'echo "ROS_DISTRO=$ROS_DISTRO"; echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0 (default)}"; echo "RMW=${RMW_IMPLEMENTATION:-default}"; echo "python3=$(command -v python3)"; echo "AMENT_PREFIX_PATH=$AMENT_PREFIX_PATH" \| tr ":" "\n"'` | Most "I see no topics" is a domain mismatch, an unsourced overlay or a conda python. |

### Preflight (read-only; nothing moves)

| GUI path | Needs | Exact command |
|---|---|---|
| Preflight → **Scan every enabled drone** (Dashboard *Scan the fleet*) | server stopped | `bash -c 'for a in <enabled addresses from crazyflies.yaml>; do echo "== $a"; ros2 run crazyflie scan --address $a; done'`. In a terminal, use `./scripts/scan_fleet.sh`: it derives the list and prints GO / NO-GO (`--list` only prints it, `--all` adds disabled drones, `--yaml PATH` takes another file). |
| System health → **Scan the fleet** | server stopped | The same scan per enabled address, 25 s each, and it also checks that each reply's datarate matches the URI's, which `scan_fleet.sh` leaves to you. A datarate mismatch hangs the server forever. |
| Preflight → **Scan one address** | server stopped | `ros2 run crazyflie scan --address <0xE7E7E7E7xx>`; the list adds the factory address `0xE7E7E7E7E7`. |
| Preflight → **Is the Crazyradio plugged in?** | any | `bash -c 'lsusb \| grep -iE "crazyradio\|bitcraze\|1915:\|35d2:" \|\| echo "no Crazyradio on USB"'` |
| Preflight → **Is UDP 1511 clear?** | any | `bash -c 'ss -uanp \| grep ":1511" \|\| echo "nothing bound to 1511 (expected when the mocap node is not running)"'`. Two sockets: the mocap node starves. |
| Preflight → **Leftover mocap processes?** | any | `bash -c 'pgrep -af motion_capture_tracking \|\| echo "none (good)"'`. A leftover makes the next connect abort. |
| Preflight → **Which motion_capture_tracking resolves?** | any | `ros2 pkg prefix motion_capture_tracking`: must print this workspace's `install/`. |
| Preflight → **List running nodes** | any | `ros2 node list` |
| Preflight → **Are the /all/\* services up?** | any | `bash -c 'ros2 service list \| grep -E "/all/\|takeoff\|land\|go_to\|arm\|emergency"'`. No `/all/takeoff`: the server is stuck connecting. |
| Preflight → **Measure /poses rate** | any (until Stop) | `ros2 topic hz /poses --window 50`: expect ≈50 Hz. |
| Preflight → **Who publishes /poses?** | any | `ros2 topic info /poses --verbose`: 0 publishers is a local failure, not Motive. |
| Preflight → **Echo one onboard pose** / **status** / **link statistics** | any | `ros2 topic echo /<drone>/pose --once`, `.../status --once` (battery, supervisor bits, link: "won't arm" is usually answered here), `.../connection_statistics --once` |
| Preflight → **Read a battery over the radio** | server stopped | `ros2 run crazyflie battery --uri <that drone's uri>` (talks to the dongle directly). |
| Preflight → **Run a ground check** | any | `ros2 run <package> <script>`, for scripts that never command a drone (`plan_*`, `*.sh`, `color_led`, `set_param`), so no "area clear?" prompt. The planners live here. |

### Fleet position (Dashboard step 2)

| GUI path | Needs | Exact command |
|---|---|---|
| Fleet position → **Preview initial_position sync** | mocap running | `python3 scripts/sync_initial_positions.py --dry-run` |
| Fleet position → **Apply initial_position sync** | mocap running · confirm | `python3 scripts/sync_initial_positions.py --yes` |

Order: **Start mocap only** → Preview → Apply → **Restart with the server**, then run the
demo's planner. The script reads `/poses`, rewrites only the `initial_position` triples
(comments kept), and refuses on its own rules. The console never passes `--force`. The
procedure: [flight day, step 1](../02-flight-day.md#1-place-the-drones-and-record-where-they-are).

### Flight (these move drones)

| GUI path | Needs | Exact command |
|---|---|---|
| Flight → **Run a flight script** (Dashboard *Fly*) | server running · confirm | `ros2 run <package> <script>`, plus `--ros-args -p <name>:=<value>` per entry in the ROS-parameters field. The simulation-clock selector `auto` inserts `use_sim_time:=true` as the first `-p` exactly when the stack is the simulator (`/clock` present); `yes` / `no` force it. |
| Commands → **E-STOP (all drones)** | server running · confirm | `ros2 service call /all/emergency std_srvs/srv/Empty {}` |
| Commands → **Arm all** | server running · confirm | `ros2 service call /all/arm crazyflie_interfaces/srv/Arm '{arm: true}'` |
| Commands → **Disarm all** | server running | `ros2 service call /all/arm crazyflie_interfaces/srv/Arm '{arm: false}'` |
| Commands → **Takeoff (all)** | server running · confirm | `ros2 service call /all/takeoff crazyflie_interfaces/srv/Takeoff '{group_mask: 0, height: 0.5, duration: {sec: 3, nanosec: 0}}'` (height, duration editable) |
| Commands → **Land (all)** (Dashboard *Land all*) | server running · confirm | `ros2 service call /all/land crazyflie_interfaces/srv/Land '{group_mask: 0, height: 0.04, duration: {sec: 4, nanosec: 0}}'` (editable; longer is gentler) |
| Commands → **Takeoff (one drone)** | server running · confirm | `ros2 service call /<drone>/takeoff crazyflie_interfaces/srv/Takeoff '{group_mask: 0, height: 0.5, duration: {sec: 3, nanosec: 0}}'` (fixed) |
| Commands → **Land (one drone)** | server running · confirm | `ros2 service call /<drone>/land crazyflie_interfaces/srv/Land '{group_mask: 0, height: 0.04, duration: {sec: 4, nanosec: 0}}'` (fixed) |
| Commands → **Go to (one drone)** | server running · confirm | `ros2 service call /<drone>/go_to crazyflie_interfaces/srv/GoTo '{group_mask: 0, relative: true, goal: {x: 0.0, y: 0.0, z: 1.0}, yaw: 0.0, duration: {sec: 3, nanosec: 0}}'` |

- `duration` is a nested message, hence `{sec: 3, nanosec: 0}`; `group_mask: 0` is all
  groups.
- `GoTo.srv` comments `yaw` as degrees while `crazyflie_py` passes radians. Check before
  trusting a large value.
- The ROS-parameters field refuses anything not shaped `name:=value`. `ros2 run` accepts a
  misspelled `-p` silently, so `vip_mode:=manaul` would fly the default mode.

### Parameters and LED

| GUI path | Needs | Exact command |
|---|---|---|
| Parameters → **Reset the Kalman filter (all)** | server running | `ros2 param set /crazyflie_server all.params.kalman.resetEstimation 1` |
| Parameters → **Clear the Kalman reset flag** | server running | `ros2 param set /crazyflie_server all.params.kalman.resetEstimation 0`. A reset is both writes; the preflight GUI's `r` does both. |
| Parameters → **List server parameters** | server running | `bash -c 'ros2 param list /crazyflie_server \| head -n 200'` |
| Parameters → **Get a parameter** | server running | `ros2 param get /crazyflie_server <name>` |
| Parameters → **Set any parameter** | server running · confirm | `ros2 param set /crazyflie_server <name> <value>`: `all.params.<group>.<name>` broadcasts, `cfN.params.<group>.<name>` targets one drone ([runtime parameters](running.md#runtime-firmware-parameters)). |
| Parameters → **Set the Color LED deck** | server running | `./scripts/led.sh <n>` ([LED keys](running.md#color-led-deck--status-convention-and-manual-control)) |

### Console-only

| GUI path | What happens | Terminal equivalent |
|---|---|---|
| **Header E-STOP** | `POST /api/estop`: the `/all/emergency` call above, answered within 3 s. | The `ros2 service call` above, but you judge the outcome: it has no timeout and prints nothing against an unreachable server. |
| Output pane → **Stop** | SIGINT to the process group, then SIGTERM, then SIGKILL (6 / 4 / 2 s; a flight script gets 15 s after the SIGINT so its landing can finish). | `kill -INT -<pgid>`, or `./console/stop_stack.sh` for the stack |
| Output pane → **Kill** | SIGKILL. | `kill -KILL -<pgid>` |
| Output pane → **stdin line** | The text plus a newline to the child's pty. | The terminal you would have run it in |

Mission-window buttons (Start, gates, Abort & land, teleop):
[mission-window.md](mission-window.md#what-each-button-sends). Anything not in these
tables (`trace_cf:=all`, a gamepad) is a terminal job.

## The health diagram

![System health: the probe graph and one box's evidence](../img/console-health.png)

**1** the graph: one probe per box, laid out along the data path, dashed links moving
where data flows. **2** the selected box: what was measured, the command behind it, and
the fix. **3** *Scan the fleet*, the go/no-go check, which needs the radio free.

A box downstream of a hard failure turns grey ("blocked upstream"), so you look at the
cause. Boxes that do not apply (radio and mocap under `backend:=sim`) read "not
applicable". Errors in any output the console ran are matched against known signatures
and attached to their box. The box list is the rig's
[known issues](known-issues.md), made executable:

| Box | Probe | The failure it names |
|---|---|---|
| ROS 2 environment | `ros2` on `PATH`, `$ROS_DISTRO`, `$ROS_DOMAIN_ID` | Console started unsourced; a domain different from the stack's. |
| Workspace overlay | `install/` on `AMENT_PREFIX_PATH` | Built but not sourced: apt packages shadow the vendored ones. |
| Python interpreter | `python3` is `/usr/bin/python3`, no conda or venv | `No module named '_cffirmware'`, invalid message types. |
| Show packages built | every `crazyflie_py` package in `src/` against `install/` | A show never built, a new entry point or module not installed, a package built after the console started. Reads as `No executable found`. |
| Config files | `crazyflies.yaml` and `motion_capture.yaml` parse | A bad hand edit. |
| Fleet sanity | the config validators | Duplicate addresses, drones under 1 m apart, unknown type, two dongles under 2 channels apart, a log block over 26 B, a bad `initial_position`. In `motion_capture.yaml`: a pinned `hostname`, the closed-source parser, an `interface_ip` that is not `"auto"` (fail if not an IPv4 literal, warn on `0.0.0.0`, info when pinned). |
| Crazyradio dongle | `lsusb` for Bitcraze IDs | Dongle missing, or a udev/plugdev problem. |
| Drones answer radio | the scan, only when you press *Scan the fleet* with the server stopped | A dead drone or a datarate mismatch, **before** it hangs the server. Skipped (not red) while the server runs: `/all/*` up proves every drone answered. |
| Motive / NatNet | the UDP 1510 discovery broadcast `launch.py` uses | Motive not on this network, not streaming, or firewalled. A ping to the Motive PC proves nothing. |
| UDP 1511 | `ss -uanp \| grep ":1511"` | More than one socket: "mocap died". |
| Mocap driver build | `ros2 pkg prefix motion_capture_tracking` | The apt driver under `/opt/ros`: `/poses` never arrives. |
| motion_capture_tracking | in `ros2 node list` | Alive is not streaming: next box. |
| /poses stream | `ros2 topic info /poses`, then `ros2 topic hz /poses --window 20` | 0 publishers; publishers but no messages; under 30 Hz. |
| crazyflie_server | `ros2 node list` | Not launched, or died. |
| /all/\* services | `ros2 service list` | Server alive but blocked mid-connect: the classic silent hang. |
| one tile per drone | `ros2 topic list`, then `ros2 topic echo /cfN/status --once` | Never connected; no status; battery under 3.8 V (warn) / 3.7 V (fail); unicast latency over 10 ms; the supervisor state. |

The drone tile orders the supervisor words by what to clear first: **`E-STOPPED`**
(latched; only a battery re-plug clears it), **`CRASHED`**, **`FLIPPED`**, `FLYING`,
`armed`, `ready to arm`. Severity is the worst of them, so a low battery never downgrades
an `E-STOPPED` drone. The live probes rerun every 3 s, the rest every 30 s
([sweeps](../../console/README.md#health-sweeps)).

**Blind spots.** No box reads `/cfX/kalman_preflight`, the connection statistics or the
telemetry watchdog's log. A "link alive, log data dead" stall shows only as "no status
message", whose fix text points at the wrong cause; look in the server log and
`scripts/link_stall_recorder.py`. A server stuck in an upload wait shows as every drone
tile failing at once; Recovery → *Kill a hung stack* stops it, SIGINT does not. And a
probe is a moment: no red box is not proof of health.

## E-STOP, Stop and Abort

- **E-STOP** (header, every tab): one click, no confirmation, no tab switch. The banner
  says **confirmed** (with the latency) or **NOT CONFIRMED** with the reason within 3 s; a
  call still pending at 15 s is dropped so it cannot hit a server launched later. If it is
  not confirmed, use the preflight GUI's `e` or cut power. An e-stop from anywhere (the
  preflight GUI, a terminal, a script) also raises the banner.
- A confirmed e-stop latches every drone's supervisor LOCKED; only a battery re-plug
  clears it, and the tile reads `E-STOPPED`. The fleet e-stop still works when one
  drone's services are wedged: `/all/*` runs in its own callback group.
- **In the simulator, e-stop does nothing**: `crazyflie_sim` only logs that it is not
  implemented, and the banner says so. Land, or stop the script.
- **For a show, use the mission window's Abort & land, not Stop.** Abort sends one SIGINT
  (Ctrl-C once in a terminal). Stop escalates, and a SIGTERM during the show's landing
  kills the landing.

## Limits

- **A pty is not your terminal.** `sudo` prompts and programs that read `/dev/tty` are
  unreliable. `escort_teleop` works (it reads its own stdin raw). `teleop_xbox` needs a
  gamepad and `teleop:=False`: a terminal job.
- **Launch arguments with no field**: `trace_cf:=all` (per-second packet-trace summaries,
  read at connect), `crazyflies_yaml_file:=`, `motion_capture_yaml_file:=`,
  `teleop_yaml_file:=`, `rviz_config_file:=`. Use a terminal
  ([launch arguments](running.md#launch-arguments-crazyflie-launchpy)).
- **Per-drone cards list the enabled drones as of the last catalog build.** The catalog
  rebuilds when `crazyflies.yaml` changes; an open card is stale until the page refreshes.
- **The one-drone Takeoff and Land cards have fixed payloads.** Use Go to, or a terminal.
- **A card offers only what the catalog knows.** A flag added to a script later is not
  offered.

---

See also: [running.md](running.md) (the same operations as terminal procedure) ·
[troubleshooting.md](troubleshooting.md) · [mocap.md](mocap.md) ·
[known-issues.md](known-issues.md).

Full earlier text: `git show 678bac1:docs/rig/console.md`
