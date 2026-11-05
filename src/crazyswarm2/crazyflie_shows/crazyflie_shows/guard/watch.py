"""The near-miss watch on the MEASURED aircraft, graded instead of all-or-nothing.

The CBF holds the setpoints apart; this watches the aircraft. Until
2026-11-05 one measured pair inside ``near_miss_ratio`` of the floor ellipsoid
(0.25 m across) landed the whole show on the spot, on one mocap frame -- and
on hardware most matches ended that way before anyone could see who won.
What it does now, every tick:

1. **Mocap glitches are not near misses.** A drone whose measured position
   jumps further in one tick than any Crazyflie can fly (``mocap_jump_m``,
   0.30 m = 6 m/s at 20 Hz, plus what it could have flown through any
   frames that were missing) is a mocap glitch (a swapped or ghost rigid body).
   Its pose is distrusted for that tick and the next -- the engine flies it on
   its setpoint -- and it is counted and reported.
2. **Hard near miss -> land everything**, at once, as before, below
   ``near_miss_land_ratio`` (0.55 = 0.19 m across, 0.34 m vertically).
3. **Soft near miss -> PAUSE**: inside ``near_miss_ratio`` (0.7) for
   ``near_miss_ticks`` ticks in a row, the match freezes and every drone
   holds through the safety layer, so the aircraft settle back onto setpoints
   the CBF already keeps ``d_cc`` apart. Play resumes when every pair is back
   outside ``near_miss_clear_ratio``; if that takes longer than
   ``near_miss_pause_s``, everything lands. ``near_miss_pause:=false``
   restores the old behaviour (land on a soft near miss).

Every near miss is reported with the evidence needed to say WHY it happened:
the measured gap, the setpoint gap at the same instant and each drone's
tracking error (aircraft minus setpoint). A small setpoint gap means the
plan put them there; a large one with a large tracking error means the
aircraft lagged its setpoint.

Pure Python: tested offline, used by guard_show.
"""

from dataclasses import dataclass, field

import numpy as np

from crazyflie_shows.guard import safety_layer

OK, PAUSE, LAND = 'ok', 'pause', 'land'


@dataclass
class Verdict:
    action: str                       # ok | pause | land
    why: str = ''
    glitched: set = field(default_factory=set)   # names to distrust this tick
    resumed: bool = False


@dataclass
class Pass:
    """One close pass, with the evidence."""
    t: float
    a: str
    b: str
    ratio: float
    gap: float                        # measured centre distance, m
    dz: float
    sp_gap: float                     # setpoint distance at the same tick, m
    lag_a: float                      # |measured - setpoint|, m
    lag_b: float

    def __str__(self):
        cause = ('the setpoints were this close too: the plan put them there'
                 if self.sp_gap < self.gap + 0.10 else
                 'the setpoints were further apart: the aircraft lagged them')
        return (f't+{self.t:5.1f}s {self.a}/{self.b} {self.gap:.2f} m apart '
                f'(dz {self.dz:+.2f}, {self.ratio:.2f} of the floor); setpoints '
                f'{self.sp_gap:.2f} m apart; tracking error {self.a} '
                f'{self.lag_a:.2f} m, {self.b} {self.lag_b:.2f} m -- {cause}')


class NearMissWatch:
    def __init__(self, cfg):
        self.cfg = cfg
        self._prev = {}
        self._suspect = {}             # name -> ticks left distrusted
        self._run = {}                 # pair -> consecutive soft ticks
        self.paused_at = None
        self.glitches = 0
        self.passes = []               # every soft or hard near miss
        self.closest = None            # the closest pass of the run

    def _evidence(self, t, a, b, pa, pb, sp):
        sa, sb = sp.get(a), sp.get(b)
        sp_gap = (float(np.linalg.norm(sa - sb)) if sa is not None and sb is not None
                  else float('nan'))
        return Pass(t, a, b, safety_layer.floor_ratio(self.cfg, pa, pb),
                    float(np.linalg.norm(pa - pb)), float(pa[2] - pb[2]), sp_gap,
                    float(np.linalg.norm(pa - sa)) if sa is not None else float('nan'),
                    float(np.linalg.norm(pb - sb)) if sb is not None else float('nan'))

    def update(self, t, measured, setpoints, paused=False):
        """``measured``: name -> position or None (stale); ``setpoints``:
        name -> commanded position. Returns a :class:`Verdict`."""
        cfg = self.cfg
        glitched = set()
        for n, p in measured.items():
            if p is None:
                continue
            p = np.asarray(p, float)
            q, tq = self._prev.get(n, (None, t))
            self._prev[n] = (p.copy(), t)
            # after a dropout it may honestly reappear further on: allow what
            # it could have flown in the frames that were missing
            allow = cfg.mocap_jump_m + cfg.v_max_safety * max(
                0.0, t - tq - 1.0 / cfg.rate_hz)
            if q is not None and float(np.linalg.norm(p - q)) > allow:
                self.glitches += 1
                self._suspect[n] = 2
        for n in list(self._suspect):
            if self._suspect[n] > 0:
                glitched.add(n)
                self._suspect[n] -= 1
            else:
                del self._suspect[n]

        live = [(n, np.asarray(p, float)) for n, p in measured.items()
                if p is not None and n not in glitched and p[2] > 0.3]
        sp = {n: np.asarray(v, float) for n, v in setpoints.items()}
        worst, hard, soft_now = np.inf, None, set()
        for i, (n1, p1) in enumerate(live):
            for n2, p2 in live[i + 1:]:
                r = safety_layer.floor_ratio(cfg, p1, p2)
                worst = min(worst, r)
                if self.closest is None or r < self.closest.ratio:
                    self.closest = self._evidence(t, n1, n2, p1, p2, sp)
                key = (n1, n2)
                if r < cfg.near_miss_land_ratio:
                    hard = self._evidence(t, n1, n2, p1, p2, sp)
                if r < cfg.near_miss_ratio:
                    soft_now.add(key)
                    self._run[key] = self._run.get(key, 0) + 1
                    if self._run[key] == cfg.near_miss_ticks:
                        self.passes.append(self._evidence(t, n1, n2, p1, p2, sp))
        for k in list(self._run):
            if k not in soft_now:
                del self._run[k]

        if hard is not None:
            self.passes.append(hard)
            return Verdict(LAND, f'NEAR MISS (hard) {hard}', glitched)
        tripped = any(v >= cfg.near_miss_ticks for v in self._run.values())
        if tripped and not cfg.near_miss_pause:
            return Verdict(LAND, f'NEAR MISS {self.passes[-1]}', glitched)
        if tripped and self.paused_at is None:
            self.paused_at = t
            return Verdict(PAUSE, f'SAFETY PAUSE -- near miss {self.passes[-1]}',
                           glitched)
        if self.paused_at is not None:
            if worst >= cfg.near_miss_clear_ratio:
                self.paused_at = None
                return Verdict(OK, 'SAFETY PAUSE over -- play resumes', glitched,
                               resumed=True)
            if t - self.paused_at > cfg.near_miss_pause_s:
                return Verdict(LAND, f'NEAR MISS did not clear in '
                               f'{cfg.near_miss_pause_s:.1f} s', glitched)
            return Verdict(PAUSE, '', glitched)
        return Verdict(OK, '', glitched)
