terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Solo, ephemeral, single-apply/destroy-cycle project — no CI, no team, no
  # remote-state bootstrap to remember to tear down. State file is gitignored.
  backend "local" {}
}
