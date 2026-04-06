#!/usr/bin/env python3
from __future__ import annotations

# Allow direct execution
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collections.abc
import dataclasses
import pathlib
import re

from devscripts.tomlparse import parse_toml
from devscripts.utils import call_github_api, run_process


BASE_PATH = pathlib.Path(__file__).parent.parent
PYPROJECT_PATH = BASE_PATH / 'pyproject.toml'
LOCKFILE_PATH = BASE_PATH / 'uv.lock'
REQUIREMENTS_PATH = BASE_PATH / 'bundle/requirements'
OUTPUT_TMPL = 'requirements-{}.txt'
CUSTOM_COMPILE_COMMAND = 'python -m devscripts.update_requirements'

EXTRAS_TABLE = 'project.optional-dependencies'
GROUPS_TABLE = 'dependency-groups'
UV_TABLE = 'tool.uv'

PINNED_EXTRAS = {
    'pin': 'default',
    'pin-curl-cffi': 'curl-cffi',
    'pin-secretstorage': 'secretstorage',
    'pin-deno': 'deno',
}


@dataclasses.dataclass
class Target:
    extras: list[str] = dataclasses.field(default_factory=list)
    groups: list[str] = dataclasses.field(default_factory=list)
    prune_packages: list[str] = dataclasses.field(default_factory=list)
    omit_packages: list[str] = dataclasses.field(default_factory=list)


LINUX_TARGET = Target(
    extras=['default', 'curl-cffi', 'secretstorage'],
    groups=['pyinstaller'],
)
WIN64_TARGET = Target(
    extras=['default', 'curl-cffi'],
)

BUNDLE_TARGETS = {
    'linux-x86_64': LINUX_TARGET,
    'linux-aarch64': LINUX_TARGET,
    'linux-armv7l': LINUX_TARGET,
    'musllinux-x86_64': LINUX_TARGET,
    'musllinux-aarch64': LINUX_TARGET,
    'win-x64': WIN64_TARGET,
    'win-arm64': WIN64_TARGET,
    'win-x86': Target(extras=['default']),
    'macos': Target(
        extras=['default', 'curl-cffi'],
        # NB: Resolve delocate and PyInstaller together since they share dependencies
        groups=['delocate', 'pyinstaller'],
        # curl-cffi and cffi don't provide universal2 wheels, so only directly install their deps
        omit_packages=['curl-cffi', 'cffi'],
    ),
    # We fuse our own universal2 wheels for curl-cffi+cffi, so we need a separate requirements file
    'macos-curl_cffi': Target(
        extras=['curl-cffi'],
        # Only need curl-cffi+cffi in this requirements file; their deps are installed directly
        # XXX: Try to keep these in sync with curl-cffi's and cffi's transitive dependencies
        prune_packages=['rich'],
        omit_packages=['certifi', 'pycparser'],
    ),
}

PYINSTALLER_BUILDS_TARGETS = {
    'win-x64-pyinstaller': 'win_amd64',
    'win-x86-pyinstaller': 'win32',
    'win-arm64-pyinstaller': 'win_arm64',
}

PYINSTALLER_BUILDS_URL = 'https://api.github.com/repos/yt-dlp/Pyinstaller-Builds/releases/latest'

PYINSTALLER_BUILDS_TMPL = '''\
{}pyinstaller @ {} \\
    --hash={}
'''

PYINSTALLER_VERSION_RE = re.compile(r'pyinstaller-(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-')


def generate_table_lines(
    table_name: str,
    table: dict[str, str | list[str | dict[str, str]]],
) -> collections.abc.Iterator[str]:
    yield f'[{table_name}]\n'
    for name, value in table.items():
        assert isinstance(value, (str, list)), 'only string & array table values are supported'

        if isinstance(value, str):
            yield f'{name} = "{value}"\n'
            continue

        yield f'{name} = ['
        if value:
            yield '\n'
        for element in value:
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
    table: dict[str, str | list[str | dict[str, str]]],
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
    table: dict[str, str | list[str | dict[str, str]]],
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


def run_uv_export(
    *,
    extras: list[str] | None = None,
    groups: list[str] | None = None,
    prune_packages: list[str] | None = None,
    omit_packages: list[str] | None = None,
    bare: bool = False,
    output_file: pathlib.Path | None = None,
) -> str:
    return run_process(
        'uv', 'export',
        '--no-python-downloads',
        '--quiet',
        '--no-progress',
        '--color=never',
        '--format=requirements.txt',
        '--frozen',
        '--refresh',
        '--no-emit-project',
        '--no-default-groups',
        *(f'--extra={extra}' for extra in (extras or [])),
        *(f'--group={group}' for group in (groups or [])),
        *(f'--prune={package}' for package in (prune_packages or [])),
        *(f'--no-emit-package={package}' for package in (omit_packages or [])),
        *(['--no-annotate', '--no-hashes', '--no-header'] if bare else []),
        *([f'--output-file={output_file.relative_to(BASE_PATH)}'] if output_file else []),
    ).stdout


