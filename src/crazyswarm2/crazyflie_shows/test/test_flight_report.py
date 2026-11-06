"""flight_report on a synthetic bag whose answers are known.

    PYTHONPATH=src/crazyswarm2/crazyflie_shows python3 -m pytest -q \\
        src/crazyswarm2/crazyflie_shows/test
"""

import json
import math

import numpy as np
import pytest

rosbag2_py = pytest.importorskip('rosbag2_py')
from rclpy.serialization import serialize_message                    # noqa: E402

from crazyflie_shows import flight_report                              # noqa: E402

LAG = 0.20          # s the aircraft trail their commands
T = 20.0            # s of flight
GLITCH_T = 8.0      # cf2's pose jumps onto cf1 for one frame


def _cmd(t, k):
    """Commanded path of drone k: a circle, 1 m up."""
    w = 0.5
    return np.array([np.cos(w * t + k * np.pi) * 1.5, np.sin(w * t + k * np.pi) * 1.5,
                     1.0 + 0.1 * k])


def _write(folder):
    from crazyflie_interfaces.msg import FullState, LogDataGeneric, Status
    from geometry_msgs.msg import PoseStamped
    from motion_capture_tracking_interfaces.msg import NamedPose, NamedPoseArray
    from rcl_interfaces.msg import Log

    w = rosbag2_py.SequentialWriter()
    w.open(rosbag2_py.StorageOptions(uri=str(folder / 'bag'), storage_id='mcap'),
           rosbag2_py.ConverterOptions('cdr', 'cdr'))
    topics = {'/poses': 'motion_capture_tracking_interfaces/msg/NamedPoseArray',
              '/rosout': 'rcl_interfaces/msg/Log',
              '/cf2/downwash': 'crazyflie_interfaces/msg/LogDataGeneric'}
    for n in ('cf1', 'cf2'):
        topics[f'/{n}/cmd_full_state'] = 'crazyflie_interfaces/msg/FullState'
        topics[f'/{n}/status'] = 'crazyflie_interfaces/msg/Status'
        topics[f'/{n}/pose'] = 'geometry_msgs/msg/PoseStamped'
    for i, (name, typ) in enumerate(topics.items()):
        w.create_topic(rosbag2_py.TopicMetadata(id=i, name=name, type=typ,
                                                serialization_format='cdr'))
    t0 = 1_000.0

    def put(topic, msg, t):
        w.write(topic, serialize_message(msg), int((t0 + t) * 1e9))

    for k in range(int(T * 100)):                       # mocap, 100 Hz
        t = k / 100.0
        arr = NamedPoseArray()
        for j, n in enumerate(('cf1', 'cf2')):
            p = _cmd(t - LAG, j)
            if n == 'cf2' and abs(t - GLITCH_T) < 0.005:
                p = _cmd(t - LAG, 0)                    # a swapped rigid body
            np_ = NamedPose()
            np_.name = n
            np_.pose.position.x, np_.pose.position.y, np_.pose.position.z = map(float, p)
            np_.pose.orientation.w = 1.0
            arr.poses.append(np_)
        dji = NamedPose()
        dji.name = 'operator'
        dji.pose.position.z = 1.3
        dji.pose.orientation.w = 1.0
        arr.poses.append(dji)
        put('/poses', arr, t)
    for k in range(int(T * 20)):                        # commands, 20 Hz
        t = k / 20.0
        if 5.0 < t < 5.6:                               # a radio stall on cf1
            continue
        for j, n in enumerate(('cf1', 'cf2')):
            m = FullState()
            m.pose.position.x, m.pose.position.y, m.pose.position.z = map(float, _cmd(t, j))
            put(f'/{n}/cmd_full_state', m, t)
    for k in range(int(T * 10)):                        # onboard pose, 10 Hz
        t = k / 10.0
        for j, n in enumerate(('cf1', 'cf2')):
            m = PoseStamped()
            p = _cmd(t - LAG, j)
            m.pose.position.x, m.pose.position.y, m.pose.position.z = map(float, p)
            yaw = math.radians(30.0) if n == 'cf2' else 0.0   # cf2's heading is off
            m.pose.orientation.z, m.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
            put(f'/{n}/pose', m, t)
    for k in range(int(T)):                             # status, 1 Hz
        for n in ('cf1', 'cf2'):
            m = Status()
            m.battery_voltage = 4.1 - 0.02 * k
            m.rssi = 40
            m.latency_unicast = 8 if k != 10 else 60
            m.num_rx_unicast = 900
            m.supervisor_info = 16 | (32 if n == 'cf2' and k == 15 else 0)
            put(f'/{n}/status', m, float(k))
    for k in range(int(T * 10)):                        # downwash block, 10 Hz
        m = LogDataGeneric()
        m.values = [2.0, 1.0, 40000.0, 1.0] + [50000.0 if k == 50 else 42000.0] * 4
        put('/cf2/downwash', m, k / 10.0)
    log = Log()
    log.level, log.name, log.msg = 30, 'crazyflie_server', 'cf1: link quality 0.81'
    put('/rosout', log, 3.0)
    w = None                                            # closes the bag
    (folder / 'output.log').write_text(
        '2026-11-05T10:00:01.000 [t+  8.0s] NEAR MISS cf1/cf2 0.05 m apart\n'
        '2026-11-05T10:00:02.000 nothing to see\n')
    (folder / 'meta.json').write_text(json.dumps({'cmdline': 'ros2 run x y',
                                                  'git': {'head': 'abc', 'dirty': True}}))


