variable "use_localstack" {
  description = "Target LocalStack instead of real AWS."
  type        = bool
  default     = true
}

variable "localstack_endpoint" {
  description = "URL of the LocalStack edge service."
  type        = string
  default     = "http://localhost:4566"
}

variable "aws_region" {
  description = "AWS region for buckets and IAM."
  type        = string
  default     = "us-east-1"
}

variable "bucket_prefix" {
  description = "Prefix applied to all created buckets, for namespacing."
  type        = string
  default     = "autopilot"
}

variable "artifacts_retention_days" {
  description = "Days before triage artifacts (screenshots, logs, HARs) expire."
  type        = number
  default     = 30
}

variable "casefiles_retention_days" {
  description = "Days before case files expire. Slightly longer so we can audit."
  type        = number
  default     = 90
}

variable "create_iam_policies" {
  description = <<-EOT
    Whether to create the IAM trust-boundary policies. These are documentation
    for future ECS/EKS deployments — the runtime path uses raw env-var creds,
    not assumed roles. Set false when the applying principal lacks iam:* perms
    (e.g. an S3-only IAM user).
  EOT
  type        = bool
  default     = true
}

# ──────────────────────── EC2 (always-on host) ────────────────────────

variable "create_ec2_instance" {
  description = "When true, provision a single EC2 box running docker-compose for the always-on demo."
  type        = bool
  default     = false
}

variable "ec2_instance_type" {
  description = "EC2 instance type. t3.small (~$15/mo) is the floor for fastembed + Postgres + Grafana."
  type        = string
  default     = "t3.small"
}

variable "ec2_admin_cidr" {
  description = <<-EOT
    CIDR allowed to SSH into the box. Default 0.0.0.0/0 (anywhere) is convenient
    but insecure; narrow to your own IP/32 for real deployments.
  EOT
  type        = string
  default     = "0.0.0.0/0"
}

variable "ec2_public_key" {
  description = <<-EOT
    Contents of an SSH public key (e.g. cat ~/.ssh/id_ed25519.pub) to authorize
    on ec2-user. Required when create_ec2_instance = true.
  EOT
  type        = string
  default     = ""
}

variable "ec2_root_volume_gb" {
  description = "Root EBS volume size in GB. Docker images + fastembed model + Postgres data."
  type        = number
  default     = 30
}

variable "ec2_name" {
  description = "Name tag for the EC2 instance + supporting resources."
  type        = string
  default     = "autopilot"
}
