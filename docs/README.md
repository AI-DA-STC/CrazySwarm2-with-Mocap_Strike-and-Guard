# Details

The deep dives behind the beginner guides. Read these when a guide is not enough, or
before changing code.

**Escort**

| File | What it covers |
|---|---|
| [escort/details/theory.md](escort/details/theory.md) | The maths and the reason behind every algorithm: the ring, blocking, the safety filter, the attacker |
| [escort/details/design-notes.md](escort/details/design-notes.md) | What was decided, what flew, what broke, and the decisions still open |
| [escort/details/reference.md](escort/details/reference.md) | Every command, show setting and number on one page; keyboard teleop; reviewing a run |
| [escort/details/qna.md](escort/details/qna.md) | Answers to visitors' questions, sorted by audience, plus the honest list of limits |

**Guard (N defenders v M attackers, pluggable strategies)**

| File | What it covers |
|---|---|
| [guard/details/theory.md](guard/details/theory.md) | The maths and the reason behind the design: the safety contract, the CBF filter, the strategies, the rules |
| [guard/details/modules.md](guard/details/modules.md) | Every module, what it may and may not do, and how one tick flows through them |
| [guard/details/design-notes.md](guard/details/design-notes.md) | The dated log: what was decided, measured and learned, match by match |
| [guard/details/footage.md](guard/details/footage.md) | How the simulator clips in the guide are made (`scripts/footage/`), and where the simulator disagrees with the offline checks |
| [guard/details/flight-replay.md](guard/details/flight-replay.md) | Watching a hardware flight again: the console view rebuilt from its flight log, and the hall camera's footage with every drone circled |

**STL game**

| File | What it covers |
|---|---|
| [stl/details/design-notes.md](stl/details/design-notes.md) | How the colleague's algorithm decides, how it is ported and checked, what was measured, and how to bring in a new version |

**The rig, shared by every demo and show**

| File | What it covers |
|---|---|
| [preflight-gui.md](rig/preflight-gui.md) | The preflight window: checklist, screenshots of good and bad, drone and room axes |
| [mocap.md](rig/mocap.md) | OptiTrack: calibration, rigid bodies, the measured arena, the lab network |
| [serpent/run.md](serpent/run.md) | The one-minute serpent show for the big arena: what it does, how it stays safe at speed, how to fly it |
| [running.md](rig/running.md) | General rig commands: one-drone test flight, health checks, LEDs, launch arguments |
| [console.md](rig/console.md) | The web console: every button and the command it runs |
| [mission-window.md](rig/mission-window.md) | Each demo's own screen in the web console, and the spec file behind it |
| [troubleshooting.md](rig/troubleshooting.md) | Every known symptom, cause and fix |
| [radio-link-2026-11-17.md](rig/radio-link-2026-11-17.md) | The 17 November session: radio replies lost and poses arriving late, what was measured and ruled out, what to try next |
| [known-issues.md](rig/known-issues.md) | The long story behind each silent failure, with evidence |
| [server-changes.md](rig/server-changes.md) | What this repo changed in the Crazyswarm2 server, and why |
| [provenance.md](rig/provenance.md) | Who owns each layer (Bitcraze, OptiTrack, IMRCLab, AI-DA-STC, this project), measured against upstream |

**Diagrams:** every diagram in these docs is a slide in
[`../diagrams/strike-and-guard-diagrams.pptx`](diagrams/strike-and-guard-diagrams.pptx).
Edit it in PowerPoint, then run `./docs/diagrams/export_png.sh` to update the PNGs. The
four plots in `escort/details/theory.md` (`../img/escort/*.svg`) are computed from the real
controller by [`escort_figures.py`](escort/details/escort_figures.py) instead:
`python3 docs/escort/details/escort_figures.py`.
