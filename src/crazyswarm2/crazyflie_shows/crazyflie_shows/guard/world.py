"""What a strategy is allowed to see: a read-only snapshot of the match.

A strategy gets a :class:`View` every tick and returns velocities. It never
sees the radio, ROS, the safety layer's internals or the other team's
strategy -- only positions, velocities, statuses, the room and the rules --
and for the other team only what a camera could tell it: observed positions
and velocities estimated from them, never their commands. Every View is a
private copy; changing it changes nothing.
That boundary is what makes strategies swappable and comparable: the same
View is built offline by ``plan_guard`` and on the drones by ``guard_show``.
"""

from dataclasses import dataclass, field

import numpy as np

from crazyflie_shows import escort

DEFENSE = 'defense'
ATTACK = 'attack'

#: Agent statuses. Only ACTIVE agents are commanded by their strategy;
#: RETIRING ones are being landed (and are obstacles to everybody else);
#: DOWNED and STRUCK record why an attacker left the match.
ACTIVE = 'active'
RETIRING = 'retiring'


@dataclass
class Agent:
    name: str
    team: str
    p: np.ndarray                  # observed position (mocap, else setpoint)
    #: Your OWN team: the velocity you last commanded. An OPPONENT: its
    #: velocity ESTIMATED from its observed positions -- never its command,
    #: which is its strategy's intent (engine.py, "What a strategy may know").
    v: np.ndarray
    status: str = ACTIVE
    #: Why it stopped being active: 'downed', or 'struck' (it scored).
    outcome: str = ''

    @property
    def active(self):
        return self.status == ACTIVE


class Arena:
    """The room as a strategy sees it: clearance, direction inward, band."""

    def __init__(self, cfg):
        self._cfg = cfg
        self.floor = cfg.floor
        self.ceiling = cfg.ceiling
        self.centre = np.array([*cfg.room_center, 0.5 * (cfg.floor + cfg.ceiling)])

    def clearance(self, p):
        """Signed plan-view distance to the edge (+ inside). Any (..., 2+)."""
        return escort.room_clearance(self._cfg, p)

    def inward(self, p):
        """Unit horizontal vector (3,) pointing into the room from ``p``."""
        n = escort.room_inward(self._cfg, p)
        return np.array([n[0], n[1], 0.0])

    def vertical_room(self, p):
        """(room below, room above) ``p``, m."""
        z = float(np.asarray(p, float)[2])
        return z - self.floor, self.ceiling - z

    def inside(self, p, margin=0.0):
        p = np.asarray(p, float)
        lo, hi = self.vertical_room(p)
        return float(self.clearance(p)) >= margin and lo >= margin and hi >= margin


@dataclass
class View:
    t: float
    dt: float
    vip_p: np.ndarray
    vip_v: np.ndarray
    agents: dict                   # name -> Agent (both teams, every status)
    arena: Arena
    cfg: object                    # GuardConfig: limits, separation, safety
    #: The rule set being played (guard/rules/): call its down_rates /
    #: strike_rates on PREDICTED positions to see how a plan would score.
    rules: object = None
    #: Everybody's meters now, name -> {'down': 0..1, 'strike': 0..1}:
    #: public, like a scoreboard.
    meters: dict = field(default_factory=dict)
    #: Events so far, oldest first (rules.Event).
    events: list = field(default_factory=list)

    def team(self, team, active_only=True):
        return [a for a in self.agents.values()
                if a.team == team and (a.active or not active_only)]

    @property
    def defenders(self):
        return self.team(DEFENSE)

    @property
    def attackers(self):
        return self.team(ATTACK)

    def v_max(self, team):
        return self.cfg.v_max_defense if team == DEFENSE else self.cfg.v_max_attack
