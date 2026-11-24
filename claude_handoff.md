# Claude handoff: Strike and Guard (Crazyflie rig)

> **How to use this file.** Read it at the start of a session, after [CLAUDE.md](CLAUDE.md).
> §1 is the current state, §2 is what is waiting on people, §3 is the next steps.
> Update all three before you stop. The history behind them lives in the docs, not here:
> [docs/details/guard-design-notes.md](docs/details/guard-design-notes.md) (the last three
> sections: landing out of the way, the form-up, 2026-11-23) and
> [docs/details/radio-link-2026-11-17.md](docs/details/radio-link-2026-11-17.md).
> Last updated: 24 November 2026.

## 1. Current state (as of 23-11)

**Guard on hardware, 23-11:** 12 runs and 5 completed matches, all 4 v 3 with the DJI,
`pressure` rules, 1 m/s. The attack won 3 and the defence 2. Every run has a folder in
`~/.ros/flight_logs/20261123_*`, and the run-by-run table is in the design notes.

- **Mellinger works**: lag 0.08-0.14 s (PID 0.54-0.58 s the same day), closest pair
  0.36-0.40 m, 0 near misses, 1 CBF emergency (14:41), backstop never. **Since 24-11 it
  is the default** (`guard_show` + console; not switched in sim, which runs it already).
  `-p controller:=pid` = the old behaviour. `plan_guard` still defaults to the PID plant.
- **Form-up: attackers hold** (`form_up_attackers` hold|follow, default hold). The pilot
  opens distance with the DJI; the show prints `NOT A FAIR START yet` then `fair start`.
  Flown in four matches.
- **Contested strikes** (`strike_block`, m, default 0 = off). Flown once at 0.8 m (16:49,
  defence won). In sim it rescues the defence against flood and wolfpack, but not against
  coordinated (1 -> 2 of 12): coordinated wins by downs.
- **Mocap with Wi-Fi up fixed** (patch 0007, `interface_ip: "auto"`), verified on the rig.

Everything above is committed on `big-arena` (5a4feec, af5f992), and the docs caught up
on 24-11.

## 2. Waiting on people

1. **Batteries**: in the last 23-11 match the packs started at ~4.0 V and sagged to
   3.3-3.4 V under load. Charge everything before the next session.
2. **Reboot** still worthwhile: abandoned Fast DDS shared-memory files pile up in `/dev/shm`
   (stops use SIGKILL).
3. **Diagram PNGs drift on re-export:** on 24-11, `export_png.sh` re-rendered the text of 37
   unchanged slides slightly differently (26-29 matched), so only `30-guard-lag.png` was
   committed. A full re-export would churn every PNG; find the font-rendering difference
   first.

## 3. Next steps for the next session

1. **Balance under `pressure` against `coordinated`:** the defence is 0-3/12 in sim because
   coordinated downs every defender. Levers, not built: a teammate-support radius in the
   rules, or a "wingman" defence that keeps pairs together.
2. **Re-run the drifting-DJI matrix on the Mellinger plant** (`plan_guard --matrix --rules
   all --delay 0.1 --tau 0.1 --vip-move 0.2`). 5/80 cells failed on the PID plant.
3. **Two report quirks** (cf10 23-11): its supervisor flagged `crashed, tumbled` at an
   ordinary touchdown (also cf4/cf2 17-11), and its `land()` line was missing from rosout,
   so the report's SERVER COMMANDS list can be incomplete. Neither is understood yet.

Background that holds across sessions lives in the memory files (guard show, mocap rate
limiter, mocap interface_ip). The AirStack training project keeps its own handoff at
`~/AirStack-starling-max2/svg_training/docs/claude/HANDOFF.md`, untouched here.
