# Details

The deep dives behind the five beginner guides. Read these when a guide is not
enough, or before changing code.

| File | What it covers |
|---|---|
| [theory.md](theory.md) | The maths and the reason behind every algorithm: the ring, blocking, the safety filter, the attacker |
| [design-notes.md](design-notes.md) | What was decided, what flew, what broke, and the decisions still open |
| [operator-reference.md](operator-reference.md) | Every command, show setting and number on one page; keyboard teleop; reviewing a run |
| [qna.md](qna.md) | Answers to visitors' questions, sorted by audience, plus the honest list of limits |
| [preflight-gui.md](preflight-gui.md) | The preflight window: checklist, screenshots of good and bad, drone and room axes |
| [mocap.md](mocap.md) | OptiTrack: calibration, rigid bodies, the measured arena, the lab network |
| [running.md](running.md) | General rig commands: one-drone test flight, health checks, LEDs, launch arguments |
| [console.md](console.md) | The web console: every button and the command it runs |
| [mission-window.md](mission-window.md) | The escort's own screen in the web console |
| [troubleshooting.md](troubleshooting.md) | Every known symptom, cause and fix |
| [known-issues.md](known-issues.md) | The long story behind each silent failure, with evidence |
| [server-changes.md](server-changes.md) | What this repo changed in the Crazyswarm2 server, and why |
| [provenance.md](provenance.md) | Who owns each layer (Bitcraze, OptiTrack, IMRCLab, AI-DA-STC, this project), measured against upstream |

**Diagrams:** every diagram in these docs is a slide in
[`../diagrams/escort-diagrams.pptx`](../diagrams/escort-diagrams.pptx). Edit it in
PowerPoint, then run `./docs/diagrams/export_png.sh` to update the PNGs. The four plots
in `theory.md` (`../img/escort/*.svg`) are computed from the real controller by
[`escort_figures.py`](escort_figures.py) instead: `python3 docs/details/escort_figures.py`.
