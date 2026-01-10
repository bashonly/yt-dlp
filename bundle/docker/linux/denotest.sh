#!/bin/bash
set -exuo pipefail

pipx ensurepath
pipx install --verbose ".[default,deno]"

yt-dlp -v || true

pipx run deno --version
