# The docs

One folder per demo: its beginner guides at the top, its deep dives in `details/`.
`rig/` is what every demo shares. Start with the [README](../README.md) if you are new.

| Start here | |
|---|---|
| [01-setup.md](01-setup.md) | Install everything once |
| [02-flight-day.md](02-flight-day.md) | The routine every flight day shares |
| [troubleshooting.md](troubleshooting.md) | The commonest problems, and what to do |

| Demo | Guides | Details |
|---|---|---|
| **Escort**: guard a moving VIP | [run](escort/run.md) · [how it works](escort/how-it-works.md) · [presenting](escort/presenting.md) | [theory](escort/details/theory.md) (why, with the maths) · [reference](escort/details/reference.md) (every setting and number) · [design notes](escort/details/design-notes.md) (the dated log, open decisions) · [Q&A](escort/details/qna.md) (visitors' questions) |
| **STL game**: guard a goal line | [run](stl/run.md) · [how it works](stl/how-it-works.md) | [design notes](stl/details/design-notes.md) (the algorithm, the port and its checks) |
| **Guard**: N defenders v M attackers | [run](guard/run.md) · [how it works](guard/how-it-works.md) · [presenting](guard/presenting.md) | [theory](guard/details/theory.md) (why, with the maths) · [modules](guard/details/modules.md) (the code) · [design notes](guard/details/design-notes.md) (the dated log) · [footage](guard/details/footage.md) (simulator clips) · [flight replay](guard/details/flight-replay.md) (a hardware flight, seen again) |
| **Serpent**: a one-minute show | [run](serpent/run.md) | |

| The rig (shared) | |
|---|---|
| [running.md](rig/running.md) | General commands: one-drone test, health checks, LEDs, launch arguments |
| [preflight-gui.md](rig/preflight-gui.md) | The preflight window, and what good and bad look like |
| [console.md](rig/console.md) · [mission-window.md](rig/mission-window.md) | The web console's buttons, and each demo's own window (developers: [console/README.md](../console/README.md)) |
| [mocap.md](rig/mocap.md) | OptiTrack: calibration, rigid bodies, the network |
| [flight-logs.md](rig/flight-logs.md) | What every flight records, and how to read it |
| [troubleshooting.md](rig/troubleshooting.md) | Every known symptom and its fix |
| [known-issues.md](rig/known-issues.md) | The evidence behind each silent failure and each CLAUDE.md rule |
| [server-changes.md](rig/server-changes.md) | What this repo changed in the Crazyswarm2 server, and why |
| [provenance.md](rig/provenance.md) | Who owns each layer, measured against upstream |

**Diagrams** are slides in [diagrams/strike-and-guard-diagrams.pptx](diagrams/strike-and-guard-diagrams.pptx):
edit there, then `./docs/diagrams/export_png.sh`. A full re-export redraws every PNG
slightly differently, so commit only the PNGs of slides you changed. The escort's four
plots (`img/escort/*.svg`) come from the real controller:
`python3 docs/escort/details/escort_figures.py`.
