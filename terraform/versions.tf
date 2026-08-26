terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # >= 6.25 for S3 Vectors resources (aws_s3vectors_vector_bucket, aws_s3vectors_index),
      # first available at 6.25.0 -- bumped from ~> 5.0 for QNT-268.
      version = "~> 6.25"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Solo, ephemeral, single-apply/destroy-cycle project — no CI, no team, no
  # remote-state bootstrap to remember to tear down. State file is gitignored.
  backend "local" {}
}
