#!/usr/bin/env python3
"""Take and validate a SQLite snapshot without opening the source for writes."""
import argparse
import contextlib
import os
from pathlib import Path
import sqlite3
import time


def read_only(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def snapshot(source, destination, timeout=120):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('snapshot destination must differ from source')
    if not source.is_file():
        raise FileNotFoundError('source database does not exist')
    companions = [Path(str(destination) + suffix) for suffix in ('-wal', '-shm', '-journal')]
    if any(path.exists() for path in companions):
        raise FileExistsError('snapshot sidecar already exists')
    # Reserve exclusively: never overwrite an existing file or follow a symlink.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        deadline = time.monotonic() + timeout

        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError('SQLite backup exceeded time limit')

        with contextlib.closing(read_only(source)) as live:
            target = sqlite3.connect(destination)
            try:
                live.backup(target, pages=256, progress=progress, sleep=.05)
                # Keep the standalone snapshot self-contained, even when the
                # source uses WAL. This changes only the new destination.
                if target.execute('PRAGMA journal_mode=DELETE').fetchone() != ('delete',):
                    raise ValueError('cannot make snapshot self-contained')
            finally:
                target.close()
        check = read_only(destination)
        try:
            if check.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('snapshot integrity check failed')
        finally:
            check.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        for path in companions:
            path.unlink(missing_ok=True)
        raise
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    try:
        snapshot(args.source, args.destination, args.timeout)
    except (OSError, ValueError, sqlite3.Error, TimeoutError):
        parser.exit(1, 'Snapshot failed; no new snapshot retained (check source, destination and integrity).\n')
    print('SNAPSHOT-OK: online backup complete; integrity_check ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
