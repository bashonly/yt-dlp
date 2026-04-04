#!/usr/bin/env python3
from __future__ import annotations

# Allow direct execution
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collections.abc
import contextlib
import dataclasses
import itertools
import json
import pathlib
import re
import typing
import urllib.request

from devscripts.tomlparse import parse_toml
from devscripts.utils import run_process


BASE_PATH = pathlib.Path(__file__).parent.parent
PYPROJECT_PATH = BASE_PATH / 'pyproject.toml'
LOCKFILE_PATH = BASE_PATH / 'uv.lock'
REQUIREMENTS_PATH = BASE_PATH / 'bundle/requirements'
OUTPUT_TMPL = 'requirements-{}.txt'
CUSTOM_COMPILE_COMMAND = 'python -m devscripts.update_requirements'

LINUX_GNU_PYTHON_VERSION = '3.13'
LINUX_MUSL_PYTHON_VERISON = '3.14'
WINDOWS_INTEL_PYTHON_VERSION = '3.10'
WINDOWS_ARM64_PYTHON_VERSION = '3.13'
MACOS_PYTHON_VERSION = '3.14'

EXTRAS_TABLE = 'project.optional-dependencies'
GROUPS_TABLE = 'dependency-groups'

LOCK_EXTRAS = {
    'lock': 'default',
    'curl-cffi-lock': 'curl-cffi',
    'secretstorage-lock': 'secretstorage',
    'deno-lock': 'deno',
}


@dataclasses.dataclass
class Target:
    platform: str
    version: str
    extras: list[str] = dataclasses.field(default_factory=list)
    groups: list[str] = dataclasses.field(default_factory=list)
    compile_args: list[str] = dataclasses.field(default_factory=list)


INSTALL_DEPS_TARGETS = {
    'linux-x86_64': Target(
        platform='x86_64-manylinux2014',
        version=LINUX_GNU_PYTHON_VERSION,
        extras=['default', 'curl-cffi', 'secretstorage'],
        groups=['pyinstaller'],
    ),
    'linux-aarch64': Target(
        platform='aarch64-manylinux2014',
        version=LINUX_GNU_PYTHON_VERSION,
        extras=['default', 'curl-cffi', 'secretstorage'],
        groups=['pyinstaller'],
    ),
    'linux-armv7l': Target(
        platform='linux',
        version=LINUX_GNU_PYTHON_VERSION,
        extras=['default', 'curl-cffi', 'secretstorage'],
        groups=['pyinstaller'],
    ),
    'musllinux-x86_64': Target(
        platform='x86_64-unknown-linux-musl',
        version=LINUX_MUSL_PYTHON_VERISON,
        extras=['default', 'curl-cffi', 'secretstorage'],
        groups=['pyinstaller'],
    ),
    'musllinux-aarch64': Target(
        platform='aarch64-unknown-linux-musl',
        version=LINUX_MUSL_PYTHON_VERISON,
        extras=['default', 'curl-cffi', 'secretstorage'],
        groups=['pyinstaller'],
    ),
    'win-x64': Target(
        platform='x86_64-pc-windows-msvc',
        version=WINDOWS_INTEL_PYTHON_VERSION,
        extras=['default', 'curl-cffi'],
    ),
    'win-x86': Target(
        platform='i686-pc-windows-msvc',
        version=WINDOWS_INTEL_PYTHON_VERSION,
        extras=['default'],
    ),
    'win-arm64': Target(
        platform='aarch64-pc-windows-msvc',
        version=WINDOWS_ARM64_PYTHON_VERSION,
        extras=['default', 'curl-cffi'],
    ),
    'macos': Target(
        platform='macos',
        version=MACOS_PYTHON_VERSION,
        extras=['default', 'curl-cffi'],
        # NB: Resolve delocate and PyInstaller together since they share dependencies
        groups=['delocate', 'pyinstaller'],
        # curl-cffi and cffi don't provide universal2 wheels, so only directly install their deps
        # NB: uv's --no-emit-package option is equivalent to pip-compile's --unsafe-package option
        compile_args=['--no-emit-package', 'curl-cffi', '--no-emit-package', 'cffi'],
    ),
    # We fuse our own universal2 wheels for curl-cffi+cffi, so we need a separate requirements file
    'macos-curl_cffi': Target(
        platform='macos',
        version=MACOS_PYTHON_VERSION,
        extras=['curl-cffi'],
        # Only need curl-cffi+cffi in this requirements file; their deps are installed directly
        compile_args=[
            # XXX: Try to keep this in sync with curl-cffi's and cffi's transitive dependencies
            f'--no-emit-package={package}' for package in (
                'certifi',
                'markdown-it-py',
                'mdurl',
                'pycparser',
                'pygments',
                'rich',
            )
        ],
    ),
}


@dataclasses.dataclass
class PyInstallerTarget:
    platform: str
    version: str
    asset_tag: str


