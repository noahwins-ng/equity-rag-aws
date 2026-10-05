#!/usr/bin/env bash
# Builds the retrieval-service Lambda deployment package: vendors requirements.txt alongside
# handler.py into build/, which terraform/retrieval_service.tf then zips. Targets
# aarch64-manylinux_2_28/py3.13 explicitly (matches the Lambda's arm64 runtime) so any
# dependency with a compiled extension resolves to a Linux ARM64 wheel, not the local
# machine's platform (e.g. macOS ARM64). manylinux_2_28, not 2014 (QNT-312): numpy (via
# rank-bm25) ships no manylinux2014 aarch64 wheel for py3.13, and the python3.13 runtime
# runs on Amazon Linux 2023 (glibc 2.34), so 2_28 wheels are compatible.
# Re-run by terraform on any handler.py/requirements.txt change via the null_resource
# trigger. Mirrors lambda/index_job/build.sh (QNT-268).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

rm -rf build
mkdir -p build

uv pip install --target build \
  --python-platform aarch64-manylinux_2_28 --python-version 3.13 \
  -r requirements.txt

cp handler.py hybrid.py build/
