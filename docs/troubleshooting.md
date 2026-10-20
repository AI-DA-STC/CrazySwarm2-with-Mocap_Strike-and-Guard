# Troubleshooting

The problems people actually hit, most common first. The full list, with causes, is in
[details/troubleshooting.md](details/troubleshooting.md).

## Starting up

| What you see | What to do |
|---|---|
| The launch hangs, no error, and `ros2 service list` has no `/all/takeoff` | An enabled drone is not answering the radio. Run `./scripts/scan_fleet.sh`; switch it on, fix its address, or set it `enabled: false` in `crazyflies.yaml`. Kill the hung launch (Ctrl-C, then `pkill -9 -f crazyflie_server`). |
| `setup.sh` prints `ERROR` about `motion_capture_tracking` | The broken apt driver is installed. `sudo apt remove ros-$ROS_DISTRO-motion-capture-tracking ros-$ROS_DISTRO-motion-capture-tracking-interfaces`, then `./scripts/build.sh` and re-source. |
| Build fails in `natnet_ros2`: `NatNet SDK not found` | The first build downloads OptiTrack's NatNet SDK. Build once on a network with internet (the Motive network has none). |
| `No module named 'cffirmware'` (simulator) | Run `./scripts/setup_sim_firmware.sh`, then open a new terminal. |
| Strange Python errors, `invalid message type` | conda is active. `conda deactivate`, open a new terminal. |
| You see drone commands or nodes you did not start | Someone else in the lab uses the same ROS domain. Set your own `export ROS_DOMAIN_ID=<n>` in every terminal. |

## Cameras (mocap)

| What you see | What to do |
|---|---|
| `mocap [Hz]` is 0, or `ros2 topic hz /poses` prints nothing | Check Motive is streaming **Multicast**. Check nothing else holds the camera port: `ss -uanp \| grep :1511` must show at most one socket; kill any leftover process, then relaunch. |
| Launch stops with `no Motive answered a NatNet discovery ping` | Your laptop is not on the Motive network, or Motive is not streaming. Fix the network, or give the address: `mocap_hostname:=<ip>`. |
| A drone is missing from `/poses` | Its rigid body in Motive is switched off or named differently from `crazyflies.yaml`. |
| Red "ORIENTATION MISALIGNED" banner, or a big `err.yaw` | The rigid body was created with the drone pointing the wrong way. Point the nose along +X and recreate it. Do not fly: this one causes fly-aways. |

## The show refuses or stops (escort)

| What you see | What to do |
|---|---|
| `PLACEMENT CHECK FAILED` | A drone is not where `crazyflies.yaml` says. Move it, or re-run `sync_initial_positions.py`. |
| `gather legs close to ...` | Two drones would pass too close while forming the ring. Re-place them on the marks from `plan_escort --marks` and sync again. |
| Nothing arms, no error | The drones are locked after an E-STOP. Unplug and re-plug every battery. |
| The defenders turn cyan and stop following | The DJI left its box. Fly it back toward the middle; they resume on their own. |
| A drone lands by itself | The cameras lost it. Check its markers and the camera view, then fly again. |
| Simulator: the second run hangs at "gathering onto the ring" | Restart the `ros2 launch` between simulator runs. |

## STL game

| What you see | What to do |
|---|---|
| `plan_stl` ends `PLAN REFUSED` on every seed | Expected with the shipped game: one defender passes 10.8 cm from a landing intruder. See [stl/how-it-works.md](stl/how-it-works.md#honest-limits). |
| `start move: closest 0.0x m` | The drones are not on their start slots, so their first move crosses. Re-place them on the slots and sync the marks. |
| `not on the server: cf10, ...` | The intruders are not enabled, or the second Crazyradio is not plugged in. Enable all ten in `crazyflies.yaml`, plug in both radios, scan, relaunch. |
| Every other launch now hangs | cf10-cf14 are still enabled from an STL session. Set them back to `enabled: false`. |

## The preflight window

| What you see | What to do |
|---|---|
| It never opens | `sudo apt install python3-tk libxcb-cursor0`; if it still fails, see [details/troubleshooting.md](details/troubleshooting.md#preflight-gui). |
| A drone is missing from it | That drone is `enabled: false` in `crazyflies.yaml`. |

## Quick checks

```bash
./scripts/scan_fleet.sh --list         # which drones are enabled, and their addresses
ros2 topic hz /poses                   # camera data: about 50 Hz expected
ros2 topic echo /cf1/status --once     # battery, link, and the "locked" flag
```

Still stuck: [details/troubleshooting.md](details/troubleshooting.md), then
[details/known-issues.md](details/known-issues.md) for the long story behind each one.
