# AutoDialer Ultimate - Installation Guide

## System Requirements

- Debian 12 (Bookworm)
- Minimum 4GB RAM, 2 vCPU
- 20GB free disk space
- Access to FreePBX server (Server-1)
- Open ports: 80, 443, 5060/udp, 10000-20000/udp

## Quick Install

```bash
git clone https://github.com/naumenis-code/AutoDialer-Ultimate/
cd autodialer-ultimate
cp .env.example .env
nano .env  # Configure your settings
sudo ./install.sh
