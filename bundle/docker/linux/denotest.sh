#!/bin/bash
set -exuo pipefail

/opt/python/cp313-cp313/bin/python -m pipx ensurepath
pipx install --verbose ".[default,deno]"

yt-dlp -v || true
deno --version || true
