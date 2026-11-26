# Guard clips: how the simulator footage is made

The clips in [../how-it-works.md](../how-it-works.md) are real simulator matches in the
mission console's 3D view, made by `scripts/footage/`, so they can be re-made when a
strategy changes. For a **hardware** flight, see [flight-replay.md](flight-replay.md).

## Make them again

```bash
sudo apt install xvfb                 # once: the off-screen display
scripts/footage/rig.sh up             # display, console, bridge, Chrome: private domain 87
scripts/footage/clips.sh              # all clips, ~4 min each (or: clips.sh zone flood)
#   FILM_ONLY=1 clips.sh ...  re-films existing bags (a new camera or console fix), no flying
#   look at ~/.cache/guard-footage/clips/<name>.sheet.png, then:
CUT_ONLY=1 PUBLISH=1 scripts/footage/clips.sh    # copy the WebPs into docs/img/guard/
scripts/footage/rig.sh down
```

Nothing touches the lab or your stack: `ROS_DOMAIN_ID` 87, its own console (port 8178,
with its own usage log and flight-log folder), foxglove bridge (127.0.0.1:8799) and Chrome
on display `:99`, all set in `scripts/footage/common.sh`. `clips.tsv` has one line per clip
(the mission options, any other `guard_show` parameter as `"extra"`, title, description).

## One clip, step by step

1. **Fly** (`take.sh`): a fresh simulator stack; the show starts through the console's Run
   API (the mission window's Start button), unpaced; `/tf` and `/guard/markers` are bagged.
2. **Film** (`film.sh`): the bag replays into the console **at half speed**, the 3D scene is
   captured and sped back up 2x.
3. **Camera** (`camera.sh`): behind the attackers (from -x, +y), set by mouse drags over
   Chrome's DevTools port (`cdp_drag.py`), since the scene has no camera API.
4. **Cut** (`cut.sh`): from `MATCH LIVE` to seven seconds after the result, a title bar and
   the legend (`overlay.py`); a WebP for the docs (GitHub shows it inline, an MP4 only as a
   link), an MP4 and a contact sheet.

The console runs with `&clean=1` ([mission-window.md](../../rig/mission-window.md)): no
trails, parking marks, escort circle or overlays.

## Why the half-speed replay

Measured 2026-11-16 with `smoothness.py` (frames that really change):

| Setup | Real picture changes |
|---|---|
| Chrome on Xvfb, software WebGL, live sim | ~3 per second (6.6 cores busy) |
| Same, WebGL on the GPU (ANGLE on Vulkan) | ~7.6 per second, at any window size |
| GPU, bag replayed at half speed, sped up 2x | ~29 per second |

The GPU bottleneck is copying each frame back to the X server on one thread, so a smaller
window or power mode does not help; replaying slower does. Markers live 1 s (keep-out
bubbles 0.3 s) and are re-sent several times a second, so half speed draws them as live.
Trails would cover half as much match time, one reason clean mode drops them.

## Seeds, and where the simulator disagrees

Each seed was picked from `plan_guard`, 10 seeds per rule set and pairing (800 matches),
as the policy's typical outcome. The simulator flies the real stack (Mellinger, the
server, its physics) and `plan_guard` a stand-in, so a close match can go the other way:

- **direct v shell, tag:** offline the attack wins every seed in about 3 s; in the
  simulator the shell took all three out in 3.9 s.
- **wolfpack v shell, pressure:** offline the attack won 4 of 10; in the simulator the
  shell won both seeds tried (2 and 8) without losing a drone. So the clip is against
  **zone** (offline the attack wins all 10): it downs the lone defender at 3.4 s and strikes
  at 6.1 s.

**The one offline safety failure:** zone v coordinated, zone_pressure, seed 4: stand-ins
D1/A3 reached exactly the 0.35 m floor (1.00 of it). Not investigated.

## Traps hit on the way

- `ros2 bag record` under `setsid` once ignored SIGINT and recorded for 25 minutes; now
  `common.sh`'s `stop_group` escalates to TERM and KILL, and the take stops if the recorder
  survives.
- The 3D view rebuilt every label on every marker message, so labels flickered at 10 Hz
  (live too); `scene.mjs` now updates them in place. Trails-off missed late-appearing
  drones; fixed the same day.
- A `while read` loop over `clips.tsv` lost lines to `ros2` and `curl` reading stdin; the
  list is read on its own file descriptor.

Full earlier text: `git show 678bac1:docs/guard/details/footage.md`.
