"""The built-in rule sets.

In every one of them an attacker STRIKES by holding within ``strike_radius``
of the VIP for ``strike_time`` (the common rule in ``Rules``). They differ in
who can be DOWNED, and how:

=================  ===========  =============================================
name               downable     a drone's down meter fills...
=================  ===========  =============================================
``tag``            attackers    at 1/down_time while ANY defender is within
                                reach; resets the moment none is (the STL
                                game's block, and this show's first rule)
``timer``          nobody       never: the defence can only deny, the clock
                                decides
``pressure``       both teams   at (opponents in reach - teammates in reach
                                - 1) / down_time, never below 0; drains at
                                ``drain`` per second otherwise
``zone``           both teams   like ``tag``, but only on the OTHER team's
                                ground: attackers inside ``home`` of the
                                VIP, defenders outside it
``zone_pressure``  both teams   like ``pressure``, on the other team's ground
=================  ===========  =============================================

``pressure`` is the graded local majority. Counting is from the victim's
point of view, within ``reach`` of it:

    1 v 1  -> 0          standoff, no mutual kills
    2 v 1  -> 1/T        the lone drone falls in down_time
    3 v 1  -> 2/T        twice as fast
    2 v 2  -> 0          standoff
    3 v 2  -> 1/T        for each of the pair; the trio is safe

so there is a reason to gang up and a reason not to be caught alone, for
both teams. The meter drains instead of resetting, so a drone that escapes
is still weakened for a while.
"""

import numpy as np

from crazyflie_shows.guard.rules import Rules, register
from crazyflie_shows.guard.world import ATTACK, DEFENSE


def _count_within(centre, others, r):
    """(K,) how many of ``others`` (K, M, 3) are within ``r`` of ``centre`` (K, 3)."""
    others = np.asarray(others, float)
    if others.size == 0:
        return np.zeros(len(centre))
    d = np.linalg.norm(others - np.asarray(centre, float)[:, None, :], axis=-1)
    return np.count_nonzero(d <= r, axis=1)


@register
class Tag(Rules):
    """Attackers are downed by any defender in reach for down_time (reset on leaving)."""

    name = 'tag'
    DEFAULTS = {'reach': 1.15, 'down_time': 1.1}
    DOWNABLE = (ATTACK,)

    def down_rates(self, victim_team, victim_p, opp_p, ally_p, vip_p):
        n = _count_within(np.asarray(victim_p, float).reshape(-1, 3), opp_p, self.reach)
        return np.where(n >= 1, 1.0 / self.down_time, 0.0)


@register
class Timer(Rules):
    """Nobody is downed: the defence can only deny, the clock decides."""

    name = 'timer'
    #: 1.6 m, not the common 2.4: nothing can down an attacker, so only the
    #: defenders' bodies stop it. MEASURED 2026-11-03: with the guard's
    #: relaxed 0.45 m keep-out the defence loses every match at any strike
    #: radius from 1.6 to 2.4 m -- one defender's wall is too thin. Pure
    #: denial needs a wider keep-out (-p d_cc:=0.9).
    DEFAULTS = {'strike_radius': 1.6}
    DOWNABLE = ()


@register
class Pressure(Rules):
    """Graded local majority, both teams: fills at (opponents - teammates - 1)/down_time."""

    name = 'pressure'
    #: strike_radius 1.6, not the common 2.4: a lone defender cannot down a
    #: lone attacker here, so the strike zone has to be smaller. MEASURED
    #: 2026-11-03 (4 v 3, 8 seeds): shell beats coordinated 6/8 and direct
    #: 3/8 at 1.6 m, against 4/8 and 0/8 at 2.0 m; defenders are downed too.
    DEFAULTS = {'reach': 1.2, 'down_time': 1.1,
                'drain_rate': 0.5,       # per s: an escaped drone heals in 2 s
                'strike_radius': 1.6}
    DOWNABLE = (DEFENSE, ATTACK)

    def _graded(self, victim_p, opp_p, ally_p):
        v = np.asarray(victim_p, float).reshape(-1, 3)
        n_opp = _count_within(v, opp_p, self.reach)
        n_ally = _count_within(v, ally_p, self.reach)
        return np.maximum(0, n_opp - n_ally - 1) / self.down_time

    def down_rates(self, victim_team, victim_p, opp_p, ally_p, vip_p):
        return self._graded(victim_p, opp_p, ally_p)

    def drain(self, kind):
        return float(self.p['drain_rate']) if kind == 'down' else np.inf


class _Zoned:
    """Mixin: only on the other team's ground. Attackers are exposed inside
    ``home`` of the VIP, defenders outside it -- capture the flag."""

    def _exposed(self, victim_team, victim_p, vip_p):
        d = np.linalg.norm(np.asarray(victim_p, float).reshape(-1, 3)
                           - np.asarray(vip_p, float), axis=-1)
        inside = d <= float(self.p['home'])
        return inside if victim_team == ATTACK else ~inside

    def describe(self):
        return f'{self.name} (home ground {float(self.p["home"]):.1f} m round the VIP)'

    def problems(self, cfg):
        bad = super().problems(cfg)
        if float(self.p['home']) <= self.strike_radius:
            bad.append('home must reach beyond strike_radius, or attackers can '
                       'strike without ever being exposed')
        return bad


@register
class Zone(_Zoned, Rules):
    """Capture the flag: tag-style downing, but only on the other team's ground."""

    name = 'zone'
    DEFAULTS = {'reach': 1.15, 'down_time': 1.1, 'home': 3.0}
    DOWNABLE = (DEFENSE, ATTACK)

    def down_rates(self, victim_team, victim_p, opp_p, ally_p, vip_p):
        v = np.asarray(victim_p, float).reshape(-1, 3)
        n = _count_within(v, opp_p, self.reach)
        rate = np.where(n >= 1, 1.0 / self.down_time, 0.0)
        return np.where(self._exposed(victim_team, v, vip_p), rate, 0.0)


@register
class ZonePressure(_Zoned, Pressure):
    """Graded local majority, but only on the other team's ground."""

    name = 'zone_pressure'
    DEFAULTS = {**Pressure.DEFAULTS, 'home': 3.0}

    def down_rates(self, victim_team, victim_p, opp_p, ally_p, vip_p):
        v = np.asarray(victim_p, float).reshape(-1, 3)
        return np.where(self._exposed(victim_team, v, vip_p),
                        self._graded(v, opp_p, ally_p), 0.0)
