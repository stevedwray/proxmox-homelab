#!/usr/bin/env python3
"""Write build expectations from saved /props replies and current build records."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

BACKENDS = {'nathanw': 'fork', 'upstream': 'upstream'}


def build_expectations(props_args, builds_root, link_args=()):
    links = {}
    for assignment in link_args:
        label, separator, link = assignment.partition("=")
        if not separator or label not in BACKENDS or link not in ("current", "candidate"):
            raise ValueError("--link must be nathanw=current|candidate or upstream=current|candidate")
        if label in links:
            raise ValueError(f"duplicate --link label: {label}")
        links[label] = link
    paths = {}
    for assignment in props_args:
        label, separator, path = assignment.partition('=')
        if not separator or not path or label not in BACKENDS:
            raise ValueError('--props must be nathanw=PATH or upstream=PATH')
        if label in paths:
            raise ValueError(f'duplicate --props label: {label}')
        paths[label] = Path(path)
    if set(paths) != set(BACKENDS):
        raise ValueError('both --props nathanw=PATH and --props upstream=PATH are required')
    result = {}
    for label, backend in BACKENDS.items():
        props = json.loads(paths[label].read_text())
        link = links.get(label, 'current')
        build_path = Path(builds_root) / backend / link / 'build.json'
        build = json.loads(build_path.read_text())
        if not isinstance(props, dict) or not isinstance(build, dict):
            raise ValueError(f'{label}: props and build record must be JSON objects')
        build_info = props.get('build_info')
        if not isinstance(build_info, str):
            raise ValueError(f'{label}: build_info must be a string')
        for field in ('model_alias', 'total_slots'):
            if field not in props:
                raise ValueError(f'{label}: props is missing {field}')
        settings = props.get('default_generation_settings')
        if 'n_ctx' not in props and not (isinstance(settings, dict) and 'n_ctx' in settings):
            raise ValueError(f'{label}: props is missing n_ctx or default_generation_settings.n_ctx')
        for field in ('name', 'sha'):
            if not isinstance(build.get(field), str) or not build[field]:
                raise ValueError(f'{label}: build record needs a non-empty {field} string')
        suffix = build_info.rsplit('-', 1)[-1]
        if '-' not in build_info or not suffix or not build['sha'].startswith(suffix):
            raise ValueError(f'{label}: build_info SHA does not match {link} build sha; redo the build check')
        result[label] = dict(name=build['name'], sha=build['sha'], build_info=build_info, props=props)
    return result


def write_new(path, expectations):
    """Publish a complete file atomically, without replacing any existing path."""
    path = Path(path)
    if os.path.lexists(path):
        raise FileExistsError(f'refusing to overwrite existing output: {path}')
    data = json.dumps(expectations, indent=2) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # link() fails if the destination appears during validation/writing.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--props', action='append', required=True, metavar='LABEL=PATH')
    parser.add_argument('--builds-root', type=Path, default=Path('/storage/llama-builds'))
    parser.add_argument('--link', action='append', default=[], metavar='LABEL=current|candidate',
                        help='choose a build link per props label; unspecified labels use current')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_expectations(args.props, args.builds_root, args.link)
        write_new(args.out, result)
    except (OSError, ValueError) as exc:
        print(f'write-build-expectations: {exc}', file=sys.stderr)
        return 1
    print(' '.join(f"{label} {result[label]['build_info']}" for label in BACKENDS))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
