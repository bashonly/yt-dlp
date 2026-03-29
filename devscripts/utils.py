#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections.abc
import contextlib
import datetime as dt
import functools
import io
import re
import subprocess
import urllib.request
import zipfile


def read_file(fname):
    with open(fname, encoding='utf-8') as f:
        return f.read()


def write_file(fname, content, mode='w'):
    with open(fname, mode, encoding='utf-8') as f:
        return f.write(content)


def read_version(fname='yt_dlp/version.py', varname='__version__'):
    """Get the version without importing the package"""
    items = {}
    exec(compile(read_file(fname), fname, 'exec'), items)
    return items[varname]


def calculate_version(version=None, fname='yt_dlp/version.py'):
    if version and '.' in version:
        return version

    revision = version
    version = dt.datetime.now(dt.timezone.utc).strftime('%Y.%m.%d')

    if revision:
        assert re.fullmatch(r'[0-9]+', revision), 'Revision must be numeric'
    else:
        old_version = read_version(fname=fname).split('.')
        if version.split('.') == old_version[:3]:
            revision = str(int(([*old_version, 0])[3]) + 1)

    return f'{version}.{revision}' if revision else version


def get_filename_args(has_infile=False, default_outfile=None):
    parser = argparse.ArgumentParser()
    if has_infile:
        parser.add_argument('infile', help='Input file')
    kwargs = {'nargs': '?', 'default': default_outfile} if default_outfile else {}
    parser.add_argument('outfile', **kwargs, help='Output file')

    opts = parser.parse_args()
    if has_infile:
        return opts.infile, opts.outfile
    return opts.outfile


def compose_functions(*functions):
    return lambda x: functools.reduce(lambda y, f: f(y), functions, x)


def run_process(*args, **kwargs):
    kwargs.setdefault('text', True)
    kwargs.setdefault('check', True)
    kwargs.setdefault('capture_output', True)
    if kwargs['text']:
        kwargs.setdefault('encoding', 'utf-8')
        kwargs.setdefault('errors', 'replace')
    return subprocess.run(args, **kwargs)


def request(url: str):
    return contextlib.closing(urllib.request.urlopen(url))


def list_wheel_contents(
        wheel_data: bytes,
        package_dir: str,
        suffix: str | None = None,
        folders: bool = True,
        files: bool = True,
        excludes: list[str] | None = None,
) -> str:
    assert folders or files, 'at least one of "folders" or "files" must be True'

    if excludes is None:
        excludes = []

    with zipfile.ZipFile(io.BytesIO(wheel_data)) as zipf:
        path_gen = (zinfo.filename for zinfo in zipf.infolist())

    filtered = filter(lambda path: path.startswith(f'{package_dir}/') and path not in excludes, path_gen)
    if suffix:
        filtered = filter(lambda path: path.endswith(f'.{suffix}'), filtered)

    files_list = list(filtered)
    if not folders:
        return ' '.join(files_list)

    folders_list = list(dict.fromkeys(path.rpartition('/')[0] for path in files_list))
    if not files:
        return ' '.join(folders_list)

    return ' '.join(folders_list + files_list)


def requirements_needs_update(
    lines: collections.abc.Iterable[str],
    package: str,
    version: str,
):
    identifier = f'{package}=='
    for line in lines:
        if line.startswith(identifier):
            return not line.removeprefix(identifier).startswith(version)

    return False


def requirements_update(
    lines: collections.abc.Iterable[str],
    package: str,
    new_version: str,
    new_hashes: list[str],
):
    first_comment = True
    current = []
    for line in lines:
        if not line.endswith('\n'):
            line += '\n'

        if first_comment:
            comment_line = line.strip()
            if comment_line.startswith('#'):
                yield line
                continue

            first_comment = False
            yield '# It was later updated using devscripts/update_ejs.py\n'

        current.append(line)
        if line.endswith('\\\n'):
            # continue logical line
            continue

        if not current[0].startswith(f'{package}=='):
            yield from current

        else:
            yield f'{package}=={new_version} \\\n'
            for digest in new_hashes[:-1]:
                yield f'    --hash={digest} \\\n'
            yield f'    --hash={new_hashes[-1]}\n'

        current.clear()
