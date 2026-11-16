# Guard clips: how the simulator footage is made

The animated clips in [guard/how-it-works.md](../guard/how-it-works.md) (one per strategy,
plus two rule sets) are real simulator matches, seen in the mission console's 3D view.
Everything that makes them is in `scripts/footage/`, so they can be made again when a
strategy changes. This page is how, and why it is built the way it is.

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

Nothing touches the lab or a stack you have up: the simulator runs on `ROS_DOMAIN_ID` 87,
with its own console (port 8178, with its own usage log and flight-log folder), its own
foxglove bridge (127.0.0.1:8799) and a Chrome on display `:99`. Every one of those is an
environment variable in `scripts/footage/common.sh`.

`clips.tsv` lists the clips: the mission options (strategies, rules, seed, and any other
`guard_show` parameter as `"extra"`), the title and the one-line description. A new
strategy is a new line.

## One clip, step by step

1. **Fly** (`take.sh`). A fresh simulator stack; the show is started through the
   console's own Run API, the same call as the mission window's Start button, unpaced.
   `/tf` and `/guard/markers` are bagged.
2. **Film** (`film.sh`). The bag is replayed into the console **at half speed**, the 3D
   scene is captured, and the capture is sped back up 2x.
3. **Camera** (`camera.sh`). Behind the attackers (from -x, +y), so they are seen
   staging and striking away from the viewer. The scene has no camera API, so the
   camera is set by mouse drags sent over Chrome's DevTools port (`cdp_drag.py`).
4. **Cut** (`cut.sh`). From `MATCH LIVE` to seven seconds after the result, a title bar
   on top and the legend (`overlay.py`) underneath; WebP for the docs (GitHub shows it
   inline; an MP4 in the repository only shows as a link), an MP4 and a contact sheet.

The console runs with `&clean=1` ([mission-window.md](mission-window.md)): no trails,
parking marks, escort circle or console overlays.

## Why the half-speed replay

Measured 2026-11-16 with `smoothness.py`, which counts frames that really change:

| Setup | Real picture changes |
|---|---|
| Chrome on Xvfb, software WebGL, live sim | ~3 per second (6.6 cores busy) |
| Same, WebGL on the GPU (ANGLE on Vulkan) | ~7.6 per second, at any window size |
| GPU, bag replayed at half speed, sped up 2x | ~29 per second |

On the GPU the bottleneck is copying each frame back to the X server, on one thread, so
neither a smaller window nor the laptop's power mode helps. Replaying slower does. The
guard's markers live 1 s (keep-out bubbles 0.3 s) and are re-sent several times a second,
so half speed draws them exactly as live. Trails would cover half as much match time,
which is one reason clean mode drops them.

## Seeds, and where the simulator disagrees

Each clip's seed was picked from a `plan_guard` run of 10 seeds for every rule set and
pairing (800 offline matches, all safe but one, see below), choosing the policy's typical
outcome. The simulator flies the real stack (Mellinger, the server, the sim's physics);
`plan_guard` uses a first-order lag as a stand-in, so a close match can go the other
way. Seen while making these clips:

- **direct v shell, tag:** offline the attack wins every seed in about 3 s; in the
  simulator the shell took all three out in 3.9 s. A 3-second match is decided by a
  fraction of a second.
- **wolfpack v shell, pressure:** offline the attack won 4 of 10, downing defenders on
  the way; in the simulator the shell won both seeds tried (2 and 8) without losing one.
  So the wolfpack clip is against **zone** under pressure (offline the attack wins all
  10): there, it downs the lone defender at 3.4 s and strikes at 6.1 s.

**The one offline safety failure:** zone v coordinated under zone_pressure, seed 4: two
stand-in aircraft (D1/A3) reached exactly the 0.35 m floor (1.00 of it). Every other
cell of the matrix stayed outside it. Not investigated.

## Traps hit on the way

- `ros2 bag record` started under `setsid` ignored SIGINT once and kept recording for
  25 minutes, including the replays meant to film it, so its own playback never ended.
  `common.sh`'s `stop_group` waits, escalates to TERM and KILL, and the take stops if
  the recorder survives.
- The console's 3D view rebuilt every text label on every marker message, so labels
  flickered at 10 Hz (live too, not only in recordings). Fixed in `scene.mjs`: labels
  are updated in place. Switching trails off also missed drones that appeared later;
  fixed the same day.
- A `while read` loop over `clips.tsv` lost its lines to the `ros2` and `curl` calls
  inside it reading stdin; the list is read on its own file descriptor.
