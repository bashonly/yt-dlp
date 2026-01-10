#!/bin/bash
set -exuo pipefail

pipx install ".[default,deno]"

yt-dlp -v || true

exit 0

# OLD:


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

venvpy -m pip install -U ".[default,deno]"

yt-dlp -v || true

deno --version || true

venvpy -c "import deno; print(deno.find_deno_bin())"

deno_exe=$(venvpy -c "import deno; print(deno.find_deno_bin())")

"${deno_exe}" --version
