# GCP VPS (vps-1)

General-purpose VPS for hosting Docker services. Currently runs Supabase for CI integration tests.

## VM Details

| Property | Value |
|----------|-------|
| Project | `melisma-cloud` |
| VM name | `vps-1` |
| Zone | `us-central1-a` |
| Machine type | `e2-micro` (1 GB RAM, 2 shared vCPU) |
| Disk | 30 GB pd-standard |
| OS | Ubuntu 24.04 LTS |
| Swap | 4 GB |
| Static IP | Reserved in `us-central1` |
| Firewall | SSH (port 22) only |

## Initial Provisioning

These commands were run once to create the VM. Documented here for reproducibility.

### 1. GCP Project + VM

```bash
# Create project and enable Compute Engine
gcloud projects create melisma-cloud
gcloud config set project melisma-cloud
# Link billing account via GCP Console

gcloud services enable compute.googleapis.com

# Firewall: SSH only
gcloud compute firewall-rules create allow-ssh \
  --direction=INGRESS --priority=1000 --network=default \
  --action=ALLOW --rules=tcp:22 --source-ranges=0.0.0.0/0

# Reserve static IP
gcloud compute addresses create vps-1-ip --region=us-central1

# Create VM with swap startup script
gcloud compute instances create vps-1 \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard \
  --address=vps-1-ip \
  --metadata=startup-script='#!/bin/bash
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
  sysctl vm.swappiness=60
  echo "vm.swappiness=60" >> /etc/sysctl.conf
fi'
```

### 2. VM Bootstrap (via SSH)

```bash
gcloud compute ssh vps-1 --zone=us-central1-a

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change

# Install Supabase CLI
curl -fsSL https://raw.githubusercontent.com/supabase/cli/main/install.sh | sh

# Install jq + git
sudo apt-get install -y jq git

# Clone repo
sudo mkdir -p /opt/selko
sudo chown $USER:$USER /opt/selko
git clone https://github.com/tonimelisma/selko.git /opt/selko
```

### 3. CI-Optimized Supabase Config

Create `/opt/selko/supabase/config.ci.toml` overlay or edit `config.toml` on the VM to disable unused services:

```toml
[studio]
enabled = false      # ~256 MB saved

[inbucket]
enabled = false      # ~64 MB saved

[edge_runtime]
enabled = false      # ~128 MB saved

[analytics]
enabled = false      # ~64 MB saved

[realtime]
enabled = false      # ~128 MB saved

# Keep: PostgreSQL, GoTrue (auth), PostgREST (api), Storage
```

Then start Supabase:

```bash
cd /opt/selko
supabase start
```

### 4. Systemd Service

Create `/etc/systemd/system/supabase.service`:

```ini
[Unit]
Description=Supabase Local Dev Stack
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/selko
ExecStart=/usr/local/bin/supabase start
ExecStop=/usr/local/bin/supabase stop
User=toni
Environment=HOME=/home/toni

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable supabase
```

### 5. Health Check Timer

Create `/etc/systemd/system/supabase-health.service`:

```ini
[Unit]
Description=Supabase Health Check

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'curl -sf http://localhost:54321/rest/v1/ > /dev/null || systemctl restart supabase'
```

Create `/etc/systemd/system/supabase-health.timer`:

```ini
[Unit]
Description=Supabase Health Check Timer

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now supabase-health.timer
```

### 6. Weekly Docker Prune

```bash
echo "0 3 * * 0 docker system prune -f --volumes 2>&1 | logger -t docker-prune" | sudo tee /etc/cron.d/docker-prune
```

### 7. CI SSH Key

Generate a key pair locally and add the public key to the VM:

```bash
# On local machine
ssh-keygen -t ed25519 -f ci_vm -N "" -C "github-actions-ci"

# Copy public key to VM
gcloud compute ssh vps-1 --zone=us-central1-a --command="mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys" < ci_vm.pub

# Add private key content as GitHub secret CI_SUPABASE_SSH_KEY
cat ci_vm
```

## CI Integration

The `integration-tests-development` job in `.github/workflows/test.yml`:

1. **SSH key setup** — writes `CI_SUPABASE_SSH_KEY` secret to `~/.ssh/ci_vm`
2. **Health check** — verifies Supabase API is responsive via SSH
3. **Sync migrations + reset** — SCPs latest `supabase/migrations/` to VM, runs `supabase db reset`
4. **SSH tunnel** — forwards ports 54321 (API) and 54322 (DB) from runner to VM
5. **Tests run** — pytest connects to `localhost:54321` through the tunnel
6. **Cleanup** — kills tunnel, removes key file

Concurrency group `ci-supabase-vm` queues parallel runs (only one `db reset` can happen at a time).

## Maintenance

### Updating Supabase Version

```bash
gcloud compute ssh vps-1 --zone=us-central1-a

# Update CLI
curl -fsSL https://raw.githubusercontent.com/supabase/cli/main/install.sh | sh

# Restart with new version
cd /opt/selko
supabase stop
supabase start
```

### Syncing Config Changes

If `supabase/config.toml` changes in the repo, pull changes on the VM:

```bash
cd /opt/selko
git pull
# Re-apply CI overrides (disabled studio, inbucket, etc.)
supabase stop
supabase start
```

### Monitoring

```bash
# Check swap usage
free -h

# Check Docker resource usage
docker stats --no-stream

# Check Supabase health
curl -sf http://localhost:54321/rest/v1/ && echo "healthy"

# Check systemd services
systemctl status supabase
systemctl status supabase-health.timer
```

### Rollback

If the VM approach fails, revert `.github/workflows/test.yml` to the previous version. The old Docker-based approach is self-contained and works immediately with no external dependencies.