PYINSTALLER_BUILDS_TARGETS = {
    'win-x64-pyinstaller': PyInstallerTarget(
        platform='x86_64-pc-windows-msvc',
        version=WINDOWS_INTEL_PYTHON_VERSION,
        asset_tag='win_amd64',
    ),
    'win-x86-pyinstaller': PyInstallerTarget(
        platform='i686-pc-windows-msvc',
        version=WINDOWS_INTEL_PYTHON_VERSION,
        asset_tag='win32',
    ),
    'win-arm64-pyinstaller': PyInstallerTarget(
        platform='aarch64-pc-windows-msvc',
        version=WINDOWS_ARM64_PYTHON_VERSION,
        asset_tag='win_arm64',
    ),
}

PYINSTALLER_BUILDS_URL = 'https://api.github.com/repos/yt-dlp/Pyinstaller-Builds/releases/latest'

PYINSTALLER_BUILDS_TMPL = '''\
{}pyinstaller @ {} \\
    --hash={}
'''

PYINSTALLER_VERSION_RE = re.compile(r'pyinstaller-(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-')


def generate_table_lines(
    table_name: str,
    table: dict[str, list[str | dict[str, str]]],
) -> collections.abc.Iterator[str]:
    yield f'[{table_name}]\n'
    for name, array in table.items():
        yield f'{name} = ['
        if array:
            yield '\n'
        for element in array:
            yield '    '
            if isinstance(element, dict):
                yield '{ ' + ', '.join(f'{k} = "{v}"' for k, v in element.items()) + ' }'
            else:
                yield f'"{element}"'
            yield ',\n'
        yield ']\n'
    yield '\n'


def replace_table_in_pyproject(
    pyproject_text: str,
    table_name: str,
    table: dict[str, list[str | dict[str, str]]],
) -> collections.abc.Iterator[str]:
    INSIDE = 1
    BEYOND = 2

    state = 0
    for line in pyproject_text.splitlines(True):
        if state == INSIDE:
            if line == '\n':
                state = BEYOND
            continue
        if line != f'[{table_name}]\n' or state == BEYOND:
            yield line
            continue
        yield from generate_table_lines(table_name, table)
        state = INSIDE


def modify_and_write_pyproject(
    pyproject_text: str,
    table_name: str,
    table: dict[str, list[str | dict[str, str]]],
) -> None:
    with PYPROJECT_PATH.open(mode='w') as f:
        f.writelines(replace_table_in_pyproject(pyproject_text, table_name, table))


@dataclasses.dataclass
class Dependency:
    name: str
    direct_reference: str | None
    version: str | None
    markers: str | None


def parse_dependency(line: str, comp_op: str = '==') -> Dependency:
    line = line.rstrip().removesuffix('\\')
    before, sep, after = map(str.strip, line.partition('@'))
    name, _, version_and_markers = map(str.strip, before.partition(comp_op))
    assertion_msg = f'unable to parse Dependency from line:\n    {line}'
    assert name, assertion_msg

    if sep:
        # Direct reference
        version = version_and_markers
        direct_reference, _, markers = map(str.strip, after.partition(';'))
        assert direct_reference, assertion_msg
    else:
        # No direct reference
        direct_reference = None
        version, _, markers = map(str.strip, version_and_markers.partition(';'))

    return Dependency(
        name=name,
        direct_reference=direct_reference,
        version=version or None,
        markers=markers or None)


def verify_against_lockfile(
    requirements_path: pathlib.Path,
    lockfile: dict[str, typing.Any],
) -> None:
    with requirements_path.open() as f:
        for line in f:
            if line.lstrip().startswith(('--hash=', '#')) or not line.strip():
                continue
            dep = parse_dependency(line)
            # Ignore packages pinned to URL
            if dep.direct_reference:
                continue
            # We don't keep pip in any extras/groups
            if dep.name == 'pip':
                continue
            lock_package = next(pkg for pkg in lockfile['package'] if pkg['name'] == dep.name)
            lv = lock_package['version']
            assert dep.version == lv, f'version mismatch for {dep.name}: {dep.version} != {lv}'


def run_pip_compile(
    *args: str,
    extras: list[str] | None = None,
    groups: list[str] | None = None,
    single: str | None = None,
    platform: str | None = None,
    version: str | None = None,
    bare: bool = False,
    output_file: str | None = None,
) -> str:
    assert any((single, extras, groups)), 'one of "extras", "groups", or "single" must be passed'
    assert not single or not (extras or groups), 'only "extras"/"groups" OR "single" can be passed'

    if single:
        requirements_input = f'{single}\n'
    else:
        requirements_input = run_process(
            sys.executable, '-m', 'devscripts.install_deps',
            '--omit-default',
            '--print',
            *itertools.chain.from_iterable(itertools.product(['--include-extra'], extras or [])),
            *itertools.chain.from_iterable(itertools.product(['--include-group'], groups or [])),
        ).stdout

    if bare:
        # Lock extra
        pip_compile_args = [
            *args,
            '--no-annotate',
            '--no-header',
        ]
    else:
        # Bundle requirements
        pip_compile_args = [
            *args,
            '--generate-hashes',
            '--no-strip-markers',
            f'--custom-compile-command={CUSTOM_COMPILE_COMMAND}',
        ]

    if platform:
        pip_compile_args.append(f'--python-platform={platform}')
    if version:
        pip_compile_args.append(f'--python-version={version}')
    if not (platform or version):
        # Assume universal resolution
        pip_compile_args.append('--universal')

    if output_file:
        pip_compile_args.append(f'--output-file={output_file}')

    return run_process(
        'uv', 'pip', 'compile',
        '--no-python-downloads',
        '--quiet',
        '--no-progress',
        '--color=never',
        '--format=requirements.txt',
        *pip_compile_args,
        '-',  # Read from stdin
        input=requirements_input,
    ).stdout


