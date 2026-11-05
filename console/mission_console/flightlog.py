"""Flight logs: every flight the console starts is recorded, just in case.

The console already keeps the operator's choices (settings.json) and how the
console is used (usage.jsonl). A flight's own record lived only in a ring
buffer in memory: a NEAR MISS line was gone with the console. So for every
process ``procs.is_flight`` says commands drones (the Dashboard's Fly, every
mission's main script), the console makes ONE folder:

    ~/.ros/flight_logs/<YYYYmmdd_HHMMSS>_<script>/
        output.log      every line the show printed, wall-clock stamped
        meta.json       what ran (argv, cwd), when, how it ended, the git
                        commit and whether the tree was dirty, ROS_DOMAIN_ID
        config/         crazyflies.yaml and arena.yaml as they were
        bag/            a ros2 bag (mcap): /poses, every drone's commands,
                        onboard pose, status and kalman_preflight, /rosout
        report.txt      written after the flight by
        report.json     `ros2 run crazyflie_shows flight_report <folder>`
        guard_trace.csv (guard_show only: it writes into $FLIGHT_LOG_DIR)

The recorder and the report are ordinary console processes: they show up in
the live console with their exact command lines, like everything else here
(the CLI-only rule: `ros2 bag record`, never an in-process subscriber). The
show is told where its folder is through $FLIGHT_LOG_DIR.

scripts/record_flight.sh makes the same folder for a flight started from a
terminal. docs/details/flight-logs.md says what is in it and how to read it.

``FLIGHT_LOG_ROOT`` moves the folders; ``MISSION_CONSOLE_FLIGHT_LOG=0`` turns
recording off. Nothing is ever deleted automatically: a flight is about
6 MB a minute.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import threading
import time

from .procs import run_capture

#: What the bag records. Regex, so a drone added to the roster is recorded
#: without editing this. The show markers (/guard/markers) are left out on
#: purpose: they are ~1.5 MB/s and the show's own trace keeps the intents.
TOPIC_REGEX = (r'^/(poses|rosout)$'
               r'|^/cf[0-9]+/(cmd_full_state|cmd_position|cmd_hover|cmd_vel_legacy'
               r'|pose|status|kalman_preflight|downwash)$'
               r'|^/escort/vip$')
CONFIG_FILES = ('src/crazyswarm2/crazyflie/config/crazyflies.yaml',
                'src/crazyswarm2/crazyflie/config/arena.yaml')
TAIL_S = 2.0          # keep recording this long after the show exits


def root():
    return os.path.expanduser(os.environ.get('FLIGHT_LOG_ROOT', '~/.ros/flight_logs'))


def enabled():
    return os.environ.get('MISSION_CONSOLE_FLIGHT_LOG', '1') not in ('0', 'false', 'no')


def _slug(argv):
    """The script's name: `ros2 run crazyflie_shows guard_show ...` -> guard_show."""
    words = [a for a in argv if not a.startswith('-')]
    if len(words) >= 4 and words[0].endswith('ros2') and words[1] == 'run':
        name = words[3]
    else:
        name = os.path.basename(words[0]) if words else 'flight'
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', name)[:40] or 'flight'


def _iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t)) + f'.{int(t % 1 * 1000):03d}'


class _Run:
    def __init__(self, folder, proc):
        self.folder = folder
        self.proc = proc
        self.bag = None
        self.out = open(os.path.join(folder, 'output.log'), 'a', encoding='utf-8')
        self.meta = {}
        self.lock = threading.Lock()


