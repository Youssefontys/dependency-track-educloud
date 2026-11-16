#!/bin/bash
# Uitgevoerd door de remote-exec provisioner in main.tf, na de file-provisioners die de
# bestanden naar /tmp zetten. Gaat uit van Ubuntu (apt); pas de Docker-repo-URL aan naar
# linux/debian als het gekozen Educloud-template geen Ubuntu is.
set -eu

sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg python3 openssl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo mkdir -p /opt/dependency-track /opt/sbom-naar-dtrack

sudo mv /tmp/compose.yaml /opt/dependency-track/compose.yaml

# Wachtwoord hier op de VM zelf genereren, net als in de handmatige README-stappen: zo komt
# het nooit in terraform.tfstate of over SSH als los bestand, alleen hier op schijf.
if [ ! -f /opt/dependency-track/.env ]; then
  echo "DT_DB_PASSWORD=$(openssl rand -hex 32)" | sudo tee /opt/dependency-track/.env > /dev/null
fi
sudo chown root:root /opt/dependency-track/.env
sudo chmod 600 /opt/dependency-track/.env

sudo mv /tmp/sbom-naar-dtrack.py /opt/sbom-naar-dtrack/sbom-naar-dtrack.py
sudo mv /tmp/dt-meting.py /opt/sbom-naar-dtrack/dt-meting.py
sudo mv /tmp/sbom-naar-dtrack.service /etc/systemd/system/sbom-naar-dtrack.service
sudo mv /tmp/sbom-naar-dtrack.timer /etc/systemd/system/sbom-naar-dtrack.timer

# Niet overschrijven als er al handmatig een ingevulde versie staat (bijv. na een herrun).
if [ ! -f /etc/sbom-naar-dtrack.env ]; then
  sudo mv /tmp/sbom-naar-dtrack.env.example /etc/sbom-naar-dtrack.env
else
  sudo rm -f /tmp/sbom-naar-dtrack.env.example
fi
sudo chown root:root /etc/sbom-naar-dtrack.env
sudo chmod 600 /etc/sbom-naar-dtrack.env

cd /opt/dependency-track
sudo docker compose up -d
sudo systemctl daemon-reload

echo "Klaar: Docker draait, Dependency-Track start op (duurt even bij de eerste keer)."
echo "Resterend handwerk staat in README.md vanaf 'Maak in Dependency-Track...':"
echo "  admin-wachtwoord zetten, team + API-key, GitHub-token, /etc/sbom-naar-dtrack.env invullen, timer inschakelen."
