"""Every number the guard engine needs that is NOT a strategy's own.

Strategy tuning lives with each strategy (its ``DEFAULTS``); this is the
room, the aircraft limits, the safety layer and the rules -- the things every
strategy is held to, which is what makes two strategies comparable.

The attribute names ``room_center``, ``arena_radius``, ``contain_margin``,
``self_stale_s``, ``self_stale_land_s``, ``track_error_m`` and
``track_error_s`` match :class:`crazyflie_shows.escort.EscortConfig` on
purpose: the escort's room helpers (``room_clearance``, ``clamp_to_room``,
``room_inward``) and its per-drone watchdog (``contain_check``) take either
config, so the two shows share one definition of "inside the room" and one
containment rule.
"""

from dataclasses import dataclass, fields

from crazyflie_shows import safety


@dataclass
class GuardConfig:
    # -- the room (shared with the escort; see the module docstring) -------
    room_center: tuple = tuple(safety.ARENA_CENTRE)
    #: Only binds when set tighter than the arena's own plan radius; with a
    #: polygon in arena.yaml the polygon is the room.
    arena_radius: float = safety.ARENA_RADIUS_PLAN
    #: The altitude band every drone is held inside (the safety layer treats
    #: both as walls). The big arena is tracked to 7 m; 3 m is a deliberate
    #: first-flights ceiling, raise it per run with -p ceiling:=...
    floor: float = 0.4
    ceiling: float = 3.0

    # -- aircraft ----------------------------------------------------------
    rate_hz: float = 20.0
    #: Per-team speed caps, applied to each strategy's request before the
    #: safety layer. The escort flew at 0.6 m/s; these are the first step up.
    v_max_defense: float = 1.0
    v_max_attack: float = 1.0
    #: Hard cap the safety layer may use while dodging. Never below either
    #: team's cap.
    v_max_safety: float = 1.2
    #: Acceleration limit on each strategy's request (the safety layer may
    #: exceed it to avoid a collision).
    a_max: float = 2.0
    #: Height drones lift to off their marks, and stream from.
    start_height: float = 1.0
    #: Speed a retiring (tagged / struck) drone is modelled descending at
    #: while the high-level commander lands it.
    land_speed: float = 0.25

    # -- separation ---------------------------------------------------------
    #: The guard's OWN hard floor between two Crazyflies, as an ellipsoid:
    #: min_separation across, min_separation_z up and down. Its own, not
    #: arena.yaml's 0.80 m (which every other show keeps), relaxed 2026-11-03
    #: at the user's request: the STL game is designed to 0.20 m between
    #: drones at ONE cruise height ("closest approach 0.18-0.20 m",
    #: stl-design-notes.md). Side by side at one height is the regime that is
    #: fine; one drone over another is the separate DOWNWASH hazard, so the
    #: vertical floor stays escort.DOWNWASH_DZ (0.62 m, measured).
    min_separation: float = 0.35
    min_separation_z: float = 0.62

    # -- safety layer (velocity CBF; guard/safety_layer.py) -----------------
    #: Crazyflie-to-Crazyflie keep-out the CBF holds the SETPOINTS to: d_cc
    #: across, d_cc * cc_z_ratio up and down. The aircraft trail their
    #: setpoints by up to TRACKING_MARGIN, so d_cc = the floor + that margin,
    #: and the vertical axis keeps ~1 m, well over the downwash floor.
    d_cc: float = 0.35 + safety.TRACKING_MARGIN
    cc_z_ratio: float = 2.2
    #: Crazyflie-to-VIP keep-out. The VIP is a hand-flown DJI (or a person):
    #: bigger, with a far bigger downwash, so a taller ellipsoid.
    d_vip: float = 1.2
    vip_z_ratio: float = 1.75
    #: Class-K gain: how fast a gap may close, per metre of gap (1/s). The
    #: AirStack default.
    alpha: float = 2.5
    #: Gain for the walls, floor and ceiling.
    alpha_wall: float = 2.0
    #: How far inside the room clamp and the band the CBF holds setpoints.
    wall_margin: float = 0.05

    # -- watchdogs (shared with escort.contain_check) -----------------------
    contain_margin: float = 0.25
    self_stale_s: float = 0.3
    self_stale_land_s: float = 1.0
    track_error_m: float = 0.60
    track_error_s: float = 0.80
    vip_stale_hold_s: float = 0.4
    vip_stale_land_s: float = 2.0
    #: Two drones' MEASURED positions inside this fraction of the hard-floor
    #: ellipsoid land everything (0.7 = 0.25 m across, 0.43 m vertically).
    #: The CBF works on setpoints; this is the check on the aircraft.
    near_miss_ratio: float = 0.7

    # -- rules (guard/rules.py) ---------------------------------------------
    #: True: a defender that stays within tag_radius of an attacker for
    #: tag_time DOWNS it (it lands), as the STL game blocks intruders.
    #: False: no tagging; the defence can only deny, and the clock decides.
    #:
    #: The balance is a KNIFE EDGE (plan_guard sweep, 2026-11-03, shell v
    #: coordinated, 4 v 3): at strike_radius 2.4 the defence wins 11/12 with
    #: tag_time 1.10 s and loses 12/12 with 1.15 s, because each match is
    #: settled by one simultaneous exchange -- strike clock against tag
    #: clock. The strike radius has to reach past the "wall" a defender makes
    #: on the line (its own distance from the VIP + d_cc): at 1.6-2.2 m no
    #: attack strategy ever scored against 'shell'.
    tagging: bool = True
    tag_radius: float = 1.15
    tag_time: float = 1.1
    #: An attacker within strike_radius of the VIP for strike_time scores a
    #: strike (and then retires).
    strike_radius: float = 2.4
    strike_time: float = 1.0
    strikes_to_win: int = 1
    duration: float = 90.0


