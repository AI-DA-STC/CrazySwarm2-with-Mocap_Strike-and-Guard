# Radio link and pose delivery: the 2026-11-17 session

What went wrong on 17 November 2026 when the guard game was set up to fly again, what was
measured, what was ruled out, and what to try next, in order. Nothing flew a match that day:
one take-off (16:54) aborted itself four seconds after lifting, because the show had no fresh
pose for any drone or the VIP.

**Resolved later the same day: the Crazyradio firmware.** After both radios went to 5.5
(recommendation 3) the links matched 11-06: all seven connected in 28 s, 46 % of replies
acknowledged, 13 "received more than sent" lines a minute, and pose gaps over 100 ms in
2-3 seconds a minute; several matches flew without trouble. (Correction: the server's
`Motion capture rate off (#: N, Avg/Min/Max)` counts N intervals OUTSIDE the 40-60 Hz band,
with rates in Hz; it is not the number of poses received. The figures below use the gap
measure, Min under 10 Hz.)

Status when this was first written: **unresolved.** Two separate problems, neither fixed. Do not fly
until the numbers in [How to tell it is fixed](#how-to-tell-it-is-fixed) are back near 11-06.

## The two problems

1. **The radio link fails in one direction.** The drones hear the laptop (they report
   -39 to -72 dBm), but only 2-30 % of their replies come back (11-06: 40-47 %). The
   Crazyradio retries every unacknowledged packet, so the radios spend their time
   resending, and the poses the server forwards to the drones queue behind the retries.
   Symptoms: slow connects, status missing for seconds at a time, gaps of over 100 ms
   between poses at the server in about 15 seconds of every minute (some over 500 ms),
   stutter in the air.
2. **Delivery between processes on the laptop is unreliable.** The mocap node publishes an
   even 50 Hz, but other processes on the same laptop receive it with gaps (the 16:54 bag
   recorder: gaps up to 1.6 s, 41.7 Hz on average). Every new ROS process takes 12-23 s to
   start talking (the show printed its header 1.8 s after launch on 11-06); one guard show
   hung for more than 12 minutes before its first line. The 16:54 abort is this problem:
   the show's own copy of `/poses` was stale while the recorder was receiving.

A note on one log line that looked like a third transmitter: `Unexpected number of unicast
packets. Sent: 0. Received: 115`. The drone's receive count includes every copy the
Crazyradio resends when an acknowledgement is lost, while the server counts the packet once.
A link that fails one way therefore makes the drone "receive more than was sent". It rose
from 7-11 a minute (11-06) to 1,400-1,600 a minute (16:15, radios plugged in directly), with
nobody else using a Crazyradio. Read it as a measure of lost acknowledgements, not as proof
of a second radio.

## What was measured

| | 11-06 (flew a clean DJI match) | 17-11, hub | 17-11, radios plugged in directly |
|---|---|---|---|
| All 7 drones connected after | 27-29 s | 95-184 s | 309 s |
| Replies acknowledged | 40-47 % | 8-30 % | 2 % (one drone 46 %) |
| "Received more than sent" lines a minute | 7-11 | 150-227 | about 1,400-1,600 |
| Seconds a minute with a pose gap over 100 ms at the server | 0.8-2.1 | 14.5-15.8 | 5.9 |
| Show start to its first line | 1.8 s | 35 s to more than 12 min | |

All from the server logs in `~/.ros/log/crazyflie_server_*.log` and the flight logs in
`~/.ros/flight_logs/`. The one-liner at the end of this page recomputes them.

## Ruled out, with the evidence

| Suspect | Why it is not the cause |
|---|---|
| Server code or config | Binary unchanged since 11-05; the only `crazyflies.yaml` change since 11-06 removed lines that were already commented out |
| Drone firmware | Every drone reports parameter TOC CRC 3235840321, the same as 11-06 |
| Laptop Wi-Fi | On 5 GHz (channel 52); the 2.4 GHz scan found no Wi-Fi above 2.472 GHz |
| Laptop Bluetooth | Powered off |
| USB power or resets | Radios powered and active, no resets since the 15:05 wake-up |
| The USB hub | Moving both radios to separate laptop ports made it worse, not better |
| The console polling | It starts as many `ros2` processes as on 11-06 (164 against 183 in five minutes) |
| The Starlings | Powered off by a teammate; the links recovered briefly, then failed again |
| AirStack and its ground station | Down and off |
| Another Crazyflie user | None in the room |
| The wireless charging pods | The user has flown off them before. All drones now report "charging/charged, on charger" where 11-06 read "on battery"; the supervisor bits are identical (513: can be armed) |
| The mocap rate | Motive at 240 Hz made it worse and is now limited (below), but the failures continued at 50 Hz |

## What was changed that day (all uncommitted at the time of writing)

- `crazyflies.yaml`: `initial_position` re-synced twice from `/poses` (the attackers were
  moved so the cameras could see them on the pods, then the defenders were pulled in so
  `plan_guard` passes). `plan_guard` passed on the final marks under tag and pressure at
  0.6 m/s; the matches came out one-sided (tag: defence 12/12; pressure: attack 12/12).
- The mocap node now caps `/poses` at 55 Hz: `max_rate: 55.0` in
  `crazyflie/config/motion_capture.yaml`, vendored patch 0006
  (`src/motion_capture_tracking/VENDORED.md`, [mocap.md](mocap.md) section 3). It only steps
  down: at Motive's 50 Hz every frame passes, at 240 Hz it gives 55, and it never repeats a
  frame. `max_rate: 0` turns it off.

## Recommendations, in order

Do one at a time, start the stack after each, and compare the numbers with the table above.

1. **Reboot the laptop** (or, at the least: stop the stack and the console, run
   `fastdds shm clean` and `ros2 daemon stop`, then restart them). On 17-11, 57 abandoned
   Fast DDS shared-memory files sat in `/dev/shm`, left by processes killed since 14:45 (the
   console stops with SIGKILL). Leftovers like these are known to slow down and drop delivery
   between processes on one machine: the likely cause of problem 2. Every run that day also
   came after a 15:03 suspend and resume, which reset the USB bus and both radios; a reboot
   clears that too, and applies the static Motive-LAN address a teammate assigned.
2. **Move the radios away from the laptop.** A USB extension cable, 1-2 m from the laptop and
   its charger, raised. Plugging them in directly took replies from 8-30 % to 2 %: reception
   gets worse the closer the radios are to the laptop. As a quick test, also try a minute with
   the charger unplugged.
3. **Update both Crazyradio firmwares to the same release (5.5).** The two radios ran
   different versions: serial 62C8E949226411C0 on **5.1, a release Bitcraze has retired**
   ("≥5.2 should be used instead"; 5.2 fixed malformed USB replies in 5.1's new inline
   mode), and serial F6B6CCA0D55F5070 on 5.4 (USB bcdDevice 5.01 / 5.04 = release 5.1 / 5.4).
   This matters here: `crazyflie-link-cpp` (`CrazyradioThread.cpp`) switches inline mode on for
   any Crazyradio 2.0 on 5.1 or newer, so the buggy path was in use. Updating does not touch
   the drones (they keep firmware, channel, rate and address). Stop the stack first (the
   server holds both radios). The releases on github.com/bitcraze/crazyradio2-firmware ship one
   file each, `crazyradio2-<version>.uf2`, the same kind the radios already run. Flash: hold
   the button while plugging the radio in (LED pulses red), a drive appears; copy its
   `CURRENT.UF2` off first as a backup, then copy the new file onto it. Files, checksums and
   backups: `~/crazyradio_firmware/` (README inside). Roll back the same way with the backup.
   **Done 17-11 ~17:15: both radios on 5.5**, backups taken. The official 5.5 build carries the
   version string 5.4.0, so a 5.5 radio reports **5.04** over USB; only reading `CURRENT.UF2` in
   bootloader mode tells 5.4 from 5.5. Link numbers after the update: not yet measured.
4. **Less telemetry while flying.** Each drone sends its pose at 10 Hz, the preflight log
   (`kalman_preflight`) at 5 Hz and status at 1 Hz, all on the direction that is failing.
   Turning the preflight log down or off for flights frees return traffic (edit with the
   `config-editor` agent; it knows the log-block limits).
5. **Only if the links are still bad: drop the data rate from 2M to 1M.** A lower rate
   receives better in noise; the capacity left is enough for these loads. No reflash: in
   cfclient, connect at the current URI, **Connect -> Configure 2.x**, set 1M, keep channel
   and address, Write, then power-cycle the drone (the rate takes effect after a restart).
   Then change `/2M/` to `/1M/` in that drone's URI in `crazyflies.yaml` (or the server hangs
   at launch on the first drone it cannot reach). Change every drone on one radio together
   (one radio serves all drones with its `radio://N`); the attackers' radio first, the
   defenders' as the comparison. Run `./scripts/scan_fleet.sh` before the stack. Undo with the
   same steps. The two channels stay well apart at 1M.
