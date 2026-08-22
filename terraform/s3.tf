# Seeds the frozen corpus snapshot (QNT-265 monorepo export, staged locally under the
# gitignored ../data/) into S3 -- the read-only input to the index job (QNT-268). See
# docs/PRD.md §5 for the seam contract; §6 for the bucket's place in the architecture.

locals {
  data_dir = "${path.module}/../data"
  manifest = jsondecode(file("${local.data_dir}/manifest.json"))
}

resource "aws_s3_bucket" "corpus" {
  bucket = "equity-rag-aws-corpus-${data.aws_caller_identity.current.account_id}"

  # Ephemeral project: `terraform destroy` must succeed even if objects remain.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "corpus" {
  bucket = aws_s3_bucket.corpus.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Snapshot rows (corpus/{news,earnings}.jsonl, labels/*) -- keys mirror manifest.json's
# `files` map 1:1, so the S3 prefix layout matches the local staging layout exactly.
# `point_id` lives inside each row's JSON and travels verbatim: these are unmodified
# byte-for-byte uploads, never re-derived (PRD §5, architecture_rules).
resource "aws_s3_object" "snapshot_files" {
  for_each = local.manifest.files

  bucket             = aws_s3_bucket.corpus.id
  key                = each.key
  source             = "${local.data_dir}/${each.key}"
  etag               = filemd5("${local.data_dir}/${each.key}")
  checksum_algorithm = "SHA256"
}

resource "aws_s3_object" "manifest" {
  bucket             = aws_s3_bucket.corpus.id
  key                = "manifest.json"
  source             = "${local.data_dir}/manifest.json"
  etag               = filemd5("${local.data_dir}/manifest.json")
  checksum_algorithm = "SHA256"
}

output "corpus_bucket" {
  value       = aws_s3_bucket.corpus.id
  description = "S3 bucket holding the frozen corpus snapshot (used by scripts/verify_s3_checksums.sh and the QNT-268 index job)."
}
