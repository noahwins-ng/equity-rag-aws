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

data "aws_caller_identity" "current" {}

# Auto-attached to `var.iam_user_name` when spend hits USD 20 (100% of the cap above).
# Denies only this project's billed actions -- deliberately does NOT deny
# delete/terminate/budgets:* actions, so `terraform destroy` still works after this fires.
resource "aws_iam_policy" "budget_breach_deny" {
  name        = "equity-rag-aws-budget-breach-deny"
  description = "Auto-attached by AWS Budgets at USD 20 spend. Denies new spend; does not block teardown."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DenyProjectSpendActions"
        Effect = "Deny"
        Action = [
          "s3vectors:PutVectors",
          "s3vectors:QueryVectors",
          "lambda:InvokeFunction",
          "lambda:InvokeFunctionUrl", # retrieval service Function URL (QNT-269)
          "execute-api:Invoke",       # unused now QNT-269 chose a Function URL over API
          # Gateway -- kept harmlessly, same as the dropped Bedrock actions before it
        ]
        Resource = "*"
      }
    ]
  })
}

# Role AWS Budgets assumes to attach the deny policy on breach. Trust is scoped to this
# account's budgets (confused-deputy protection, per AWS's documented pattern).
resource "aws_iam_role" "budget_action" {
  name = "equity-rag-aws-budget-action-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "budgets.amazonaws.com" }
        Action    = "sts:AssumeRole"
        Condition = {
          ArnLike = {
            "aws:SourceArn" = "arn:aws:budgets::${data.aws_caller_identity.current.account_id}:budget/*"
          }
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# Scoped to attach/detach only the one deny policy on the one target user -- not broad
# IAM management. iam:Attach/DetachUserPolicy require both the user and policy resource
# ARNs listed together (IAM authorizes against every resource type the action touches).
resource "aws_iam_role_policy" "budget_action_permissions" {
  name = "attach-detach-breach-deny-policy"
  role = aws_iam_role.budget_action.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["iam:AttachUserPolicy", "iam:DetachUserPolicy"]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/${var.iam_user_name}",
          aws_iam_policy.budget_breach_deny.arn,
        ]
      }
    ]
  })
}

resource "aws_budgets_budget_action" "hard_stop" {
  budget_name        = aws_budgets_budget.project_cap.name
  action_type        = "APPLY_IAM_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_action.arn

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = 100
  }

  definition {
    iam_action_definition {
      policy_arn = aws_iam_policy.budget_breach_deny.arn
      users      = [var.iam_user_name]
    }
  }

  subscriber {
    subscription_type = "EMAIL"
    address           = var.budget_alert_email
  }
}