@pytest.fixture(scope='module')
def report(tmp_path_factory):
    folder = tmp_path_factory.mktemp('flight')
    _write(folder)
    return flight_report.build(str(folder)), folder


def test_lag_is_found_and_taken_out(report):
    rep, _ = report
    tr = rep['drones']['cf1']['tracking']
    assert abs(tr['lag_s'] - LAG) <= 0.02
    assert tr['error']['mean'] > 0.1             # late, so the raw error is large
    assert tr['residual']['p95'] < 0.03          # ... and almost all of it is lag


def test_command_stall_is_counted(report):
    rep, _ = report
    c = rep['drones']['cf1']['commands']
    assert c['stalls'] == 1 and 0.59 <= c['longest_stall_s'] <= 0.71
    assert rep['drones']['cf2']['commands']['stalls'] == 1      # both lost it
    assert abs(c['hz'] - 20.0) < 0.5


def test_mocap_jump_is_counted_as_a_glitch(report):
    rep, _ = report
    assert rep['drones']['cf2']['mocap']['jumps'] >= 1
    assert rep['drones']['cf1']['mocap']['jumps'] == 0
    assert abs(rep['drones']['cf1']['mocap']['hz'] - 100.0) < 1.0


def test_a_gap_while_the_recorder_starts_is_not_a_dropout():
    t = np.r_[0.0, 0.32, np.arange(0.34, 5.0, 0.02), np.arange(5.3, 8.0, 0.02)]
    track = np.column_stack([t, np.zeros((len(t), 4))])
    h = flight_report.mocap_health(track)
    assert h['dropouts'] == 1 and abs(h['longest_gap_s'] - 0.32) < 0.02   # only t 5.0


def test_estimate_yaw_disagreement(report):
    rep, _ = report
    assert abs(rep['drones']['cf2']['estimate']['yaw_deg']['p95'] - 30.0) < 1.0
    assert rep['drones']['cf1']['estimate']['yaw_deg']['p95'] < 1.0


def test_downwash_block_is_read(report):
    rep, _ = report
    eff = rep['drones']['cf2']['effort']
    assert eff['samples'] == int(T * 10)
    assert eff['motor_max_pct'] == pytest.approx(100 * 50000 / 65535, abs=0.1)
    assert 'effort' not in rep['drones']['cf1']
    assert rep['fleet']['downwash']['logged'] == ['cf2']


def test_battery_radio_and_flags(report):
    rep, _ = report
    st = rep['drones']['cf2']['status']
    assert st['battery_start'] == pytest.approx(4.1)
    assert st['battery_min'] == pytest.approx(4.1 - 0.02 * 19, abs=1e-4)
    assert st['latency_ms_max'] == 60
    assert st['flags'] == ['tumbled']


def test_pairs_and_other_bodies(report):
    rep, _ = report
    cp = rep['fleet']['closest_pair']
    assert cp['pair'] == 'cf1/cf2' and cp['gap'] < 0.2      # the glitch frame
    assert abs(cp['t'] - GLITCH_T) < 0.05
    assert cp['cmd_gap'] > 2.5                              # the commands never met
    assert cp['mocap_jump_nearby']                          # ... so: a glitch
    assert 'MOCAP GLITCH' in flight_report.text(rep)
    assert rep['fleet']['closest_to_other_bodies']['operator']['gap'] > 1.0


def test_text_report_names_the_alarms_and_writes_files(report):
    rep, folder = report
    txt = flight_report.text(rep)
    assert 'NEAR MISS cf1/cf2' in txt and 'nothing to see' not in txt
    assert 'link quality' in txt and 'uncommitted' in txt
    assert flight_report.main([str(folder)]) == 0
    assert (folder / 'report.txt').exists() and (folder / 'report.json').exists()


