variable "aws_region" {
  description = "AWS region — pinned for S3 Vectors availability. Model serving moved to OpenRouter (ADR-0001), so this is no longer driven by Bedrock co-location."
  type        = string
  default     = "us-west-2"
}

variable "budget_alert_email" {
  description = "Email address subscribed to the AWS Budgets warning (USD 10) and hard-cap (USD 20) alerts."
  type        = string
}

variable "iam_user_name" {
  description = "IAM user the budget hard-stop deny policy is auto-attached to when spend hits USD 20."
  type        = string
}

variable "openrouter_api_key" {
  description = "OpenRouter API key for the index-job Lambda (embeddings). Set a spend limit on the OpenRouter dashboard before real usage -- the AWS Budgets guard does not cover this spend (ADR-0001)."
  type        = string
  sensitive   = true
}
