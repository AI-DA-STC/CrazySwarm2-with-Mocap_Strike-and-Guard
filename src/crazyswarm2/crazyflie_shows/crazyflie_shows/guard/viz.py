"""RViz markers for a guard match: who is where, what each drone is doing,
the keep-outs the safety layer enforces, and the score.

Used by ``plan_guard --rviz`` (offline matches played in real time) and by
``guard_show`` (a flight). Fixed frame ``world``; open it with
``rviz2 -d <share>/crazyflie_shows/data/guard.rviz``.

Nothing here may break a flight: every publish is wrapped, so a marker that
fails costs a picture, never a drone.
"""

from collections import deque

import numpy as np

from crazyflie_shows import safety
from crazyflie_shows.guard.world import ATTACK, RETIRING

try:
    from builtin_interfaces.msg import Duration
    from geometry_msgs.msg import Point
    from std_msgs.msg import ColorRGBA
    from visualization_msgs.msg import Marker, MarkerArray
except ImportError:                                   # pragma: no cover
    Marker = None

TOPIC = '/guard/markers'
FRAME = 'world'

C_DEF = (0.20, 0.50, 1.00, 0.95)
C_ATT = (1.00, 0.20, 0.10, 0.95)
C_OUT = (0.55, 0.55, 0.55, 0.70)
C_VIP = (1.00, 1.00, 1.00, 0.95)
C_KEEP = (1.00, 1.00, 1.00, 0.10)
C_STRIKE = (1.00, 0.30, 0.20, 0.07)
C_ROOM = (0.80, 0.80, 0.80, 0.80)
C_TEXT = (1.00, 1.00, 1.00, 0.95)


def _c(rgba):
    return ColorRGBA(r=rgba[0], g=rgba[1], b=rgba[2], a=rgba[3])


def _pt(p):
    return Point(x=float(p[0]), y=float(p[1]), z=float(p[2]))


class GuardViz:
    def __init__(self, node, trail=120):
        self.node = node
        self.ok = Marker is not None
        if self.ok:
            self.pub = node.create_publisher(MarkerArray, TOPIC, 10)
        self.trails = {}
        self.trail = trail

    def _m(self, ns, mid, mtype, stamp):
        m = Marker()
        m.header.frame_id = FRAME
        m.header.stamp = stamp
        m.ns, m.id, m.type, m.action = ns, mid, mtype, Marker.ADD
        m.pose.orientation.w = 1.0
        m.lifetime = Duration(sec=1)
        return m

    def publish(self, t, cfg, vip, agents, labels, result=None, title=''):
        if not self.ok:
            return
        try:
            self._publish(t, cfg, vip, agents, labels, result, title)
        except Exception as e:                        # noqa: BLE001
            self.node.get_logger().warn(f'guard viz: {e!r}', throttle_duration_sec=5.0)

    def clear(self):
        """Forget trails (a new match)."""
        self.trails = {}

    def _publish(self, t, cfg, vip, agents, labels, result, title):
        stamp = self.node.get_clock().now().to_msg()
        out = []
        # the room: floor outline and ceiling outline
        poly = safety.ARENA_POLYGON
        if poly is not None:
            for k, z in enumerate((0.0, cfg.ceiling)):
                m = self._m('room', k, Marker.LINE_STRIP, stamp)
                m.scale.x = 0.03
                m.color = _c(C_ROOM if k == 0 else (*C_ROOM[:3], 0.35))
                m.points = [_pt((x, y, z)) for x, y in list(poly) + [poly[0]]]
                out.append(m)
        # the VIP, its keep-out ellipsoid, its strike sphere
        m = self._m('vip', 0, Marker.SPHERE, stamp)
        m.pose.position = _pt(vip)
        m.scale.x = m.scale.y = m.scale.z = 0.35
        m.color = _c(C_VIP)
        out.append(m)
        m = self._m('vip', 1, Marker.SPHERE, stamp)
        m.pose.position = _pt(vip)
        m.scale.x = m.scale.y = 2 * cfg.d_vip
        m.scale.z = 2 * cfg.d_vip * cfg.vip_z_ratio
        m.color = _c(C_KEEP)
        out.append(m)
        m = self._m('vip', 2, Marker.SPHERE, stamp)
        m.pose.position = _pt(vip)
        m.scale.x = m.scale.y = m.scale.z = 2 * cfg.strike_radius
        m.color = _c(C_STRIKE)
        out.append(m)
        # every drone: body, half keep-out, trail, label
        for k, (n, a) in enumerate(sorted(agents.items())):
            col = C_OUT if not a.active else (C_ATT if a.team == ATTACK else C_DEF)
            m = self._m('drone', k, Marker.SPHERE, stamp)
            m.pose.position = _pt(a.p)
            m.scale.x = m.scale.y = m.scale.z = 0.28
            m.color = _c(col)
            out.append(m)
            if a.active:
                m = self._m('keepout', k, Marker.SPHERE, stamp)
                m.pose.position = _pt(a.p)
                m.scale.x = m.scale.y = cfg.d_cc
                m.scale.z = cfg.d_cc * cfg.cc_z_ratio
                m.color = _c((*col[:3], 0.08))
                out.append(m)
            tr = self.trails.setdefault(n, deque(maxlen=self.trail))
            tr.append(np.asarray(a.p, float).copy())
            if len(tr) > 1:
                m = self._m('trail', k, Marker.LINE_STRIP, stamp)
                m.scale.x = 0.025
                m.color = _c((*col[:3], 0.45))
                m.points = [_pt(p) for p in tr]
                out.append(m)
            m = self._m('label', k, Marker.TEXT_VIEW_FACING, stamp)
            m.pose.position = _pt(np.asarray(a.p) + [0.0, 0.0, 0.40])
            m.scale.z = 0.26
            m.color = _c(C_TEXT)
            what = (a.outcome.upper() if a.status == RETIRING or not a.active
                    else labels.get(n, ''))
            m.text = f'{n} {what}'.strip()
            out.append(m)
        # the scoreboard, above the room
        m = self._m('score', 0, Marker.TEXT_VIEW_FACING, stamp)
        m.pose.position = _pt([cfg.room_center[0], cfg.room_center[1], cfg.ceiling + 2.0])
        m.scale.z = 0.45
        m.color = _c(C_TEXT)
        line = f'{title} | t {t:.1f}s'
        if result is not None:
            line += f' | strikes {result.strikes} tags {result.tags}'
            if result.winner:
                line += f' | {result.winner.upper()} WINS: {result.reason}'
        m.text = line
        out.append(m)
        self.pub.publish(MarkerArray(markers=out))