# ------------------------------------------------------------- downwash
def _track(t, f):
    return np.array([[x, *f(x), 0.0] for x in t])


def test_downwash_event_is_found_with_its_effort():
    t = np.arange(0.0, 12.0, 0.01)

    def victim(x):            # holds 1.0 m, sinks 0.12 m while cf1 is over it
        sink = 0.12 * np.exp(-((x - 5.6) / 0.25) ** 2)
        return 0.0, 0.0, 1.0 - sink

    def above(x):             # crosses over cf2 0.5 m higher between t 5 and 6
        return -2.0 + 0.4 * x, 0.05, 1.5

    def passer(x):            # crosses at t 9, 0.6 m higher, cf2 does not sink
        return 0.05, -3.6 + 0.4 * x, 1.6

    mocap = {'cf1': _track(t, above), 'cf2': _track(t, victim),
             'cf3': _track(t, passer)}
    cmd = {'cf2': np.array([[x, 0.0, 0.0, 1.0] for x in t[::5]])}
    tt = np.arange(0.0, 12.0, 0.1)
    thrust = np.where(abs(tt - 5.6) < 0.3, 52000.0, 40000.0)
    motor = np.where(abs(tt - 5.6) < 0.3, 64000.0, 42000.0)
    dw = {'cf2': np.column_stack([tt, np.full_like(tt, 3.0), np.full_like(tt, 4.0), thrust,
                                  np.where(abs(tt - 5.6) < 0.3, 0.8, 1.0),
                                  motor, motor, motor, motor])}
    ev, harmless = flight_report.downwash(mocap, cmd, dw, flight_report.DW_VARS,
                                          ['cf1', 'cf2', 'cf3'])
    assert len(ev) == 1
    e = ev[0]
    assert (e['victim'], e['above']) == ('cf2', 'cf1')
    assert abs(e['sink'] - 0.12) < 0.02 and abs(e['dz'] - 0.5) < 0.1
    assert e['motor_max_pct'] > 95 and e['thrust_up_pct'] > 25
    assert e['acc_z_min_g'] == pytest.approx(0.8)
    assert harmless == 1                                   # cf3 over cf2 at t 9
    eff = flight_report.effort(dw['cf2'], flight_report.DW_VARS)
    assert eff['saturated_s'] > 0.3 and eff['tilt_max_deg'] == pytest.approx(5.0)


def test_the_dji_has_a_wider_cone():
    t = np.arange(0.0, 6.0, 0.01)
    cf = _track(t, lambda x: (0.0, 0.0, 1.0 - (0.1 if 2.0 < x < 3.0 else 0.0)))
    dji = _track(t, lambda x: (0.7, 0.0, 2.5))            # 0.7 m across, 1.5 m up
    ev, _ = flight_report.downwash({'cf1': cf, 'operator': dji}, {}, {},
                                   flight_report.DW_VARS, ['cf1'])
    assert [e['above'] for e in ev] == ['operator']
    # the same geometry from a Crazyflie is outside its cone
    ev, _ = flight_report.downwash({'cf1': cf, 'cf9': dji}, {}, {},
                                   flight_report.DW_VARS, ['cf1', 'cf9'])
    assert ev == []


def test_downwash_var_order_comes_from_the_flight_config(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'crazyflies.yaml').write_text(
        'all:\n  firmware_logging:\n    custom_topics:\n      downwash:\n'
        '        vars: [motor.m1, stabilizer.thrust]\n')
    assert flight_report.dw_vars(str(tmp_path)) == ['motor.m1', 'stabilizer.thrust']
    assert flight_report.dw_vars(str(tmp_path / 'nope')) == flight_report.DW_VARS


def test_the_shipped_roster_keeps_the_downwash_block_off_by_default():
    """Off by default (radio airtime); its commented recipe keeps DW_VARS' order."""
    import os
    import yaml
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'crazyflie', 'config',
                        'crazyflies.yaml')
    doc = yaml.safe_load(open(path))
    assert 'downwash' not in (doc['all']['firmware_logging'].get('custom_topics') or {})
    lines = open(path).read().splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.strip() == '# downwash:')
    recipe = []
    for ln in lines[k + 3:]:                     # past "frequency:" and "vars:"
        if not ln.strip().startswith('#     - '):
            break
        recipe.append(ln.split('- ')[1].split()[0])
    assert recipe == flight_report.DW_VARS