6. **Then channels.** Same cfclient dialog, same URI edit. Only once a measurement shows a
   quieter channel; the Wi-Fi scan found nothing near the current ones, and it cannot see
   Bluetooth, the DJI remote or electrical noise.

Things not to do:

- **Do not raise Motive's rate for the Crazyflies.** Mocap was healthy up to the server; every
  pose forwarded becomes another radio broadcast on a link that is already failing. 50 Hz is
  what the rig flies on. If the Starlings need 240 Hz, the 55 Hz limit already protects the
  Crazyflie side.
- **cfclient's own settings do not affect the stack.** The server uses its own link library;
  cfclient matters here only as the tool that writes settings onto drones and radios.

## How to tell it is fixed

After the stack connects, all of these near the 11-06 column: all drones connected within
about 30 s, 40 % or more of replies acknowledged, fewer than 20 "received more than sent"
lines a minute, at most a few seconds a minute of starved mocap, and a show that prints its
header within a few seconds. Then fly 1 drone, then the match.

Recompute from the newest server log (replace the file to look at another run):

```bash
f=$(ls -t ~/.ros/log/crazyflie_server_*.log | head -1)
grep -E "\] Memories:" $f | awk -F'[][]' 'NR==1{s=$4} {printf "%.0fs ", $4-s} END{print "(connects)"}'
awk -F'[][]' 'NR==1{t0=$4} {t=$4}
/Low unicast receive rate/ { match($0,/Sent: [0-9]+\. Received: [0-9]+/); x=substr($0,RSTART,RLENGTH); split(x,a,/[^0-9]+/); su+=a[2]; re+=a[3] }
/Unexpected number of unicast packets/ {u++}
/Motion capture rate off/ { match($0,/Min: [0-9.]+/); if (substr($0,RSTART+5,RLENGTH-5)+0 < 10) g++ }
END { m=(t-t0)/60; printf "%.1f min: ack %.2f, received-more-than-sent %.0f/min, seconds with a pose gap >100 ms %.1f/min\n", m, (su?re/su:0), u/m, g/m }' $f
```

## If it is still unexplained after all of the above

Read the patched server (`crazyflie_server.cpp`, [server-changes.md](server-changes.md) first):
how the radio threads, the retry handling and `posesChanged` interact, and whether the server
itself builds the backlog that starves pose forwarding. The server's mocap rate warning
(`Motion capture rate off`) already counts what `posesChanged` sees each second; compare it
with what the mocap node publishes.
