# Details

The deep dives behind the beginner guides. Read these when a guide is not enough, or
before changing code.

**Escort**

| File | What it covers |
|---|---|
| [escort-theory.md](escort-theory.md) | The maths and the reason behind every algorithm: the ring, blocking, the safety filter, the attacker |
| [escort-design-notes.md](escort-design-notes.md) | What was decided, what flew, what broke, and the decisions still open |
| [escort-reference.md](escort-reference.md) | Every command, show setting and number on one page; keyboard teleop; reviewing a run |
| [escort-qna.md](escort-qna.md) | Answers to visitors' questions, sorted by audience, plus the honest list of limits |

**Guard (N defenders v M attackers, pluggable strategies)**

| File | What it covers |
|---|---|
| [guard-theory.md](guard-theory.md) | The maths and the reason behind the design: the safety contract, the CBF filter, the strategies, the rules |
| [guard-modules.md](guard-modules.md) | Every module, what it may and may not do, and how one tick flows through them |
| [guard-design-notes.md](guard-design-notes.md) | Why it is built this way: the CBF ported from AirStack, the separation floor, the rules and their measured balance, writing your own strategy |

**STL game**

| File | What it covers |
|---|---|
| [stl-design-notes.md](stl-design-notes.md) | How the colleague's game is ported and checked, what was measured, and how to bring in a new version |

**The rig, shared by every demo and show**

| File | What it covers |
|---|---|
| [preflight-gui.md](preflight-gui.md) | The preflight window: checklist, screenshots of good and bad, drone and room axes |
| [mocap.md](mocap.md) | OptiTrack: calibration, rigid bodies, the measured arena, the lab network |
| [serpent-show.md](serpent-show.md) | The one-minute serpent show for the big arena: what it does, how it stays safe at speed, how to fly it |
| [running.md](running.md) | General rig commands: one-drone test flight, health checks, LEDs, launch arguments |
| [console.md](console.md) | The web console: every button and the command it runs |
| [mission-window.md](mission-window.md) | Each demo's own screen in the web console, and the spec file behind it |
| [troubleshooting.md](troubleshooting.md) | Every known symptom, cause and fix |
| [known-issues.md](known-issues.md) | The long story behind each silent failure, with evidence |
| [server-changes.md](server-changes.md) | What this repo changed in the Crazyswarm2 server, and why |
| [provenance.md](provenance.md) | Who owns each layer (Bitcraze, OptiTrack, IMRCLab, AI-DA-STC, this project), measured against upstream |

**Diagrams:** every diagram in these docs is a slide in
[`../diagrams/strike-and-guard-diagrams.pptx`](../diagrams/strike-and-guard-diagrams.pptx).
Edit it in PowerPoint, then run `./docs/diagrams/export_png.sh` to update the PNGs. The
four plots in `escort-theory.md` (`../img/escort/*.svg`) are computed from the real
controller by [`escort_figures.py`](escort_figures.py) instead:
`python3 docs/details/escort_figures.py`.
