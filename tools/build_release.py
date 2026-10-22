#!/usr/bin/env python3
"""Build APK/AAB and private symbols on Linux, macOS or Windows."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT/'android_client'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flavor', choices=['dev', 'prod'], default='dev')
    args = parser.parse_args()
    flutter = shutil.which('flutter') or 'flutter'
    version = json.loads(subprocess.check_output([flutter, '--version', '--machine'], text=True))
    expected = json.loads((ROOT/'.fvmrc').read_text())['flutter']
    if version['frameworkVersion'] != expected:
        raise SystemExit(f'Use Flutter {expected} from .fvmrc')
    if args.flavor == 'prod' and not (CLIENT/'android/key.properties').is_file():
        raise SystemExit('Production requires android/key.properties and your private signing key')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = ROOT/'artifacts/releases'/f'{args.flavor}-{stamp}-{uuid.uuid4().hex[:6]}'
    destination.mkdir(parents=True, mode=0o700)
    def run(*arguments):
        subprocess.run([flutter, *arguments], cwd=CLIENT, check=True)
    run('pub', 'get', '--enforce-lockfile')
    run('analyze')
    run('test')
    for kind in ['apk', 'appbundle']:
        run('build', kind, '--release', '--flavor', args.flavor, '--obfuscate',
            f'--split-debug-info={destination / "symbols" / kind}')
        artifact = CLIENT / (f'build/app/outputs/flutter-apk/app-{args.flavor}-release.apk' if kind == 'apk'
                            else f'build/app/outputs/bundle/{args.flavor}Release/app-{args.flavor}-release.aab')
        shutil.copy2(artifact, destination/artifact.name)
        mapping = CLIENT/f'build/app/outputs/mapping/{args.flavor}Release/mapping.txt'
        if mapping.exists():
            shutil.copy2(mapping, destination/f'{kind}-r8-mapping.txt')
    shutil.copy2(CLIENT/'pubspec.lock', destination/'pubspec.lock')
    files = [{'path': str(p.relative_to(destination)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(destination.rglob('*')) if p.is_file()]
    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=ROOT, text=True).strip()
    manifest = dict(flavor=args.flavor, created_at=stamp, flutter=version['frameworkVersion'],
                    dart=version['dartSdkVersion'], revision=git('rev-parse', 'HEAD'),
                    working_tree_dirty=bool(git('status', '--porcelain')), checks_skipped=False,
                    package_version=re.search(r'^version:\s*(.+)$', (CLIENT/'pubspec.yaml').read_text(), re.M)[1],
                    distribution='operator-signed' if args.flavor == 'prod' else 'internal-test-only', files=files)
    (destination/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    # Symbols remain private; the script never copies signing materials.
    if os.name != 'nt':
        for p in destination.rglob('*'):
            p.chmod(0o700 if p.is_dir() else 0o600)
        destination.chmod(0o700)
    print(f'Release and private symbols: {destination}')


if __name__ == '__main__':
    main()
