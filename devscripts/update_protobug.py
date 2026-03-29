#!/usr/bin/env python3
from __future__ import annotations

# Allow direct execution
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import hashlib
import pathlib

from devscripts.utils import (
    list_wheel_contents,
    request,
    requirements_needs_update,
    requirements_update,
)


PACKAGE_NAME = 'protobug'
PREFIX = f'    "{PACKAGE_NAME}=='
LIBRARY_NAME = PACKAGE_NAME.replace('-', '_')
BASE_PATH = pathlib.Path(__file__).parent.parent
PYPROJECT_PATH = BASE_PATH / 'pyproject.toml'
RELEASE_URL = 'https://api.github.com/repos/yt-dlp/protobug/releases/latest'
MAKEFILE_PATH = BASE_PATH / 'Makefile'
REQUIREMENTS_PATH = BASE_PATH / 'bundle/requirements'


def protobug_makefile_variables(
        version: str | None = None,
        name: str | None = None,
        digest: str | None = None,
        data: bytes | None = None,
        keys_only: bool = False,
) -> dict[str, str | None]:
    assert keys_only or all(arg is not None for arg in (version, name, digest, data))

    return {
        'PROTOBUG_VERSION': None if keys_only else version,
        'PROTOBUG_WHEEL_NAME': None if keys_only else name,
        'PROTOBUG_WHEEL_HASH': None if keys_only else digest,
        'PROTOBUG_PY_FOLDERS': None if keys_only else list_wheel_contents(data, LIBRARY_NAME, 'py', files=False),
        'PROTOBUG_PY_FILES': None if keys_only else list_wheel_contents(
            data, LIBRARY_NAME, 'py', folders=False, excludes=[f'{LIBRARY_NAME}/__main__.py']),
    }


def main():
    current_version = None
    with PYPROJECT_PATH.open() as file:
        for line in file:
            if not line.startswith(PREFIX):
                continue
            current_version, _, _ = line.removeprefix(PREFIX).partition('"')

    if not current_version:
        print(f'{PACKAGE_NAME} dependency line could not be found')
        return

    makefile_info = protobug_makefile_variables(keys_only=True)
    prefixes = tuple(f'{key} = ' for key in makefile_info)
    with MAKEFILE_PATH.open() as file:
        for line in file:
            if not line.startswith(prefixes):
                continue
            key, _, val = line.partition(' = ')
            makefile_info[key] = val.rstrip()

    with request(RELEASE_URL) as resp:
        info = json.load(resp)

    version = info['tag_name']
    if version == current_version:
        print(f'{PACKAGE_NAME} is up to date! ({version})')
        return

    print(f'Updating {PACKAGE_NAME} from {current_version} to {version}')
    wheel_info = {}
    requirements_hashes = []
    for asset in info['assets']:
        name = asset['name']
        digest = asset['digest']

        # Is it the source distribution? If so, we only need its hash for the requirements files
        if name == f'{LIBRARY_NAME}-{version}.tar.gz':
            requirements_hashes.append(digest)
            continue

        # The only other asset we are looking for is the wheel
        if not (name.startswith(f'{LIBRARY_NAME}-') and name.endswith('.whl')):
            continue

        with request(asset['browser_download_url']) as resp:
            data = resp.read()

        # verify digest from github
        algo, _, expected = digest.partition(':')
        hexdigest = hashlib.new(algo, data).hexdigest()
        assert hexdigest == expected, f'downloaded attest mismatch ({hexdigest!r} != {expected!r})'

        requirements_hashes.append(digest)
        wheel_info = protobug_makefile_variables(version, asset['name'], digest, data)

    hash_count = len(requirements_hashes)
    assert hash_count == 2, f'2 requirements hashes expected, but {hash_count} hash(es) were found'
    assert all(wheel_info.get(key) for key in makefile_info), 'wheel info not found in release'

    content = PYPROJECT_PATH.read_text()
    updated = content.replace(PREFIX + current_version, PREFIX + version)
    PYPROJECT_PATH.write_text(updated)

    makefile = MAKEFILE_PATH.read_text()
    for key in wheel_info:
        makefile = makefile.replace(f'{key} = {makefile_info[key]}', f'{key} = {wheel_info[key]}')
    MAKEFILE_PATH.write_text(makefile)

    for req in REQUIREMENTS_PATH.glob('requirements-*.txt'):
        lines = req.read_text().splitlines(True)
        if requirements_needs_update(lines, PACKAGE_NAME, version):
            with req.open(mode='w') as f:
                f.writelines(requirements_update(lines, PACKAGE_NAME, version, requirements_hashes))


if __name__ == '__main__':
    main()
