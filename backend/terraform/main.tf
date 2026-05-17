locals {
  artifacts_bucket = "${var.bucket_prefix}-artifacts"
  casefiles_bucket = "${var.bucket_prefix}-casefiles"
  common_tags = {
    Project   = "superset-devin-autopilot"
    ManagedBy = "terraform"
  }
}

# ──────────── Buckets ────────────

resource "aws_s3_bucket" "artifacts" {
  bucket        = local.artifacts_bucket
  force_destroy = true
  tags          = local.common_tags
}

resource "aws_s3_bucket" "casefiles" {
  bucket        = local.casefiles_bucket
  force_destroy = true
  tags          = local.common_tags
}

# ──────────── Versioning (audit trail for case files) ────────────

resource "aws_s3_bucket_versioning" "casefiles" {
  bucket = aws_s3_bucket.casefiles.id
  versioning_configuration {
    status = "Enabled"
  }
}

# ──────────── Lifecycle (cap storage cost) ────────────

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-old-artifacts"
    status = "Enabled"
    filter {}
    expiration {
      days = var.artifacts_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "casefiles" {
  bucket = aws_s3_bucket.casefiles.id
  rule {
    id     = "expire-old-casefiles"
    status = "Enabled"
    filter {}
    expiration {
      days = var.casefiles_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# ──────────── Server-side encryption ────────────

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "casefiles" {
  bucket = aws_s3_bucket.casefiles.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ──────────── Public access block (private buckets; access via pre-signed URLs only) ────────────

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "casefiles" {
  bucket                  = aws_s3_bucket.casefiles.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
