# Deploying the always-on demo on EC2

End-to-end walkthrough from zero to a public URL judges can click.

**Cost:** ~$15/month while running (t3.small + EIP). `terraform destroy` stops the bill.

**You will need:** AWS credentials with EC2 + IAM perms, an SSH key pair, your existing `.env` from local dev (Devin key, GitHub PAT, AWS S3 creds, GitHub webhook secret).

---

## 1. One-time setup

```bash
# Generate an SSH key just for this host (don't reuse your main one)
ssh-keygen -t ed25519 -f ~/.ssh/autopilot -C "autopilot-ec2"
# This creates ~/.ssh/autopilot (private) and ~/.ssh/autopilot.pub (public).

# Find your public IP so we can lock SSH to it
curl -s https://api.ipify.org && echo
```

Then create `backend/terraform/ec2.tfvars` from the example:

```bash
cp backend/terraform/ec2.tfvars.example backend/terraform/ec2.tfvars
```

Edit `ec2.tfvars`:
- `ec2_admin_cidr = "<your-ip>/32"` — replace `0.0.0.0/0` so only you can SSH
- `ec2_public_key = "<contents of ~/.ssh/autopilot.pub>"` — paste the whole line

---

## 2. Apply

```bash
terraform -chdir=backend/terraform init     # if you haven't already
terraform -chdir=backend/terraform apply -var-file=ec2.tfvars
```

Outputs you'll see:

```
ec2_public_dns      = "ec2-44-208-208-66.compute-1.amazonaws.com"
ec2_public_ip       = "44.208.208.66"
ec2_ssh_command     = "ssh ec2-user@44.208.208.66"
ec2_dashboard_url   = "http://44.208.208.66:3001/d/autopilot"
ec2_webhook_url     = "http://44.208.208.66:8000/webhook/github"
```

Save those.

---

## 3. SSH in and bring up the stack

```bash
ssh -i ~/.ssh/autopilot ec2-user@<ec2_public_ip>
```

First boot installs Docker + Compose via user-data; verify it's done:

```bash
ls /var/log/autopilot-userdata-done   # should exist
docker --version && docker compose version
```

Then on the box:

```bash
git clone https://github.com/advaith334/superset-devin-autopilot.git
cd superset-devin-autopilot

# Copy your local .env over (from your laptop, in a separate terminal):
#   scp -i ~/.ssh/autopilot .env ec2-user@<ec2_public_ip>:~/superset-devin-autopilot/.env

# Or paste it inline:
nano .env   # paste the same values as your local .env
```

Bring it up:

```bash
make up
make doctor   # all services healthy?
make migrate  # alembic upgrade head
```

---

## 4. Repoint the GitHub webhook

The webhook target moves from your `ngrok` URL to the EC2's public DNS:

```bash
# From your laptop:
source .env
gh api -X PATCH "repos/${GITHUB_TARGET_REPO}/hooks/<HOOK_ID>" \
  -f "config[url]=http://<ec2_public_ip>:8000/webhook/github" \
  -f "config[content_type]=json" \
  -f "config[secret]=${GITHUB_WEBHOOK_SECRET}"
```

(Find the hook ID with `gh api "repos/${GITHUB_TARGET_REPO}/hooks" --jq '.[].id'`.)

---

## 5. Lock it down before sharing

Two things that matter before you paste the URL in your submission:

### a. Grafana basic-auth password

By default Grafana is `admin/admin` AND has anonymous admin access enabled (good for local dev, terrible for a public IP). On the EC2:

```bash
# Edit docker-compose.yml — set GF_AUTH_ANONYMOUS_ENABLED=false and change the admin password
nano docker-compose.yml
# Then:
docker compose up -d --force-recreate grafana
```

### b. Disable `/dispatch/{id}` or pre-fire the demos

Anyone hitting `POST http://<ip>:8000/dispatch/N` could burn your Devin ACU budget. Two options:

- **Cheap fix:** Set `AUTO_DISPATCH_THRESHOLD=1.0` in `.env` and restart — auto-dispatch goes off; only triage runs sit ready until you fire `/dispatch` from your machine.
- **Better:** Add a simple header check to the `/dispatch` route. Out of scope for this walkthrough.

---

## 6. Send the submission

In your README under the demo section:

```
Live demo (read-only): http://<ec2_public_ip>:3001/d/autopilot
  user: judge
  password: <whatever you set>
```

Judges open the link, log in, see the dashboard with whatever sessions and PRs you've already produced on your account.

---

## 7. When you're done

```bash
terraform -chdir=backend/terraform destroy -var-file=ec2.tfvars
```

Everything goes away. The S3 buckets stay (they're in `main.tf`, not gated on `create_ec2_instance`).

---

## Honest caveats

- **Plain HTTP only.** No TLS. If you want HTTPS you'll need a real domain + ACM cert + ALB, or Caddy on the box auto-fetching Let's Encrypt. Skipped here because it adds 50+ Terraform lines and 30 min of setup; not worth it for a 1-week demo.
- **No log shipping.** Logs live on the box. `docker compose logs -f` for live tailing.
- **No backups.** Postgres is on the EBS root volume. If the volume dies, state is gone. Acceptable for demo.
- **Single point of failure.** One box. If AWS reboots it, judges see a brief outage; auto-restart via `restart: unless-stopped` would help (currently not set in compose).