def run_pip_compile(
    *args: str,
    input_line: str,
    output_file: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    return run_process(
        'uv', 'pip', 'compile',
        '--no-python-downloads',
        '--quiet',
        '--no-progress',
        '--color=never',
        '--format=requirements.txt',
        '--refresh',
        '--generate-hashes',
        '--no-strip-markers',
        f'--custom-compile-command={CUSTOM_COMPILE_COMMAND}',
        '--universal',
        *args,
        *([f'--output-file={output_file.relative_to(BASE_PATH)}'] if output_file else []),
        '-',  # Read from stdin
        input=f'{input_line}\n',
        env=env,
    ).stdout


def update_requirements(upgrade_only: str | None = None, verify: bool = False):
    # Are we upgrading all packages or only one (e.g. 'yt-dlp-ejs' or 'protobug')?
    upgrade_arg = f'--upgrade-package={upgrade_only}' if upgrade_only else '--upgrade'

    pyproject_text = PYPROJECT_PATH.read_text()
    pyproject_toml = parse_toml(pyproject_text)
    extras = pyproject_toml['project']['optional-dependencies']

    # Remove pinned extras so they don't muck up the lockfile during generation/upgrade
    for pinned_extra_name in PINNED_EXTRAS:
        extras.pop(pinned_extra_name, None)

    # Write an intermediate pyproject.toml to use for generating lockfile and bundle requirements
    modify_and_write_pyproject(pyproject_text, table_name=EXTRAS_TABLE, table=extras)

    # If verifying, set UV_EXCLUDE_NEWER env var with the last timestamp recorded in uv.lock
    env = {}
    if verify:
        env['UV_EXCLUDE_NEWER'] = parse_toml(LOCKFILE_PATH.read_text())['options']['exclude-newer']

    # Generate/upgrade lockfile
    run_process('uv', 'lock', upgrade_arg, env=env)
    lockfile = parse_toml(LOCKFILE_PATH.read_text())

    # Generate bundle requirements
    if not upgrade_only or upgrade_only.lower() == 'pyinstaller':
        info = call_github_api(PYINSTALLER_BUILDS_URL)
        for target_suffix, asset_tag in PYINSTALLER_BUILDS_TARGETS.items():
            asset_info = next(asset for asset in info['assets'] if asset_tag in asset['name'])
            pyinstaller_version = PYINSTALLER_VERSION_RE.match(asset_info['name']).group('version')
            pyinstaller_builds_deps = run_pip_compile(
                '--no-emit-package=pyinstaller',
                upgrade_arg,
                input_line=f'pyinstaller=={pyinstaller_version}',
                env=env)
            requirements_path = REQUIREMENTS_PATH / OUTPUT_TMPL.format(target_suffix)
            requirements_path.write_text(PYINSTALLER_BUILDS_TMPL.format(
                pyinstaller_builds_deps, asset_info['browser_download_url'], asset_info['digest']))

    for target_suffix, target in BUNDLE_TARGETS.items():
        run_uv_export(
            extras=target.extras,
            groups=target.groups,
            prune_packages=target.prune_packages,
            omit_packages=target.omit_packages,
            output_file=REQUIREMENTS_PATH / OUTPUT_TMPL.format(target_suffix))

    run_uv_export(
        groups=['build'],
        output_file=REQUIREMENTS_PATH / OUTPUT_TMPL.format('pypi-build'))

    run_pip_compile(
        upgrade_arg,
        input_line='pip',
        output_file=REQUIREMENTS_PATH / OUTPUT_TMPL.format('pip'),
        env=env)

    # Generate pinned extras
    for pinned_name, extra_name in PINNED_EXTRAS.items():
        pinned_extra = extras[pinned_name] = []
        exported_extra = run_uv_export(extras=[extra_name], bare=True)
        for line in exported_extra.splitlines():
            dep = parse_dependency(line)
            wheels = next((
                pkg.get('wheels') for pkg in lockfile['package']
                if pkg['name'] == dep.name and pkg['version'] == dep.version), None)
            assert wheels, f'no wheels found for {dep.name} in lockfile'
            # If multiple wheels are found, we'll *assume* it's because they're platform-specific.
            # Platform tags can't be used in markers, so the best we can do is pin to exact version
            if len(wheels) > 1:
                pinned_extra.append(line)
                continue
            # If there's only a 'none-any' wheel, then use a direct reference to PyPI URL with hash
            wheel_url = wheels[0]['url']
            algo, _, digest = wheels[0]['hash'].partition(':')
            pinned_line = f'{dep.name} @ {wheel_url}#{algo}={digest}'
            pinned_extra.append(' ; '.join(filter(None, (pinned_line, dep.markers))))

    # Write the finalized pyproject.toml
    modify_and_write_pyproject(pyproject_text, table_name=EXTRAS_TABLE, table=extras)


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description='generate/update lockfile and requirements')
    parser.add_argument(
        'upgrade_only', nargs='?', metavar='PACKAGE',
        help='only upgrade this package. (by default, all packages will be upgraded)')
    parser.add_argument(
        '--verify', action='store_true',
        help='only verify the update(s) using the previously recorded cooldown timestamp')
    return parser.parse_args()


def main():
    args = parse_args()
    update_requirements(upgrade_only=args.upgrade_only, verify=args.verify)


if __name__ == '__main__':
    main()
