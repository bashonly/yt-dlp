ARG BUILDIMAGE=ghcr.io/yt-dlp/manylinux2014_x86_64-shared:latest
ARG VERIFYIMAGE=alpine:3.22
ARG DENOIMAGE=quay.io/pypa/manylinux2014_x86_64:2025.12.19-1@sha256:b716645f9aecd0c1418283af930804bbdbd68a73d855a60101c5aab8548d737d

FROM $BUILDIMAGE AS build

WORKDIR /yt-dlp
COPY build.sh /build.sh
ENTRYPOINT ["/build.sh"]


FROM $VERIFYIMAGE AS verify

WORKDIR /testing
COPY verify.sh /verify.sh
ENTRYPOINT ["/verify.sh"]


FROM $DENOIMAGE AS deno

WORKDIR /yt-dlp
COPY denotest.sh /denotest.sh
ENTRYPOINT ["/denotest.sh"]
