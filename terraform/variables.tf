variable "aws_region" {
  description = "AWS region — pinned to co-locate Bedrock (Titan/Cohere Rerank/gpt-oss-20b) and S3 Vectors."
  type        = string
  default     = "us-west-2"
}

variable "budget_alert_email" {
  description = "Email address subscribed to the AWS Budgets warning (USD 10) and hard-cap (USD 20) alerts."
  type        = string
}
