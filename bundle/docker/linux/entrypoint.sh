#!/bin/bash
set -e

python -m venv ~/yt-dlp-build-venv
source ~/yt-dlp-build-venv/bin/activate
python -m devscripts.install_deps -o --include build
python -m devscripts.install_deps --include secretstorage --include curl-cffi --include pyinstaller
python -m devscripts.make_lazy_extractors
python devscripts/update-version.py -c "${channel}" -r "${origin}" "${version}"
python -m bundle.pyinstaller