def update_requirements(upgrade_only: str | None = None):
    # Are we upgrading all packages or only one (e.g. 'yt-dlp-ejs' or 'protobug')?
    upgrade_arg = ''.join(('--upgrade', f'-package={upgrade_only}' if upgrade_only else ''))

    pyproject_text = PYPROJECT_PATH.read_text()
    pyproject_toml = parse_toml(pyproject_text)
    extras = pyproject_toml['project']['optional-dependencies']

    # Remove locked extras so they don't muck up the lockfile during generation/upgrade
    for lock_name in LOCK_EXTRAS:
        extras.pop(lock_name, None)

    # Write an intermediate pyproject.toml to use for generating lockfile and bundle requirements
    modify_and_write_pyproject(pyproject_text, table_name=EXTRAS_TABLE, table=extras)

    # Generate/upgrade lockfile
    run_process('uv', 'lock', upgrade_arg)
    lockfile = parse_toml(LOCKFILE_PATH.read_text())

    # Begin bundle requirements generation
    with contextlib.closing(urllib.request.urlopen(PYINSTALLER_BUILDS_URL)) as resp:
        info = json.load(resp)

    for target_suffix, target in PYINSTALLER_BUILDS_TARGETS.items():
        asset_info = next(asset for asset in info['assets'] if target.asset_tag in asset['name'])
        pyinstaller_version = PYINSTALLER_VERSION_RE.match(asset_info['name']).group('version')
        pyinstaller_builds_deps = run_pip_compile(
            '--no-emit-package=pyinstaller',
            upgrade_arg,
            single=f'pyinstaller=={pyinstaller_version}',
            platform=target.platform,
            version=target.version)
        requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format(target_suffix)
        requirements_path.write_text(PYINSTALLER_BUILDS_TMPL.format(
            pyinstaller_builds_deps, asset_info['browser_download_url'], asset_info['digest']))
        verify_against_lockfile(requirements_path, lockfile)

    for target_suffix, target in INSTALL_DEPS_TARGETS.items():
        requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format(target_suffix)
        run_pip_compile(
            *target.compile_args,
            upgrade_arg,
            extras=target.extras,
            groups=target.groups,
            platform=target.platform,
            version=target.version,
            output_file=requirements_path)
        verify_against_lockfile(requirements_path, lockfile)

    requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format('pypi-build')
    run_pip_compile(
        upgrade_arg,
        groups=['build'],
        output_file=requirements_path)
    verify_against_lockfile(requirements_path, lockfile)

    requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format('pip')
    run_pip_compile(
        upgrade_arg,
        single='pip',
        output_file=requirements_path)
    verify_against_lockfile(requirements_path, lockfile)
    # End bundle requirements generation

    # Generate locked extras
    for lock_name, extra_name in LOCK_EXTRAS.items():
        lock_extra = extras[lock_name] = []
        compiled_extra = run_pip_compile(upgrade_arg, extras=[extra_name], bare=True)
        for line in compiled_extra.splitlines():
            dep = parse_dependency(line)
            lock_package = next(pkg for pkg in lockfile['package'] if pkg['name'] == dep.name)
            lv = lock_package['version']
            assert lv == dep.version, f'version mismatch for {dep.name}: {lv} != {dep.version}'
            wheels = lock_package['wheels']
            assert wheels, f'lockfile wheels list is empty for {dep.name} in "{lock_name}"'
            # If there are platform-specific wheels, then the best we can do is pin to exact version
            if len(wheels) > 1:
                lock_extra.append(line)
                continue
            # If there's a single 'none-any' wheel then we pin to the PyPI URL and add the hash
            wheel_url = wheels[0]['url']
            algo, _, digest = wheels[0]['hash'].partition(':')
            lock_line = f'{dep.name} @ {wheel_url}#{algo}={digest}'
            lock_extra.append(' ; '.join(filter(None, (lock_line, dep.markers))))

    # Write the finalized pyproject.toml
    modify_and_write_pyproject(pyproject_text, table_name=EXTRAS_TABLE, table=extras)


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description='Generate/update lockfile and requirements')
    parser.add_argument(
        'upgrade_only', nargs='?', metavar='PACKAGE',
        help='only upgrade this package. (by default, all packages will be upgraded)')
    return parser.parse_args()


def main():
    args = parse_args()
    update_requirements(upgrade_only=args.upgrade_only)


if __name__ == '__main__':
    main()
