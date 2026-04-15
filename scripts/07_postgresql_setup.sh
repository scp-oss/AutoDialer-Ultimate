#!/bin/bash
# PostgreSQL Setup

set -e
source "$SCRIPT_DIR/../.env"

print_step "Setting up PostgreSQL..."

# Generate password if not set
if [ -z "$DB_PASSWORD" ]; then
    DB_PASSWORD=$(openssl rand -hex 16)
    echo "DB_PASSWORD=$DB_PASSWORD" >> "$SCRIPT_DIR/../.env"
fi

systemctl enable postgresql
systemctl start postgresql

# Create database and user
sudo -u postgres psql << EOF
CREATE DATABASE autodialer;
CREATE USER autodialer WITH PASSWORD '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE autodialer TO autodialer;
EOF

# Import schema
sudo -u postgres psql -d autodialer -f "$SCRIPT_DIR/../sql/schema.sql"

# PostgreSQL tuning
PG_CONF=$(find /etc/postgresql -name "postgresql.conf" | head -1)
cat >> "$PG_CONF" << EOF
shared_buffers = 256MB
work_mem = 4MB
maintenance_work_mem = 64MB
effective_cache_size = 1GB
random_page_cost = 1.1
max_connections = 200
EOF

systemctl restart postgresql

print_success "PostgreSQL configured"
