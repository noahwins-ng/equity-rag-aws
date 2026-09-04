# S3 Vectors store (one index per corpus) + the index-job Lambda that embeds the
# frozen snapshot into it (QNT-268). See docs/PRD.md §5 (point_id identity), §6
# (architecture: "index job (Lambda, one-shot)").

locals {
  corpora = toset(["news", "earnings"])
}

resource "aws_s3vectors_vector_bucket" "main" {
  vector_bucket_name = "equity-rag-aws-vectors-${data.aws_caller_identity.current.account_id}"

  # Ephemeral project: `terraform destroy` must succeed even if vectors remain.
  force_destroy = true
}

# One index per corpus (PRD §6) -- 512-dim Titan V2 embeddings, cosine distance.
resource "aws_s3vectors_index" "corpus" {
  for_each = local.corpora

  vector_bucket_name = aws_s3vectors_vector_bucket.main.vector_bucket_name
  index_name         = each.value
  data_type          = "float32"
  dimension          = 512
  distance_metric    = "cosine"
}

# Vendors lambda/index_job/requirements.txt + handler.py into build/ (pure-Python
# deps, no cross-compilation concerns) for archive_file to zip below. Rebuilds
# whenever the handler or pinned deps change.
resource "null_resource" "index_job_build" {
  triggers = {
    handler_sha      = filesha256("${path.module}/../lambda/index_job/handler.py")
    requirements_sha = filesha256("${path.module}/../lambda/index_job/requirements.txt")
  }

  provisioner "local-exec" {
    command = "${path.module}/../lambda/index_job/build.sh"
  }
}

data "archive_file" "index_job" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/index_job/build"
  output_path = "${path.module}/index_job.zip"

  depends_on = [null_resource.index_job_build]
}

resource "aws_iam_role" "index_job" {
  name = "equity-rag-aws-index-job-role"

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

# Least-privilege for the job: read the corpus, write to the two S3 Vectors indices,
# and log. Embedding calls go to OpenRouter (external HTTPS, not an AWS action -- no
# IAM statement needed; auth is the OPENROUTER_API_KEY env var below). AC3's sanity
# checks (counts, sample query) run locally under the operator's own credentials, not
# this role.
resource "aws_iam_role_policy" "index_job" {
  name = "index-job-permissions"
  role = aws_iam_role.index_job.id

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
        Sid      = "WriteVectors"
        Effect   = "Allow"
        Action   = ["s3vectors:PutVectors"]
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

# Explicit so it's tracked in state and removed by `terraform destroy` -- the auto-created
# group for this function was found orphaned after the QNT-272 teardown (QNT-271 only
# declared the retrieval-service one). Same pattern as retrieval_service.tf.
resource "aws_cloudwatch_log_group" "index_job" {
  name              = "/aws/lambda/equity-rag-aws-index-job"
  retention_in_days = 14
}

resource "aws_lambda_function" "index_job" {
  function_name = "equity-rag-aws-index-job"
  role          = aws_iam_role.index_job.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.13"
  architectures = ["arm64"]
  timeout       = 900
  memory_size   = 256

  filename         = data.archive_file.index_job.output_path
  source_code_hash = data.archive_file.index_job.output_base64sha256

  environment {
    variables = {
      CORPUS_BUCKET      = aws_s3_bucket.corpus.id
      VECTOR_BUCKET      = aws_s3vectors_vector_bucket.main.vector_bucket_name
      OPENROUTER_API_KEY = var.openrouter_api_key
    }
  }
}

output "vector_bucket" {
  value       = aws_s3vectors_vector_bucket.main.vector_bucket_name
  description = "S3 Vectors bucket holding the news/earnings indices."
}

output "index_job_function_name" {
  value       = aws_lambda_function.index_job.function_name
  description = "Invoke manually per corpus, e.g. aws lambda invoke --function-name <this> --payload '{\"corpus\":\"news\"}' out.json"
}
