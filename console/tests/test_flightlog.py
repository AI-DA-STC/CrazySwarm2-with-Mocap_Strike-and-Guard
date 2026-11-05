"""Every flight the console starts is recorded (mission_console/flightlog.py).

Stdlib only, no ROS: a fake `ros2` on PATH stands in for `ros2 bag record`
(it runs until SIGINT, like the real one) and for `ros2 run ... flight_report`.

    cd console && python3 -m unittest discover -s tests -v
"""

import json
import os
import stat
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mission_console import flightlog as F         # noqa: E402
from mission_console import procs as P             # noqa: E402

FAKE_ROS2 = '''#!/usr/bin/env python3
import os, signal, sys, time
log = os.environ['FAKE_ROS2_LOG']
with open(log, 'a') as fh:
    fh.write(' '.join(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['bag', 'record']:
    out = sys.argv[sys.argv.index('-o') + 1]
    os.makedirs(out)
    done = []
    signal.signal(signal.SIGINT, lambda *a: done.append(1))
    while not done:
        time.sleep(0.05)
    open(os.path.join(out, 'metadata.yaml'), 'w').write('closed: true\\n')
'''


def _wait(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class Recording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        bindir = os.path.join(self.tmp, 'bin')
        os.makedirs(bindir)
        ros2 = os.path.join(bindir, 'ros2')
        with open(ros2, 'w') as fh:
            fh.write(FAKE_ROS2)
        os.chmod(ros2, os.stat(ros2).st_mode | stat.S_IEXEC)
        self.calls = os.path.join(self.tmp, 'calls.log')
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ['PATH'],
                   FAKE_ROS2_LOG=self.calls, FLIGHT_LOG_ROOT=os.path.join(self.tmp, 'logs'),
                   ROS_DOMAIN_ID='77')
        self._old = {k: os.environ.get(k) for k in ('FLIGHT_LOG_ROOT',)}
        os.environ['FLIGHT_LOG_ROOT'] = env['FLIGHT_LOG_ROOT']
        self.pm = P.ProcessManager(P.EventBus(), self.tmp, env=env)
        self.pm.recorder = F.FlightRecorder(self.pm, self.tmp)
        F.TAIL_S = 0.2

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _fly(self, script):
        argv = [sys.executable, '-c', script]
        proc = self.pm.start('mission:crazyflie_shows/guard:main', 'Guard', argv)
        self.assertTrue(_wait(lambda: not proc.running))
        folders = os.listdir(os.environ['FLIGHT_LOG_ROOT'])
        self.assertEqual(len(folders), 1)
        folder = os.path.join(os.environ['FLIGHT_LOG_ROOT'], folders[0])
        self.assertTrue(_wait(lambda: json.load(open(os.path.join(folder, 'meta.json')))
                              .get('ended') is not None))
        return proc, folder

    def test_a_flight_gets_a_folder_with_output_bag_meta_and_a_report(self):
        proc, folder = self._fly(
            'import os; print("MATCH LIVE"); print("NEAR MISS cf1/cf2 0.21 m apart");'
            'print("dir", os.environ["FLIGHT_LOG_DIR"])')
        out = open(os.path.join(folder, 'output.log')).read()
        self.assertIn('NEAR MISS cf1/cf2 0.21 m apart', out)
        self.assertIn(f'dir {folder}', out)                  # the show was told
        self.assertRegex(out.splitlines()[1], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3} ')
        meta = json.load(open(os.path.join(folder, 'meta.json')))
        self.assertEqual(meta['returncode'], 0)
        self.assertEqual(meta['ros_domain_id'], '77')
        self.assertTrue(meta['bag'])
        # the bag was stopped politely (SIGINT), so it closed its file
        self.assertTrue(os.path.exists(os.path.join(folder, 'bag', 'metadata.yaml')))
        self.assertTrue(_wait(lambda: 'flight_report' in open(self.calls).read()))
        calls = open(self.calls).read().splitlines()
        self.assertTrue(calls[0].startswith('bag record -s mcap -o '))
        self.assertIn(f'run crazyflie_shows flight_report {folder}', calls)
        self.assertIn(f'[flight log] saved in {folder}', [r[2] for r in proc.lines])

    def test_a_failing_flight_is_recorded_too(self):
        proc, folder = self._fly('import sys; print("Traceback: boom"); sys.exit(3)')
        meta = json.load(open(os.path.join(folder, 'meta.json')))
        self.assertEqual(meta['returncode'], 3)
        self.assertEqual(meta['state'], 'failed')

    def test_only_flights_are_recorded(self):
        p = self.pm.start('srv.takeoff', 'Take off', [sys.executable, '-c', 'print(1)'])
        self.assertTrue(_wait(lambda: not p.running))
        time.sleep(0.3)
        self.assertFalse(os.path.exists(os.environ['FLIGHT_LOG_ROOT']))

    def test_switched_off(self):
        os.environ['MISSION_CONSOLE_FLIGHT_LOG'] = '0'
        try:
            p = self.pm.start('fly.script', 'Fly', [sys.executable, '-c', 'print(1)'])
            self.assertTrue(_wait(lambda: not p.running))
            time.sleep(0.3)
            self.assertFalse(os.path.exists(os.environ['FLIGHT_LOG_ROOT']))
        finally:
            os.environ.pop('MISSION_CONSOLE_FLIGHT_LOG')

    def test_slug_is_the_script(self):
        self.assertEqual(F._slug(['ros2', 'run', 'crazyflie_shows', 'guard_show',
                                  '--ros-args', '-p', 'x:=1']), 'guard_show')
        self.assertEqual(F._slug(['/usr/bin/python3', '-c', 'x']), 'python3')


if __name__ == '__main__':
    unittest.main()
