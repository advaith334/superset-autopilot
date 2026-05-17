output "artifacts_bucket" {
  description = "Bucket holding triage artifacts (screenshots, logs, HARs)."
  value       = aws_s3_bucket.artifacts.bucket
}

output "casefiles_bucket" {
  description = "Bucket holding case-file JSON bundles handed to Devin."
  value       = aws_s3_bucket.casefiles.bucket
}

output "s3_endpoint_in_use" {
  description = "Effective S3 endpoint (LocalStack URL or empty for real AWS)."
  value       = var.use_localstack ? var.localstack_endpoint : "default-aws"
}

# ──────────────────────── EC2 ────────────────────────

output "ec2_public_dns" {
  description = "Public DNS of the autopilot EC2 host (null when create_ec2_instance = false)."
  value       = var.create_ec2_instance ? aws_instance.autopilot[0].public_dns : null
}

output "ec2_public_ip" {
  description = "Elastic IP attached to the autopilot host."
  value       = var.create_ec2_instance ? aws_eip.autopilot[0].public_ip : null
}

output "ec2_ssh_command" {
  description = "Copy-pasteable SSH command (assumes default ec2-user)."
  value       = var.create_ec2_instance ? "ssh ec2-user@${aws_eip.autopilot[0].public_ip}" : null
}

output "ec2_dashboard_url" {
  description = "URL the judges will hit once you bring docker compose up on the host."
  value       = var.create_ec2_instance ? "http://${aws_eip.autopilot[0].public_ip}:3001/d/autopilot" : null
}

output "ec2_webhook_url" {
  description = "Plug this into the GitHub webhook config on your fork."
  value       = var.create_ec2_instance ? "http://${aws_eip.autopilot[0].public_ip}:8000/webhook/github" : null
}
