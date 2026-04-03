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
import subprocess
import typing
import urllib.request

from devscripts.tomlparse import parse_toml
from devscripts.utils import run_process


BASE_PATH = pathlib.Path(__file__).parent.parent
PYPROJECT_PATH = BASE_PATH / 'pyproject.toml'
LOCKFILE_PATH = BASE_PATH / 'uv.lock'
TEMP_DIR_PATH = BASE_PATH / 'build'
TEMP_INPUT_PATH = TEMP_DIR_PATH / 'requirements.in'
REQUIREMENTS_PATH = BASE_PATH / 'bundle/requirements'
INPUT_TMPL = 'requirements-{}.in'
OUTPUT_TMPL = 'requirements-{}.txt'
CUSTOM_COMPILE_COMMAND = 'python -m devscripts.update_bundle_requirements'

LINUX_GNU_PYTHON_VERSION = '3.13'
LINUX_MUSL_PYTHON_VERISON = '3.14'
WINDOWS_INTEL_PYTHON_VERSION = '3.10'
WINDOWS_ARM64_PYTHON_VERSION = '3.13'
MACOS_PYTHON_VERSION = '3.14'

EXTRAS_TABLE = 'project.optional-dependencies'
GROUPS_TABLE = 'dependency-groups'

HIDDEN_EXTRAS = ('curl-cffi-compat',)

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
        extras=['default', 'curl-cffi-compat', 'secretstorage'],
        groups=['pyinstaller'],
    ),
    'linux-aarch64': Target(
        platform='aarch64-manylinux2014',
        version=LINUX_GNU_PYTHON_VERSION,
        extras=['default', 'curl-cffi-compat', 'secretstorage'],
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
        extras=['default', 'secretstorage'],
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
        extras=['default', 'curl-cffi-compat'],
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
        extras=['curl-cffi-compat'],
        # Only need curl-cffi+cffi in this requirements file; their deps are installed directly
        compile_args=['--no-emit-package', 'certifi', '--no-emit-package', 'pycparser'],
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
    hidden_extras: dict[str, list[tuple[str, str, str]]] | None = None,
) -> None:
    # Hidden extras have older version pins for compatibility; make exceptions for these
    exceptions = [
        parse_dependency(dep).name for dep in itertools.chain.from_iterable(hidden_extras.values())
    ] if hidden_extras else []
    # We don't keep pip in any extras/groups
    exceptions.append('pip')

    with requirements_path.open() as f:
        for line in f:
            if line.lstrip().startswith(('--hash=', '#')) or not line.strip():
                continue
            dep = parse_dependency(line)
            # Ignore packages pinned to URL
            if dep.direct_reference:
                continue
            if dep.name in exceptions:
                continue
            lock_package = next(pkg for pkg in lockfile['package'] if pkg['name'] == dep.name)
            lv = lock_package['version']
            assert dep.version == lv, f'version mismatch for {dep.name}: {dep.version} != {lv}'


def write_requirements_input(filepath: pathlib.Path, *args: str) -> None:
    filepath.write_text(run_process(
        sys.executable, '-m', 'devscripts.install_deps',
        '--omit-default', '--print', *args).stdout)


def run_pip_compile(
    python_platform: str,
    python_version: str,
    requirements_input_path: pathlib.Path,
    *args: str,
) -> subprocess.CompletedProcess:
    return run_process(
        'uv', 'pip', 'compile',
        '--no-python-downloads',
        '--quiet',
        '--no-progress',
        '--color=never',
        f'--python-platform={python_platform}',
        f'--python-version={python_version}',
        '--generate-hashes',
        '--no-strip-markers',
        f'--custom-compile-command={CUSTOM_COMPILE_COMMAND}',
        '--format=requirements.txt',
        *args, str(requirements_input_path))


def run_pip_compile_universal(
    requirements_input_path: pathlib.Path,
    *args: str,
) -> subprocess.CompletedProcess:
    return run_process(
        'uv', 'pip', 'compile',
        '--no-python-downloads',
        '--quiet',
        '--no-progress',
        '--color=never',
        '--universal',
        '--no-annotate',
        '--no-header',
        '--format=requirements.txt',
        *args, str(requirements_input_path))


