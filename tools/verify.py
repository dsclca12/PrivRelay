#!/usr/bin/env python3
"""Cross-platform verification with isolated, opt-in container lifecycle checks."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def executable(name):
    return shutil.which(name) or name


def run(command, cwd=ROOT, env=None):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android', action='store_true')
    parser.add_argument('--containers', action='store_true')
    args = parser.parse_args()
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report_dir = ROOT / 'artifacts' / f'verify-{stamp}-{uuid.uuid4().hex[:6]}'
    report_dir.mkdir(parents=True)
    results = []

    def check(name, fn):
        start = time.monotonic()
        try:
            fn()
            results.append(dict(name=name, status='passed', seconds=round(time.monotonic()-start, 2)))
        except (subprocess.CalledProcessError, OSError, RuntimeError) as error:
            results.append(dict(name=name, status='failed', error=str(error)))
        (report_dir / 'report.json').write_text(json.dumps(results, indent=2), encoding='utf8')

    go, npm, node, flutter = map(executable, ('go', 'npm', 'node', 'flutter'))
    check('go-race', lambda: run([go, 'test', '-race', './...', '-count=1', '-timeout=120s'], ROOT/'server'))
    check('go-vet', lambda: run([go, 'vet', './...'], ROOT/'server'))
    check('upstream-checksums', lambda: run([sys.executable, 'tools/verify_upstream.py']))

    def web():
        major = int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0])
        if major < 22:
            raise RuntimeError('Use Node 22 or newer (see .nvmrc)')
        run([npm, 'ci', '--prefix', 'web_client'])
        run([npm, 'test', '--prefix', 'web_client'])
        run([npm, 'run', 'build', '--prefix', 'web_client'])
        binary = ROOT/'artifacts'/('privrelay-server.exe' if os.name == 'nt' else 'privrelay-server')
        run([go, 'build', '-trimpath', '-o', binary, '.'], ROOT/'server')
        run([node, 'tools/smoke_web.mjs'])
    check('web-and-live-server', web)
    if args.android:
        def android():
            actual = json.loads(subprocess.check_output([flutter, '--version', '--machine'], text=True))['frameworkVersion']
            expected = json.loads((ROOT/'.fvmrc').read_text())['flutter']
            if actual != expected:
                raise RuntimeError(f'Use Flutter {expected}; installed {actual}')
            client = ROOT/'android_client'
            for command in ([flutter, 'pub', 'get', '--enforce-lockfile'],
                            [executable('dart'), 'run', 'build_runner', 'build'],
                            [flutter, 'analyze'], [flutter, 'test'],
                            [flutter, 'build', 'apk', '--debug', '--flavor', 'dev']):
                run(command, client)
            run(['cmd', '/c', 'gradlew.bat', ':app:testDevDebugUnitTest'] if os.name == 'nt'
                else ['bash', 'gradlew', ':app:testDevDebugUnitTest'], client/'android')
        check('android', android)
    if args.containers:
        def containers():
            env = os.environ.copy()
            env['COMPOSE_PROJECT_NAME'] = 'privrelay-test-' + uuid.uuid4().hex[:12]
            env['PRIVRELAY_COMPOSE_TEST'] = '1'
            # Avoid inheriting real service credentials or private classifier routes.
            env['CLASSIFIER_URL'] = 'http://classifier:8000'
            env['CLASSIFIER_API_KEY'] = ''
            env['PRIVATESMS_DECISION_THRESHOLD'] = ''
            env.pop('COMPOSE_FILE', None)
            env.pop('COMPOSE_PROFILES', None)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                env['PRIVRELAY_PORT'] = str(listener.getsockname()[1])
            docker = executable('docker')
            try:
                run([docker, 'compose', 'build'], env=env)
                run([docker, 'compose', 'up', '-d', '--wait', '--wait-timeout', '240'], env=env)
                run([node, 'tools/smoke_compose.mjs'], env=env)
            finally:
                run([docker, 'compose', 'down', '--volumes'], env=env)
        check('containers', containers)
    print(f'Verification report: {report_dir / "report.json"}')
    return int(any(row['status'] != 'passed' for row in results))


if __name__ == '__main__':
    sys.exit(main())
