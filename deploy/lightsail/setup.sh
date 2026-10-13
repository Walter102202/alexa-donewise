#!/bin/sh
# Run on the dedicated Ubuntu Lightsail instance only. Preserves data and secrets.
set -eu
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo install -d -m 0755 /opt/donewise /opt/donewise/source /opt/donewise/data
sudo install -d -m 0700 /opt/donewise/private
# Use existing swap if provided; the minimum instance needs headroom for image builds.
if [ "$(swapon --show --noheadings | wc -l)" -eq 0 ] && [ ! -e /opt/donewise/swap ]; then
    sudo fallocate -l 2G /opt/donewise/swap
    sudo chmod 600 /opt/donewise/swap
    sudo mkswap /opt/donewise/swap
    sudo swapon /opt/donewise/swap
    echo '/opt/donewise/swap none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
