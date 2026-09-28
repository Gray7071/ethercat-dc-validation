#!/usr/bin/env python3
"""Archive explicitly named logs/configs, optionally take one read-only Linux snapshot.

Does not start an application, request OP, upload SDO, write registers, or use sudo.
Use completed immutable logs for reproducible hashes; capture live data in a non-RT logger.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform
import subprocess


def collect(files, out, metadata, master=None):
    if not isinstance(metadata, dict):
        raise ValueError('Metadata must be a JSON object')
    if master is not None and (platform.system() != 'Linux' or master < 0):
        raise ValueError('Snapshot requires Linux and a nonnegative master index')
    paths = [Path(p).resolve(strict=True) for p in files]
    if any(not p.is_file() for p in paths):
        raise ValueError('Inputs must be files')
    out.mkdir(parents=True, exist_ok=False)
    manifest = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'metadata': metadata, 'files': [], 'snapshots': []}
    for i, path in enumerate(paths):
        stat_before = path.stat()
        dest = out / (f'{i:03d}-' + path.name)
        digest = hashlib.sha256()
        with path.open('rb') as src, dest.open('xb') as target:
            for block in iter(lambda: src.read(1024 * 1024), b''):
                target.write(block)
                digest.update(block)
        stat_after = path.stat()
        manifest['files'].append({'name': dest.name, 'source_name': path.name,
                                  'sha256': digest.hexdigest(),
                                  'source_changed_during_copy': (stat_before.st_size, stat_before.st_mtime_ns) != (stat_after.st_size, stat_after.st_mtime_ns)})
    if master is not None:
        # Fixed argv only. No arbitrary commands or background polling.
        commands = [['uname', '-a'], ['ethercat', 'version'], ['modinfo', 'ec_master'],
                    ['ethercat', 'master', '-m', str(master)],
                    ['ethercat', 'slaves', '-m', str(master), '-v']]
        for argv in commands:
            record = {'argv': argv}
            try:
                p = subprocess.run(argv, capture_output=True, text=True, errors='replace', timeout=5, check=False)
                record.update(exit=p.returncode, stdout=p.stdout, stderr=p.stderr)
            except (OSError, subprocess.TimeoutExpired) as exc:
                record['unavailable'] = str(exc)
            manifest['snapshots'].append(record)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--file', action='append', required=True, type=Path)
    p.add_argument('--metadata', type=Path, help='Explicit case configuration JSON; no credentials')
    p.add_argument('--out', required=True, type=Path, help='New directory; existing directories refused')
    p.add_argument('--snapshot-master', type=int, help='Optional one-time, read-only CLI snapshot on Linux')
    a = p.parse_args()
    try:
        meta = json.loads(a.metadata.read_text(encoding='utf-8')) if a.metadata else {'configuration': 'not provided'}
        result = collect(a.file, a.out, meta, a.snapshot_master)
        print(json.dumps({'files': len(result['files']), 'snapshot_commands': len(result['snapshots'])}))
    except (OSError, ValueError) as exc:
        p.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
