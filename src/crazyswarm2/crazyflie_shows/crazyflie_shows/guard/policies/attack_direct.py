"""Attack 'direct' (a baseline): every attacker flies straight at the VIP.

No planning, no coordination, no feints: the yardstick an attack strategy
has to beat, and the hardest-pressing test of a defence's geometry. It
relies entirely on the safety layer to not hit anything.
"""

from crazyflie_shows.guard.policies import Policy, register
from crazyflie_shows.guard.policies.common import seek, unit
from crazyflie_shows.guard.world import ATTACK


@register
class Direct(Policy):
    """Straight at the VIP, at full speed, all at once."""

    team = ATTACK
    name = 'direct'
    DEFAULTS = {
        'inside': 0.3,          # m inside the strike radius it aims for
    }

    def act(self, view):
        out = {}
        r = view.rules.strike_radius - self.p['inside']
        for a in view.attackers:
            goal = view.vip_p + unit(a.p - view.vip_p) * r
            goal[2] = view.vip_p[2]
            out[a.name] = seek(a.p, goal, view.v_max(self.team), view.cfg.a_max)
            self.labels[a.name] = 'charge'
        return out
