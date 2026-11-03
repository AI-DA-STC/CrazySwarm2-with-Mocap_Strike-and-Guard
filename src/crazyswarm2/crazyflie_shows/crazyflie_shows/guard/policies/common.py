"""Small pieces most strategies need. Nothing here is a strategy."""

import numpy as np
from scipy.optimize import linear_sum_assignment


def unit(v, fallback=(1.0, 0.0, 0.0)):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.asarray(fallback, float)


def seek(p, goal, v_max, a_max, v_goal=None, gain=2.0):
    """Velocity toward ``goal`` that can stop there.

    Speed is the smallest of the cap, what ``a_max`` can still brake from
    (sqrt(2 a d)), and a proportional ``gain * d`` for the last few cm, so a
    drone arrives instead of oscillating. ``v_goal`` (a moving goal's own
    velocity) is added as feedforward, then the sum is capped.
    """
    d = np.asarray(goal, float) - np.asarray(p, float)
    dist = float(np.linalg.norm(d))
    speed = min(v_max, np.sqrt(2.0 * a_max * dist), gain * dist)
    v = d / dist * speed if dist > 1e-9 else np.zeros(3)
    if v_goal is not None:
        v = v + np.asarray(v_goal, float)
    n = float(np.linalg.norm(v))
    return v * (v_max / n) if n > v_max else v


def bearing(p, about):
    d = np.asarray(p, float) - np.asarray(about, float)
    return float(np.arctan2(d[1], d[0]))


def wrap(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def soft_min(x, k):
    """Smooth minimum (the STL game's), -> min as k grows."""
    x = np.asarray(x, float)
    m = float(np.min(x))
    return m - np.log(np.sum(np.exp(-k * (x - m)))) / k


def assign(cost):
    """Min-cost assignment of rows to columns: list of (row, col)."""
    cost = np.asarray(cost, float)
    if cost.size == 0:
        return []
    r, c = linear_sum_assignment(np.where(np.isfinite(cost), cost, 1e9))
    return list(zip(r.tolist(), c.tolist()))


def into_band(p, arena, margin=0.3):
    """``p`` with its height clipped into the band, ``margin`` clear of it."""
    p = np.asarray(p, float).copy()
    p[2] = float(np.clip(p[2], arena.floor + margin, arena.ceiling - margin))
    return p


def into_room(p, arena, margin=0.3):
    """``p`` pulled into the room so it is ``margin`` clear of the edge."""
    p = into_band(p, arena, margin)
    for _ in range(4):
        c = float(arena.clearance(p))
        if c >= margin:
            break
        p = p + arena.inward(p) * (margin - c + 1e-3)
    return p