def problems(cfg):
    """What is wrong with a config, as plain sentences (empty = fine)."""
    bad = []
    if not cfg.floor < cfg.start_height < cfg.ceiling:
        bad.append(f'start_height {cfg.start_height:.2f} m is outside the band '
                   f'({cfg.floor:.2f}, {cfg.ceiling:.2f}) m')
    top = float(safety.ceiling_at(0.0))
    if cfg.ceiling > top:
        bad.append(f'ceiling {cfg.ceiling:.2f} m is above the {top:.2f} m the '
                   'arena has been flown to (arena.yaml)')
    if cfg.d_cc < cfg.min_separation:
        bad.append(f'd_cc {cfg.d_cc:.2f} m is under the hard floor '
                   f'min_separation {cfg.min_separation:.2f} m')
    if cfg.d_cc * cfg.cc_z_ratio < cfg.min_separation_z:
        bad.append(f'the keep-out is {cfg.d_cc * cfg.cc_z_ratio:.2f} m tall, under '
                   f'the {cfg.min_separation_z:.2f} m downwash floor')
    if cfg.min_separation < 0.2:
        bad.append(f'min_separation {cfg.min_separation:.2f} m is under the '
                   '0.20 m the STL game was designed to; nothing here has '
                   'evidence for closer')
    if cfg.v_max_safety < max(cfg.v_max_defense, cfg.v_max_attack):
        bad.append('v_max_safety must be at least both team caps')
    if cfg.tagging and cfg.tag_radius <= cfg.d_cc:
        bad.append(f'tag_radius {cfg.tag_radius:.2f} m is inside the '
                   f'{cfg.d_cc:.2f} m the safety layer keeps between drones, '
                   'so nobody could ever be tagged')
    if cfg.strike_radius <= cfg.d_vip:
        bad.append(f'strike_radius {cfg.strike_radius:.2f} m is inside the '
                   f'{cfg.d_vip:.2f} m keep-out around the VIP, so nobody '
                   'could ever strike')
    if not 0.0 < cfg.near_miss_ratio < 1.0:
        bad.append('near_miss_ratio must be between 0 and 1 (a fraction of '
                   'the hard floor), or ordinary tracking error lands the show')
    return bad


def override(cfg, values):
    """Set the config fields named in ``values`` (unknown names raise)."""
    known = {f.name for f in fields(cfg)}
    for k, v in values.items():
        if k not in known:
            raise KeyError(f'GuardConfig has no field {k!r}')
        cur = getattr(cfg, k)
        if isinstance(cur, bool):
            v = v if isinstance(v, bool) else str(v).lower() in ('1', 'true', 'yes')
        elif isinstance(cur, tuple):
            v = tuple(float(x) for x in v)
        else:
            v = type(cur)(v)
        setattr(cfg, k, v)
    return cfg