class FlightRecorder:
    def __init__(self, pm, repo):
        self.pm = pm
        self.repo = repo
        self.runs = {}                 # flight proc id -> _Run
        self._lock = threading.Lock()

    # -- called by ProcessManager -------------------------------------------
    def prepare(self, proc):
        """Before the flight starts: make its folder. Returns env additions."""
        if not enabled():
            return {}
        try:
            base = os.path.join(root(), time.strftime('%Y%m%d_%H%M%S_',
                                                      time.localtime(proc.started))
                                + _slug(proc.argv))
            folder, k = base, 1
            while os.path.exists(folder):
                k += 1
                folder = f'{base}_{k}'
            os.makedirs(os.path.join(folder, 'config'))
            for rel in CONFIG_FILES:
                src = os.path.join(self.repo, rel)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(folder, 'config'))
            run = _Run(folder, proc)
            run.meta = self._meta(proc)
            self._write_meta(run)
        except Exception as exc:                        # noqa: BLE001
            # a log that cannot be written must never stop a flight
            proc.note = (proc.note + f' (flight log off: {exc})').strip()
            return {}
        with self._lock:
            self.runs[proc.id] = run
        return {'FLIGHT_LOG_DIR': folder}

    def started(self, proc):
        """The flight is running: start the bag beside it."""
        run = self.runs.get(proc.id)
        if run is None:
            return
        argv = ['ros2', 'bag', 'record', '-s', 'mcap',
                '-o', os.path.join(run.folder, 'bag'), '--regex', TOPIC_REGEX]
        run.bag = self.pm.start('flightlog.bag', f'Flight recorder ({proc.label})', argv,
                                kind='service',
                                note=f'records the flight to {run.folder}')
        self.pm._emit_line(proc, f'[flight log] recording to {run.folder}')

    def line(self, proc, t, text):
        run = self.runs.get(proc.id)
        if run is None:
            return
        with run.lock:
            if run.out is not None:
                try:
                    run.out.write(f'{_iso(t)} {text}\n')
                    run.out.flush()
                except Exception:                       # noqa: BLE001
                    pass

    def finished(self, proc):
        """The flight exited: stop the bag after a short tail, finish the
        metadata, then run the report."""
        with self._lock:
            run = self.runs.pop(proc.id, None)
        if run is None:
            return
        threading.Thread(target=self._finish, args=(run,), daemon=True).start()

    # -- internals ----------------------------------------------------------
    def _finish(self, run):
        proc = run.proc
        time.sleep(TAIL_S)
        if run.bag is not None and run.bag.running:
            self.pm.stop(run.bag.id)
            deadline = time.time() + 15.0
            while run.bag.running and time.time() < deadline:
                time.sleep(0.2)
        with run.lock:
            try:
                run.out.close()
            except Exception:                           # noqa: BLE001
                pass
            run.out = None
        run.meta.update({
            'ended': proc.ended, 'ended_iso': _iso(proc.ended or time.time()),
            'returncode': proc.returncode, 'state': proc.state(),
            'bag': os.path.isdir(os.path.join(run.folder, 'bag')),
        })
        self._write_meta(run)
        if run.meta['bag']:
            self.pm.start('flightlog.report', f'Flight report ({proc.label})',
                          ['ros2', 'run', 'crazyflie_shows', 'flight_report', run.folder],
                          kind='task', note='what was commanded against what flew')
        self.pm._emit_line(proc, f'[flight log] saved in {run.folder}'
                           + ('' if run.meta['bag'] else ' (no bag was recorded)'))

    def _meta(self, proc):
        env = self.pm.env
        head = run_capture(['git', 'rev-parse', '--short', 'HEAD'], cwd=self.repo)
        dirty = run_capture(['git', 'status', '--porcelain'], cwd=self.repo)
        branch = run_capture(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=self.repo)
        return {
            'action_id': proc.action_id, 'label': proc.label,
            'argv': proc.argv, 'cmdline': proc.cmdline, 'cwd': proc.cwd,
            'started': proc.started, 'started_iso': _iso(proc.started),
            'host': socket.gethostname(),
            'ros_domain_id': env.get('ROS_DOMAIN_ID', ''),
            'sim': any('use_sim_time:=true' in a for a in proc.argv),
            'git': {'head': head['out'].strip() if head['rc'] == 0 else '',
                    'branch': branch['out'].strip() if branch['rc'] == 0 else '',
                    'dirty': bool(dirty['out'].strip()) if dirty['rc'] == 0 else None},
            'recorder': 'mission console',
            'topics': TOPIC_REGEX,
        }

    @staticmethod
    def _write_meta(run):
        tmp = os.path.join(run.folder, 'meta.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(run.meta, fh, indent=1)
        os.replace(tmp, os.path.join(run.folder, 'meta.json'))
