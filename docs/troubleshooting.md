# Troubleshooting

The problems people actually hit, most common first. Each "More" link goes to the full
entry in [rig/troubleshooting.md](rig/troubleshooting.md).

## Starting up

| What you see | What to do | More |
|---|---|---|
| The launch hangs with no error; `ros2 service list` has no `/all/takeoff` | A drone is not answering. Run `./scripts/scan_fleet.sh`; switch it on, fix its address, or set it `enabled: false` in `crazyflies.yaml`. Kill the hung launch: Ctrl-C, then `pkill -9 -f crazyflie_server`. | [radio](rig/troubleshooting.md#crazyradio--drones) |
| `setup.sh` prints `ERROR` about `motion_capture_tracking` | `sudo apt remove ros-$ROS_DISTRO-motion-capture-tracking ros-$ROS_DISTRO-motion-capture-tracking-interfaces`, then `./scripts/build.sh` and re-source. | [build](rig/troubleshooting.md#setup--build) |
| Build fails in `natnet_ros2`: `NatNet SDK not found` | Build once on a network with internet (the Motive network has none). | [build](rig/troubleshooting.md#setup--build) |
| `No module named 'cffirmware'` (simulator) | `./scripts/setup_sim_firmware.sh`, then a new terminal. | [build](rig/troubleshooting.md#setup--build) |
| Strange Python errors, `invalid message type` | `conda deactivate`, then a new terminal. | [build](rig/troubleshooting.md#setup--build) |
| Drone commands or nodes you did not start | `export ROS_DOMAIN_ID=<n>` (your own number) in every terminal. | [ROS](rig/troubleshooting.md#ros-2--dds--parameters) |

## Cameras (mocap)

| What you see | What to do | More |
|---|---|---|
| `mocap [Hz]` is 0, or `ros2 topic hz /poses` prints nothing | Check Motive streams **Multicast**. `ss -uanp \| grep :1511` must show at most one socket: kill any leftover, relaunch. | [mocap](rig/troubleshooting.md#mocap-pipeline) |
| Launch stops: `no Motive answered a NatNet discovery ping` | Join the Motive network and check Motive is streaming, or give the address: `mocap_hostname:=<ip>`. | [mocap](rig/troubleshooting.md#mocap-pipeline) |
| `/poses` silent with Wi-Fi and the cable both connected | The launch line `mocap: NatNet multicast joined on <ip>` must show this laptop's Motive-network address. Keep `interface_ip: "auto"` in `motion_capture.yaml`, or pass `mocap_interface_ip:=<that address>`. | [mocap](rig/troubleshooting.md#mocap-pipeline) |
| A drone is missing from `/poses` | Switch its rigid body on in Motive, named as in `crazyflies.yaml`. | [mocap](rig/troubleshooting.md#mocap-pipeline) |
| Red "ORIENTATION MISALIGNED" banner, or a big `err.yaw` | **Do not fly** (fly-away risk). Point the nose along +X and recreate the rigid body. | [mocap](rig/troubleshooting.md#mocap-pipeline) |

## The show refuses or stops (escort)

| What you see | What to do |
|---|---|
| `PLACEMENT CHECK FAILED` | Move the drone to where `crazyflies.yaml` says, or re-run `sync_initial_positions.py`. |
| `gather legs close to ...` | Re-place the drones on the marks from `plan_escort --marks`, sync again. |
| Nothing arms, no error | The drones are locked after an E-STOP: unplug and re-plug every battery. |
| The defenders turn cyan and stop following | The DJI left its box. Fly it back toward the middle; they resume by themselves. |
| A drone lands by itself | The cameras lost it. Check its markers and the camera view, fly again. |
| Simulator: the second run hangs at "gathering onto the ring" | Restart the `ros2 launch` between simulator runs. |

## STL game

| What you see | What to do |
|---|---|
| `plan_stl` ends `PLAN REFUSED` on every seed | Expected with the shipped game: [stl/how-it-works.md](stl/how-it-works.md#honest-limits). |
| `start move: closest 0.0x m` | Put the drones back on their start slots and sync the marks. |
| `not on the server: cf10, ...` | Enable the intruders in `crazyflies.yaml`, plug in both Crazyradios, scan, relaunch. |
| Launches hang after an STL session | Drones it enabled are still `enabled: true`. Scan, and set the ones not flying back to `enabled: false`. |

## Guard

| What you see | What to do |
|---|---|
| Abort at the start gate: `CONTAINMENT cf1: no mocap for 1.1 s` | The cameras lost that drone. Check its markers and the camera view, fly again. |
| Abort in the match: `cf10: 0.64 m from where it was commanded for 0.9 s` | The drone ran late. Check the show's header says `controller mellinger`, not `pid`. To fly PID, fly 0.6 m/s (`-p v_max_defense:=0.6 -p v_max_attack:=0.6`). Why: [guard/how-it-works.md](guard/how-it-works.md#why-the-drones-run-late-and-what-to-do-about-it). |
| `no /poses entry for 'operator'` right after the header | Set the VIP to the DJI's rigid-body name in Motive (`-p vip_name:=<name>`, or the console's VIP field). |
| `FORM-UP NOT A FAIR START yet: attacker ... inside reach` | The pilot flies the DJI further from the attackers until the show prints `fair start`; then press START. |
| The match pauses and every drone holds | A near miss: the safety layer keeps them apart and play resumes by itself; if it does not clear in a few seconds, everything lands. Expected. |

## The preflight window

| What you see | What to do | More |
|---|---|---|
| It never opens | `sudo apt install python3-tk libxcb-cursor0`. | [GUI](rig/troubleshooting.md#preflight-gui) |
| A drone is missing from it | That drone is `enabled: false` in `crazyflies.yaml`. | [GUI](rig/troubleshooting.md#preflight-gui) |

## Quick checks

```bash
./scripts/scan_fleet.sh --list         # which drones are enabled, and their addresses
ros2 topic hz /poses                   # camera data: about 50 Hz expected
ros2 topic echo /cf1/status --once     # battery, link, and the "locked" flag
```

Still stuck: [rig/troubleshooting.md](rig/troubleshooting.md); the evidence behind each
problem is in [rig/known-issues.md](rig/known-issues.md).
