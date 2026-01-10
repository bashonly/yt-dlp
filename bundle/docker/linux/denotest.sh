#!/bin/bash
set -exuo pipefail

function runpy {
    /opt/python/cp313-cp313/bin/python "$@"
}

function venvpy {
    python3.13 "$@"
}

runpy -m venv /yt-dlp-build-venv
# shellcheck disable=SC1091
source /yt-dlp-build-venv/bin/activate

venvpy -m ensurepip --upgrade --default-pip
venvpy -m pip install -U pip

venvpy -m pip install -U ".[default]"
venvpy -m pip install "deno @ https://github.com/bashonly/deno_pypi/releases/download/v2.6.4/deno-2.6.4.tar.gz"

yt-dlp -v || true

deno --version || true

venvpy -c "import deno; print(deno.find_deno_bin())"

deno_exe=$(venvpy -c "import deno; print(deno.find_deno_bin())")

"${deno_exe}" --version
