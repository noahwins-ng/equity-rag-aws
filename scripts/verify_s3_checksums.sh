#!/usr/bin/env bash
# QNT-267 AC3: verify every seeded S3 object's checksum against data/manifest.json.
# Run after `terraform apply` (terraform/s3.tf). Requires: aws cli, jq.
set -euo pipefail

cd "$(dirname "$0")/.."

bucket=$(cd terraform && terraform output -raw corpus_bucket)
manifest="data/manifest.json"
fail=0

check_object() {
  local key="$1" expected_hex="$2"
  local expected_b64
  expected_b64=$(python3 -c "import base64,sys; print(base64.b64encode(bytes.fromhex(sys.argv[1])).decode())" "$expected_hex")

  local actual_b64
  actual_b64=$(aws s3api head-object --bucket "$bucket" --key "$key" --checksum-mode ENABLED \
    --query 'ChecksumSHA256' --output text)

  if [[ "$actual_b64" == "$expected_b64" ]]; then
    echo "OK    $key"
  else
    echo "FAIL  $key  expected=$expected_b64 actual=$actual_b64"
    fail=1
  fi
}

for key in $(jq -r '.files | keys[]' "$manifest"); do
  expected=$(jq -r --arg k "$key" '.files[$k].sha256' "$manifest")
  check_object "$key" "$expected"
done

# manifest.json itself is seeded too but isn't self-describing its own checksum;
# just confirm it round-trips.
manifest_local_sha=$(shasum -a 256 "$manifest" | awk '{print $1}')
manifest_b64=$(python3 -c "import base64,sys; print(base64.b64encode(bytes.fromhex(sys.argv[1])).decode())" "$manifest_local_sha")
manifest_actual=$(aws s3api head-object --bucket "$bucket" --key manifest.json --checksum-mode ENABLED \
  --query 'ChecksumSHA256' --output text)
if [[ "$manifest_actual" == "$manifest_b64" ]]; then
  echo "OK    manifest.json"
else
  echo "FAIL  manifest.json  expected=$manifest_b64 actual=$manifest_actual"
  fail=1
fi

exit "$fail"
