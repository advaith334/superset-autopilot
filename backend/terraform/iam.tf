# IAM roles defining the trust boundaries described in plan.md §2.4.
# - control-plane: full S3 (mints pre-signed URLs)
# - data-plane (triage): scoped to artifacts bucket
# - Devin sessions: NO IAM role; they only ever receive short-TTL pre-signed URLs.

data "aws_iam_policy_document" "control_plane_s3" {
  statement {
    sid     = "FullAccessToAutopilotBuckets"
    effect  = "Allow"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
      aws_s3_bucket.casefiles.arn,
      "${aws_s3_bucket.casefiles.arn}/*",
    ]
  }
}

data "aws_iam_policy_document" "triage_worker_s3" {
  statement {
    sid    = "ArtifactPutGetOnly"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]
  }
  statement {
    sid       = "ListArtifactsBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]
  }
}

resource "aws_iam_policy" "control_plane_s3" {
  count  = var.create_iam_policies ? 1 : 0
  name   = "${var.bucket_prefix}-control-plane-s3"
  policy = data.aws_iam_policy_document.control_plane_s3.json
}

resource "aws_iam_policy" "triage_worker_s3" {
  count  = var.create_iam_policies ? 1 : 0
  name   = "${var.bucket_prefix}-triage-worker-s3"
  policy = data.aws_iam_policy_document.triage_worker_s3.json
}

# Roles + instance-profile attachments are environment-specific (EKS IRSA,
# ECS task role, EC2 instance profile). We define the policies here; the
# binding lives in whatever environment module deploys the services.
output "control_plane_policy_arn" {
  value = var.create_iam_policies ? aws_iam_policy.control_plane_s3[0].arn : null
}

output "triage_worker_policy_arn" {
  value = var.create_iam_policies ? aws_iam_policy.triage_worker_s3[0].arn : null
}
