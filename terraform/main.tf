provider "aws" {
  region = var.aws_region
}

# Backstop to `terraform destroy` (the primary teardown safety mechanism) — see
# docs/PRD.md §8. One USD 20 monthly budget, warning at 50% (USD 10) and hard cap
# at 100% (USD 20).
resource "aws_budgets_budget" "project_cap" {
  name         = "equity-rag-aws-cap"
  budget_type  = "COST"
  limit_amount = "20"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
