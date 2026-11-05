"""Every number the guard engine needs that is NOT a strategy's own.

Strategy tuning lives with each strategy (its ``DEFAULTS``) and the rule
numbers with each rule set (guard/rules/); this is the room, the aircraft
limits, the separation floor, the safety layer and the watchdogs -- the
things every strategy is held to, under every rule set.

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
    #: The near-miss watch on the MEASURED aircraft (guard/watch.py); the
    #: CBF works on setpoints, this is the check on the aircraft. Fractions
    #: of the hard-floor ellipsoid (min_separation across, min_separation_z
    #: vertically).
    #: SOFT: inside this for near_miss_ticks ticks in a row pauses the match
    #: (0.7 = 0.25 m across, 0.43 m vertically). Until 2026-11-05 it landed
    #: everything on one frame, which ended most hardware matches.
    near_miss_ratio: float = 0.7
    near_miss_ticks: int = 2
    #: HARD: inside this lands everything at once (0.55 = 0.19 m across,
    #: 0.34 m vertically; the STL game is designed to 0.18-0.20 m).
    near_miss_land_ratio: float = 0.55
    #: false = the old behaviour: a soft near miss lands everything.
    near_miss_pause: bool = True
    #: A pause ends when every pair is back outside this fraction ...
    near_miss_clear_ratio: float = 0.9
    #: ... and lands everything if that takes longer than this.
    near_miss_pause_s: float = 3.0
    #: A measured jump bigger than this in one tick is a mocap glitch (a
    #: swapped or ghost rigid body), not a flight: 0.30 m = 6 m/s at 20 Hz.
    mocap_jump_m: float = 0.30

    # The RULES (who can be downed, strikes, the clock) are not here: they
    # are a module of their own, chosen by name (guard/rules/).


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
    if not 0.0 < cfg.near_miss_ratio < 1.0:
        bad.append('near_miss_ratio must be between 0 and 1 (a fraction of '
                   'the hard floor), or ordinary tracking error lands the show')
    if not 0.0 < cfg.near_miss_land_ratio <= cfg.near_miss_ratio:
        bad.append('near_miss_land_ratio must be above 0 and no more than '
                   'near_miss_ratio (the hard line is inside the soft one)')
    if not cfg.near_miss_ratio < cfg.near_miss_clear_ratio <= 1.5:
        bad.append('near_miss_clear_ratio must be above near_miss_ratio, or a '
                   'pause could end with the pair still inside it')
    if cfg.near_miss_ticks < 1 or cfg.near_miss_pause_s <= 0.0:
        bad.append('near_miss_ticks must be >= 1 and near_miss_pause_s > 0')
    if cfg.mocap_jump_m < 2.0 * cfg.v_max_safety / cfg.rate_hz:
        bad.append(f'mocap_jump_m {cfg.mocap_jump_m:.2f} m is within reach of a real '
                   f'flight at v_max_safety (twice {cfg.v_max_safety / cfg.rate_hz:.2f} '
                   'm per tick): real moves would be ignored as glitches')
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
