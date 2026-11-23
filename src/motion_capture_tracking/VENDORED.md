# Vendored: motion_capture_tracking (do NOT install the apt package)

Source: https://github.com/IMRCLab/motion_capture_tracking, branch `ros2`,
commit `64d3af2` (2026-07-21), with `deps/libmotioncapture` at `24321e4`
(2026-07-17, "Revert 'vibecoded troubleshooting from chatgpt'").
Nested `.git` metadata was stripped; this is a plain copy.

## Why it is vendored

- The apt release `ros-humble-motion-capture-tracking 1.0.9` (and the 1.0.9
  build queued for Jazzy) pins a libmotioncapture commit that hard-codes a
  TU Berlin interface address, `141.23.110.162`, into the NatNet data-socket
  `bind()` / `join_group()`. On any other machine the node either aborts
  (exit -6, "set_option: No such device") or silently never binds and
  publishes an empty `/poses` forever. Upstream reverted it on 2026-07-17 but
  no fixed release exists.
- Every apt version (1.0.6 and 1.0.9) mis-parses the NatNet 4.2 model
  definition sent by Motive 3.4.1 and can segfault after the handshake,
  depending on which rigid bodies Motive streams.

Building from this tree gives Ubuntu 22.04 / Humble and 24.04 / Jazzy the same
working parser. `scripts/install_deps.sh` removes the apt package so it cannot
shadow this build.

## Local patches applied on top of upstream

`patches/0007-node-interface-ip.patch` (applies after 0006) — libmotioncapture's
OptiTrack driver joins the NatNet multicast group on `cfg["interface_ip"]`, but
the upstream node never puts that key in `cfg`, so the join always used
`0.0.0.0`, i.e. the interface of the default route. With Wi-Fi (internet) and the
wire (Motive) both up, NetworkManager can rank Wi-Fi as the default route, and
then `/poses` stays silent while ping and NatNet discovery still work (seen on
2026-11-23). The patch declares an `interface_ip` parameter (default `0.0.0.0` =
upstream behaviour), forwards it, and prints the interface it joins on. The rig
sets `interface_ip: "auto"` in `crazyflie/config/motion_capture.yaml`; the
crazyflie `launch.py` turns that into the address the route to Motive leaves
from. Applies with:

    git apply --directory=src/motion_capture_tracking \
        src/motion_capture_tracking/patches/0007-node-interface-ip.patch

`patches/0006-node-max-rate.patch` — upstream publishes `/poses`, `/tf` and
`pointCloud` (and runs the marker tracker) on every Motive frame. When Motive
streams at 240 Hz for other aircraft sharing the volume (the Starlings, from
2026-11-17), every one of those becomes a Crazyradio broadcast in
`crazyflie_server`. The patch adds a `max_rate` parameter (Hz, default 0 = every
frame, i.e. upstream behaviour): every frame is still read off the socket so
nothing queues, but processing and publishing run on a fixed schedule that
averages at most `max_rate` and never bursts to catch up after a gap. A frame may
be up to half a period early, so input at or below `max_rate` passes untouched
despite jitter; nothing is ever repeated. The rig sets `max_rate: 55.0` in
`crazyflie/config/motion_capture.yaml`. Applies with:

    git apply --directory=src/motion_capture_tracking \
        src/motion_capture_tracking/patches/0006-node-max-rate.patch

`patches/0005-libmotioncapture-natnet-connect-timeout-and-logging.patch` —
upstream blocks forever in `connect()` when Motive does not answer on UDP 1510
(stale address after a DHCP move, streaming off, Windows firewall): the node
stays alive, prints nothing, never binds 1511, never creates `/poses`. The
patch `poll()`s the command socket for 5 s before each reply (SO_RCVTIMEO does
not work: Boost.Asio's sync receive retries on EAGAIN) and throws a
`std::runtime_error` naming the address and the likely causes, and logs
`NatNet: connecting to ...`, the Motive name / NatNet version / data port /
transport, and the streamed rigid-body names after connect. Applies with:

    git apply --directory=src/motion_capture_tracking/motion_capture_tracking/deps/libmotioncapture \
        src/motion_capture_tracking/patches/0005-libmotioncapture-natnet-connect-timeout-and-logging.patch

`patches/0004-node-humble-compatible-tf-broadcaster.patch` — upstream commit
`a17396d` ("fix build error on rolling") constructs the TF broadcaster through
`rclcpp::node_interfaces::NodeInterfaces`. That API reached Humble only in
`ros-humble-rclcpp` 16.0.17 (2025-12 backport), so a 22.04 laptop with an older
rclcpp (verified: 16.0.14 fails, patched build succeeds)
fails with `rclcpp/node_interfaces/node_interfaces.hpp: No such file or
directory`. We target Humble + Jazzy, not Rolling, so the vendored node keeps
the classic `tf2_ros::TransformBroadcaster(node)` constructor. Applies with:

    git apply --directory=src/motion_capture_tracking \
        src/motion_capture_tracking/patches/0004-node-humble-compatible-tf-broadcaster.patch


`patches/0003-libmotioncapture-natnet-4.2-modeldef-segfault.patch`
(copied into this directory) — for NatNet >= 4.1 use each dataset's
`description_size` as the authoritative boundary in `parseModelDef`, read only
rigid-body name / ID / parent / offsets, skip the rest.
Applies with:

    git apply --directory=src/motion_capture_tracking/motion_capture_tracking/deps/libmotioncapture \
        src/motion_capture_tracking/patches/0003-libmotioncapture-natnet-4.2-modeldef-segfault.patch

## Updating

Re-clone upstream at a newer commit, re-apply every patch in `patches/` in number order, verify
`grep -r 141.23.110.162 motion_capture_tracking/deps/libmotioncapture/src`
prints nothing, strip `.git` entries, rebuild on BOTH a 22.04/Humble and a
24.04/Jazzy machine (a stock `ros:humble` Docker image is enough for the build
check), and confirm `/poses` streams.
