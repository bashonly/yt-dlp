#!/bin/bash
set -exuo pipefail

python -m ensurepip --upgrade --default-pip

python -m venv /yt-dlp-build-venv
# shellcheck disable=SC1091
source /yt-dlp-build-venv/bin/activate

python -m pip install -U pip

python -m pip install -U ".[default,deno]"

yt-dlp -v || true

deno --version || true

python -c "import deno; print(deno.find_deno_bin())"

deno_exe=$(python -c "import deno; print(deno.find_deno_bin())")

chmod +x "${deno_exe}"

"${deno_exe}" --version
