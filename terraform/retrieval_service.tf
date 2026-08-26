# Retrieval service (Lambda + Function URL) -- QNT-269. Dense search (S3 Vectors) ->
# OpenRouter Cohere Rerank 3.5 -> optional gpt-oss-20b generation. See docs/PRD.md §6.
#
# Lambda Function URL (AWS_IAM auth), decided over API Gateway per the ticket's
# implementation note: the only caller is the local eval client, which already carries AWS
# credentials (SigV4 via boto3), so IAM auth keeps the endpoint private with zero extra
# IaC/cost versus a public API Gateway resource. No reserved-concurrency cap (the ticket's
# suggested belt-and-suspenders extra) -- this account's total Lambda concurrency quota is
# only 10, too low to reserve any of it (see the resource below).

resource "null_resource" "retrieval_service_build" {
  triggers = {
    handler_sha      = filesha256("${path.module}/../lambda/retrieval_service/handler.py")
    requirements_sha = filesha256("${path.module}/../lambda/retrieval_service/requirements.txt")
  }

  provisioner "local-exec" {
    command = "${path.module}/../lambda/retrieval_service/build.sh"
  }
}

data "archive_file" "retrieval_service" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/retrieval_service/build"
  output_path = "${path.module}/retrieval_service.zip"

  depends_on = [null_resource.retrieval_service_build]
}

resource "aws_iam_role" "retrieval_service" {
  name = "equity-rag-aws-retrieval-service-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

# Least-privilege: read the corpus (to join dense hits back to source text -- S3 Vectors
# metadata doesn't carry it, see lambda/retrieval_service/handler.py), query (not put)
# both S3 Vectors indices, and log. No s3vectors:GetVectors -- returnMetadata is never
# requested, so that extra permission (required only when reading metadata back) isn't
# needed. Rerank/generation calls go to OpenRouter (external HTTPS, not an AWS action) --
# auth is the OPENROUTER_API_KEY env var below, same pattern as the index job.
resource "aws_iam_role_policy" "retrieval_service" {
  name = "retrieval-service-permissions"
  role = aws_iam_role.retrieval_service.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadCorpus"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.corpus.arn}/corpus/*"
      },
      {
        Sid      = "QueryVectors"
        Effect   = "Allow"
        Action   = ["s3vectors:QueryVectors"]
        Resource = [for idx in aws_s3vectors_index.corpus : idx.index_arn]
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "retrieval_service" {
  function_name = "equity-rag-aws-retrieval-service"
  role          = aws_iam_role.retrieval_service.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.13"
  architectures = ["arm64"]
  timeout       = 30
  memory_size   = 256

  # No reserved-concurrency cap: this account's total Lambda concurrent-execution quota is
  # only 10 (aws lambda get-account-settings), and AWS enforces >=10 unreserved remaining --
  # any positive reserved value here is rejected (PutFunctionConcurrency
  # InvalidParameterValueException). The ticket's suggested cap was an optional
  # belt-and-suspenders extra on top of the IAM-auth guard below, not the primary control,
  # so this is dropped rather than blocked on a quota-increase request.

  filename         = data.archive_file.retrieval_service.output_path
  source_code_hash = data.archive_file.retrieval_service.output_base64sha256

  environment {
    variables = {
      CORPUS_BUCKET      = aws_s3_bucket.corpus.id
      VECTOR_BUCKET      = aws_s3vectors_vector_bucket.main.vector_bucket_name
      OPENROUTER_API_KEY = var.openrouter_api_key
    }
  }
}

# No aws_lambda_permission for lambda:InvokeFunctionUrl -- same-account callers with that
# permission on their own IAM identity (e.g. the operator's AdministratorAccess user) can
# invoke without a resource-based policy statement. Fine for this project's single-operator
# model; a cross-account caller would need one added here.
resource "aws_lambda_function_url" "retrieval_service" {
  function_name      = aws_lambda_function.retrieval_service.function_name
  authorization_type = "AWS_IAM"
}

output "retrieval_service_url" {
  value       = aws_lambda_function_url.retrieval_service.function_url
  description = "IAM-authenticated Function URL. Invoke with a SigV4-signed POST, e.g. uv run python scripts/invoke_retrieval.py earnings 'query text'."
}
