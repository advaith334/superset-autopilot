# ──────────────────────── EC2 always-on host ────────────────────────
#
# Single t3.small (or whatever ec2_instance_type) running Amazon Linux 2023
# in the account's default VPC. user-data installs Docker + Compose so SSH +
# `make up` is enough to bring the stack live. Public ports for the app
# (8000), Grafana (3001), and Prometheus (9090) are open to the internet;
# SSH is gated by var.ec2_admin_cidr.
#
# Everything in this file is gated behind var.create_ec2_instance — if false
# (the default), no EC2 resources are created and S3-only tf-apply runs are
# unaffected.

# ── Default VPC discovery (we don't manage networking; just attach) ──

data "aws_vpc" "default" {
  count   = var.create_ec2_instance ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = var.create_ec2_instance ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

# ── Latest Amazon Linux 2023 AMI for the instance arch ──

data "aws_ami" "al2023" {
  count       = var.create_ec2_instance ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}

# ── SSH key pair ──

resource "aws_key_pair" "autopilot" {
  count      = var.create_ec2_instance ? 1 : 0
  key_name   = "${var.ec2_name}-key"
  public_key = var.ec2_public_key

  lifecycle {
    precondition {
      condition     = length(var.ec2_public_key) > 0
      error_message = "ec2_public_key is required when create_ec2_instance = true. Set it to the contents of your ~/.ssh/<key>.pub."
    }
  }
}

# ── Security group ──

resource "aws_security_group" "autopilot" {
  count       = var.create_ec2_instance ? 1 : 0
  name        = "${var.ec2_name}-sg"
  description = "Inbound HTTPish for the autopilot demo box; SSH from admin CIDR."
  vpc_id      = data.aws_vpc.default[0].id
  tags        = local.common_tags

  # SSH (admin only)
  ingress {
    description = "SSH from admin CIDR"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ec2_admin_cidr]
  }

  # Backend HTTP (FastAPI app, webhook target)
  ingress {
    description = "Backend (FastAPI) - public webhook target"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Grafana (public dashboard for judges)
  ingress {
    description = "Grafana dashboard"
    from_port   = 3001
    to_port     = 3001
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Prometheus (optional; harmless if exposed but consider scoping in prod)
  ingress {
    description = "Prometheus (read-only)"
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # All egress — Docker pulls, Devin API, GitHub API, S3, etc.
  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── User-data: install Docker + Compose + git on first boot ──

locals {
  user_data_script = <<-BASH
    #!/bin/bash
    set -euxo pipefail

    dnf update -y
    dnf install -y docker git make
    systemctl enable --now docker
    usermod -aG docker ec2-user

    # Docker Compose v2 plugin (Compose is not bundled with Docker on AL2023).
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL https://github.com/docker/compose/releases/download/v2.29.0/docker-compose-linux-x86_64 \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    # Make it available system-wide.
    ln -sf /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose

    # Tag completion of bootstrap.
    touch /var/log/autopilot-userdata-done
  BASH
}

# ── EC2 instance ──

resource "aws_instance" "autopilot" {
  count                       = var.create_ec2_instance ? 1 : 0
  ami                         = data.aws_ami.al2023[0].id
  instance_type               = var.ec2_instance_type
  key_name                    = aws_key_pair.autopilot[0].key_name
  vpc_security_group_ids      = [aws_security_group.autopilot[0].id]
  subnet_id                   = tolist(data.aws_subnets.default[0].ids)[0]
  associate_public_ip_address = true
  user_data                   = local.user_data_script

  root_block_device {
    volume_size = var.ec2_root_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  tags = merge(local.common_tags, {
    Name = var.ec2_name
  })
}

# ── Elastic IP so the public address survives stop/start ──

resource "aws_eip" "autopilot" {
  count    = var.create_ec2_instance ? 1 : 0
  instance = aws_instance.autopilot[0].id
  domain   = "vpc"

  tags = merge(local.common_tags, {
    Name = "${var.ec2_name}-eip"
  })
}
