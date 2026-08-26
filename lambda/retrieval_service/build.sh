#!/usr/bin/env bash
# Builds the retrieval-service Lambda deployment package: vendors requirements.txt alongside
# handler.py into build/, which terraform/retrieval_service.tf then zips. Targets
# aarch64-manylinux2014/py3.13 explicitly (matches the Lambda's arm64 runtime) since
# openai's pydantic-core dependency ships a compiled native extension -- a wheel built
# on the local machine's platform (e.g. macOS ARM64) won't load on Lambda's Linux ARM64.
# Re-run by terraform on any handler.py/requirements.txt change via the null_resource
# trigger. Mirrors lambda/index_job/build.sh (QNT-268).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

rm -rf build
mkdir -p build

uv pip install --target build \
  --python-platform aarch64-manylinux2014 --python-version 3.13 \
  -r requirements.txt

cp handler.py build/
