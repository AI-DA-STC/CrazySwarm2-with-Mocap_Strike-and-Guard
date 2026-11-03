"""The referee: strikes, tags and the clock. Strategy-blind by design.

Two ways to play, chosen with ``GuardConfig.tagging``:

* **tag** (``tagging=True``, the default): the STL game's model. A defender
  that holds within ``tag_radius`` of an attacker for ``tag_time`` DOWNS it,
  and it lands -- visible, unambiguous, and it frees the airspace, so the
  match thins out and ends on its own.
* **deny** (``tagging=False``): nobody is downed; the defence can only keep
  the attackers off, and the clock decides.

Either way an attacker that holds within ``strike_radius`` of the VIP for
``strike_time`` scores a STRIKE and retires (lands). The attack wins on
``strikes_to_win`` strikes; the defence wins by reaching the end of the
clock, or by downing every attacker first.

Distances are 3D. Both radii sit OUTSIDE the safety layer's keep-outs
(config.problems refuses otherwise), so a strike or a tag is a geometric
event, never contact.
"""

from dataclasses import dataclass, field

import numpy as np

from crazyflie_shows.guard.world import ATTACK, DEFENSE


@dataclass
class Event:
    t: float
    kind: str              # 'strike' | 'tag'
    attacker: str
    by: str = ''           # the defender, for a tag

    def __str__(self):
        if self.kind == 'tag':
            return f't+{self.t:5.1f}s  {self.by} TAGGED {self.attacker} -- it lands'
        return f't+{self.t:5.1f}s  {self.attacker} STRUCK the VIP -- it lands'


@dataclass
class Result:
    winner: str            # 'defense' | 'attack' | '' (still playing)
    reason: str
    strikes: int
    tags: int
    t: float
    events: list = field(default_factory=list)


class Referee:
    def __init__(self, cfg):
        self.cfg = cfg
        self._strike_t = {}
        self._tag_t = {}
        self.events = []

    def update(self, t, dt, agents, vip_p):
        """Advance the timers; return the NEW events of this tick.

        ``agents``: name -> Agent, positions as the referee should judge them
        (the aircraft, where mocap sees them).
        """
        cfg = self.cfg
        vip_p = np.asarray(vip_p, float)
        defenders = [a for a in agents.values() if a.team == DEFENSE and a.active]
        new = []
        for a in agents.values():
            if a.team != ATTACK or not a.active:
                continue
            if float(np.linalg.norm(a.p - vip_p)) <= cfg.strike_radius:
                self._strike_t[a.name] = self._strike_t.get(a.name, 0.0) + dt
            else:
                self._strike_t[a.name] = 0.0
            if self._strike_t[a.name] >= cfg.strike_time:
                new.append(Event(t, 'strike', a.name))
                continue
            if not cfg.tagging or not defenders:
                continue
            d = [float(np.linalg.norm(a.p - q.p)) for q in defenders]
            k = int(np.argmin(d))
            if d[k] <= cfg.tag_radius:
                self._tag_t[a.name] = self._tag_t.get(a.name, 0.0) + dt
            else:
                self._tag_t[a.name] = 0.0
            if self._tag_t[a.name] >= cfg.tag_time:
                new.append(Event(t, 'tag', a.name, defenders[k].name))
        self.events.extend(new)
        return new

    def result(self, t, agents):
        cfg = self.cfg
        strikes = sum(e.kind == 'strike' for e in self.events)
        tags = sum(e.kind == 'tag' for e in self.events)
        active_att = [a for a in agents.values() if a.team == ATTACK and a.active]
        if strikes >= cfg.strikes_to_win:
            return Result('attack', f'{strikes} strike(s)', strikes, tags, t,
                          list(self.events))
        if not active_att:
            return Result('defense', 'no attacker left in play', strikes, tags,
                          t, list(self.events))
        if t >= cfg.duration:
            return Result('defense', 'held to the end of the clock', strikes,
                          tags, t, list(self.events))
        return Result('', '', strikes, tags, t, list(self.events))
