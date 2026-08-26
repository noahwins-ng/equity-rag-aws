#!/usr/bin/env python3
"""QNT-269 AC1/AC3: sample-query smoke test against the deployed retrieval service Function
URL. SigV4-signs the POST with the caller's own AWS credentials -- the endpoint requires
AWS_IAM auth (terraform/retrieval_service.tf) -- the same signing pattern the QNT-270 eval
client will use to score the cloud endpoint.

Usage: uv run python scripts/invoke_retrieval.py <news|earnings> "<query text>"
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = "us-west-2"


def _function_url() -> str:
    return subprocess.check_output(
        ["terraform", "output", "-raw", "retrieval_service_url"], cwd="terraform", text=True
    ).strip()


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <news|earnings> <query>", file=sys.stderr)
        return 1
    corpus, query = sys.argv[1], sys.argv[2]

    url = _function_url()
    body = json.dumps({"corpus": corpus, "query": query}).encode()

    request = AWSRequest(
        method="POST", url=url, data=body, headers={"Content-Type": "application/json"}
    )
    SigV4Auth(boto3.Session().get_credentials(), "lambda", REGION).add_auth(request)

    req = urllib.request.Request(url, data=body, headers=dict(request.headers), method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(json.dumps(json.load(resp), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