def update_requirements(upgrade_only: str | None = None):
    # Are we upgrading all packages or only one (e.g. 'yt-dlp-ejs' or 'protobug')?
    upgrade_arg = '--upgrade' + (f'-package={upgrade_only}' if upgrade_only else '')

    pyproject_text = PYPROJECT_PATH.read_text()
    pyproject_toml = parse_toml(pyproject_text)

    extras = pyproject_toml['project']['optional-dependencies']
    hidden_extras = {}

    # Remove hidden and locked extras so they don't muck up the lockfile during generation/upgrade
    for hidden_extra in HIDDEN_EXTRAS:
        # We will restore these later and need to use them as exceptions to lockfile verification
        hidden_extras[hidden_extra] = extras.pop(hidden_extra)
    for lock_name in LOCK_EXTRAS:
        extras.pop(lock_name, None)

    # Write a pyproject.toml that will only be used to generate/upgrade the lockfile
    modify_and_write_pyproject(pyproject_text, table_name=EXTRAS_TABLE, table=extras)

    # Generate/upgrade lockfile
    run_process('uv', 'lock', upgrade_arg)
    lockfile = parse_toml(LOCKFILE_PATH.read_text())

    # Write a pyproject.toml with hidden extras restored for bundle requirements generation/updating
    extras.update(hidden_extras)
    modify_and_write_pyproject(pyproject_text, table_name=EXTRAS_TABLE, table=extras)

    # Begin bundle requirements generation
    with contextlib.closing(urllib.request.urlopen(PYINSTALLER_BUILDS_URL)) as resp:
        info = json.load(resp)

    for target_suffix, target in PYINSTALLER_BUILDS_TARGETS.items():
        asset_info = next(asset for asset in info['assets'] if target.asset_tag in asset['name'])
        pyinstaller_version = PYINSTALLER_VERSION_RE.match(asset_info['name']).group('version')
        base_requirements_path = REQUIREMENTS_PATH / INPUT_TMPL.format(target_suffix)
        base_requirements_path.write_text(f'pyinstaller=={pyinstaller_version}\n')
        pyinstaller_builds_deps = run_pip_compile(
            target.platform, target.version, base_requirements_path,
            '--no-emit-package=pyinstaller', upgrade_arg).stdout
        requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format(target_suffix)
        requirements_path.write_text(PYINSTALLER_BUILDS_TMPL.format(
            pyinstaller_builds_deps, asset_info['browser_download_url'], asset_info['digest']))
        verify_against_lockfile(requirements_path, lockfile)

    for target_suffix, target in INSTALL_DEPS_TARGETS.items():
        requirements_input_path = REQUIREMENTS_PATH / INPUT_TMPL.format(target_suffix)
        write_requirements_input(
            requirements_input_path,
            *itertools.chain.from_iterable(itertools.product(['--include-extra'], target.extras)),
            *itertools.chain.from_iterable(itertools.product(['--include-group'], target.groups)))
        requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format(target_suffix)
        run_pip_compile(
            target.platform, target.version, requirements_input_path,
            upgrade_arg, *target.compile_args, f'--output-file={requirements_path}')
        verify_against_lockfile(requirements_path, lockfile, hidden_extras)

    pypi_input_path = REQUIREMENTS_PATH / INPUT_TMPL.format('pypi-build')
    write_requirements_input(pypi_input_path, '--include-group', 'build')
    requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format('pypi-build')
    run_pip_compile(
        'linux', LINUX_GNU_PYTHON_VERSION, pypi_input_path,
        upgrade_arg, f'--output-file={requirements_path}')
    verify_against_lockfile(requirements_path, lockfile)

    pip_input_path = REQUIREMENTS_PATH / INPUT_TMPL.format('pip')
    pip_input_path.write_text('pip\n')
    requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format('pip')
    run_pip_compile(
        'windows', WINDOWS_INTEL_PYTHON_VERSION, pip_input_path,
        upgrade_arg, f'--output-file={requirements_path}')
    verify_against_lockfile(requirements_path, lockfile)
    # End bundle requirements generation

    # Generate locked extras
    TEMP_DIR_PATH.mkdir(exist_ok=True)
    for lock_name, extra_name in LOCK_EXTRAS.items():
        lock_extra = extras[lock_name] = []
        write_requirements_input(TEMP_INPUT_PATH, '--include-extra', extra_name)
        compiled_extra = run_pip_compile_universal(TEMP_INPUT_PATH, upgrade_arg).stdout
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


def main():
    upgrade_only = None
    if len(sys.argv) > 1:
        upgrade_only = sys.argv[1]
    update_requirements(upgrade_only=upgrade_only)


if __name__ == '__main__':
    main()
