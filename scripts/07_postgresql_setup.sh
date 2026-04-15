#!/bin/bash
# =============================================
# AutoDialer Ultimate - PostgreSQL Setup
# Version: 3.0.0
# =============================================

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_step() { echo -e "${GREEN}[STEP]${NC} $1"; }
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${CYAN}[SUCCESS]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================
# Load Configuration
# =============================================
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
    print_info "Loaded configuration from .env"
fi

# Database configuration
DB_NAME="${DB_NAME:-autodialer}"
DB_USER="${DB_USER:-autodialer}"
DB_PASSWORD="${DB_PASSWORD:-$(openssl rand -hex 16)}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

# Save password to .env if not exists
if [ -f "$PROJECT_ROOT/.env" ] && ! grep -q "^DB_PASSWORD=" "$PROJECT_ROOT/.env"; then
    echo "DB_PASSWORD=$DB_PASSWORD" >> "$PROJECT_ROOT/.env"
    print_info "Saved DB_PASSWORD to .env"
fi

print_info "Database: $DB_NAME"
print_info "User: $DB_USER"

# =============================================
# Install PostgreSQL (if not installed)
# =============================================
print_step "Checking PostgreSQL installation..."

if ! command -v psql &> /dev/null; then
    print_info "Installing PostgreSQL..."
    apt update
    apt install -y postgresql postgresql-contrib postgresql-client
    print_success "PostgreSQL installed"
else
    POSTGRES_VERSION=$(psql --version | head -1)
    print_success "PostgreSQL already installed: $POSTGRES_VERSION"
fi

# =============================================
# Start and Enable PostgreSQL
# =============================================
print_step "Starting PostgreSQL..."

systemctl enable postgresql
systemctl start postgresql

# Wait for PostgreSQL to be ready
for i in {1..10}; do
    if sudo -u postgres psql -c "SELECT 1" &>/dev/null; then
        print_success "PostgreSQL is ready"
        break
    fi
    print_info "Waiting for PostgreSQL... ($i/10)"
    sleep 2
done

# =============================================
# Configure PostgreSQL
# =============================================
print_step "Configuring PostgreSQL..."

# Get PostgreSQL version and config path
PG_VERSION=$(sudo -u postgres psql -t -c "SHOW server_version;" | xargs | cut -d' ' -f1 | cut -d'.' -f1)
PG_CONF=$(find /etc/postgresql -name "postgresql.conf" | head -1)

if [ -f "$PG_CONF" ]; then
    print_info "Configuring $PG_CONF"
    
    # Backup original config
    cp "$PG_CONF" "${PG_CONF}.backup"
    
    # Tune PostgreSQL for AutoDialer
    cat >> "$PG_CONF" << 'EOF'

# =============================================
# AutoDialer Ultimate Optimizations
# =============================================
shared_buffers = 256MB
work_mem = 4MB
maintenance_work_mem = 64MB
effective_cache_size = 1GB
random_page_cost = 1.1
effective_io_concurrency = 200
wal_buffers = 16MB
min_wal_size = 1GB
max_wal_size = 4GB
max_connections = 200
superuser_reserved_connections = 3
checkpoint_completion_target = 0.9
default_statistics_target = 100
autovacuum = on
autovacuum_vacuum_scale_factor = 0.05
autovacuum_analyze_scale_factor = 0.025
log_min_duration_statement = 1000
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_checkpoints = on
log_connections = on
log_disconnections = on
log_lock_waits = on
log_temp_files = 0
datestyle = 'iso, mdy'
timezone = 'UTC'
lc_messages = 'en_US.UTF-8'
lc_monetary = 'en_US.UTF-8'
lc_numeric = 'en_US.UTF-8'
lc_time = 'en_US.UTF-8'
default_text_search_config = 'pg_catalog.english'
EOF

    print_success "PostgreSQL configuration updated"
fi

# Configure pg_hba.conf
PG_HBA=$(find /etc/postgresql -name "pg_hba.conf" | head -1)
if [ -f "$PG_HBA" ]; then
    # Ensure local connections are allowed
    if ! grep -q "^host\s\+all\s\+all\s\+127.0.0.1/32\s\+md5" "$PG_HBA"; then
        echo "host    all             all             127.0.0.1/32            md5" >> "$PG_HBA"
    fi
    print_success "pg_hba.conf updated"
fi

# Restart PostgreSQL to apply changes
systemctl restart postgresql
sleep 3

# =============================================
# Create Database and User
# =============================================
print_step "Creating database and user..."

# Check if database exists
DB_EXISTS=$(sudo -u postgres psql -t -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | xargs)

if [ "$DB_EXISTS" == "1" ]; then
    print_warn "Database '$DB_NAME' already exists"
    read -p "Drop and recreate? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo -u postgres psql -c "DROP DATABASE IF EXISTS $DB_NAME;"
        sudo -u postgres psql -c "DROP USER IF EXISTS $DB_USER;"
        DB_EXISTS=""
    fi
fi

if [ "$DB_EXISTS" != "1" ]; then
    # Create user
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
    print_success "User '$DB_USER' created"
    
    # Create database
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
    print_success "Database '$DB_NAME' created"
    
    # Grant privileges
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
    sudo -u postgres psql -c "ALTER USER $DB_USER CREATEDB;"
    print_success "Privileges granted"
fi

# =============================================
# Create Schema
# =============================================
print_step "Creating database schema..."

if [ -f "$PROJECT_ROOT/sql/schema.sql" ]; then
    SCHEMA_FILE="$PROJECT_ROOT/sql/schema.sql"
elif [ -f "$PROJECT_ROOT/sql/migrations/001_initial.sql" ]; then
    SCHEMA_FILE="$PROJECT_ROOT/sql/migrations/001_initial.sql"
else
    print_warn "Schema file not found, creating basic schema..."
    SCHEMA_FILE="/tmp/autodialer_schema.sql"
    
    cat > "$SCHEMA_FILE" << 'EOF'
-- AutoDialer Ultimate Database Schema

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email VARCHAR(255),
    full_name VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'operator' CHECK (role IN ('admin', 'operator', 'viewer')),
    force_password_change BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP,
    last_ip INET,
    settings JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Campaigns table
CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'draft' CHECK (status IN ('draft', 'running', 'paused', 'stopped', 'completed', 'failed')),
    max_calls INTEGER DEFAULT 30 CHECK (max_calls > 0 AND max_calls <= 100),
    cps INTEGER DEFAULT 5 CHECK (cps > 0 AND cps <= 50),
    audio_id INTEGER,
    retry_strategy JSONB DEFAULT '{"busy": 2, "noanswer": 3, "failed": 1}',
    schedule_start TIMESTAMP,
    schedule_end TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Contacts table
CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(255),
    email VARCHAR(255),
    group_id INTEGER,
    tags TEXT[],
    custom_fields JSONB,
    status VARCHAR(50) DEFAULT 'active',
    blacklisted BOOLEAN DEFAULT FALSE,
    blacklist_reason TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Contact groups table
CREATE TABLE IF NOT EXISTS contact_groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    color VARCHAR(7) DEFAULT '#667eea',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Campaign contacts junction
CREATE TABLE IF NOT EXISTS campaign_contacts (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    retry_count INTEGER DEFAULT 0,
    last_call_at TIMESTAMP,
    next_retry_at TIMESTAMP,
    status VARCHAR(50),
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(campaign_id, contact_id)
);

-- Call results table
CREATE TABLE IF NOT EXISTS call_results (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    unique_id VARCHAR(255),
    linked_id VARCHAR(255),
    channel VARCHAR(255),
    caller_id VARCHAR(255),
    status VARCHAR(50),
    dtmf_result VARCHAR(10),
    duration INTEGER,
    billable_seconds INTEGER,
    hangup_cause VARCHAR(50),
    hangup_cause_txt TEXT,
    retry_count INTEGER DEFAULT 0,
    recording_path TEXT,
    recording_url TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Settings table
CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    category VARCHAR(50) DEFAULT 'general',
    is_public BOOLEAN DEFAULT FALSE,
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audio files table
CREATE TABLE IF NOT EXISTS audio_files (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    duration INTEGER,
    format VARCHAR(10) DEFAULT 'sln',
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_public BOOLEAN DEFAULT FALSE,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit log table
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),
    entity_id INTEGER,
    details JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Blacklist table
CREATE TABLE IF NOT EXISTS blacklist (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    reason TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- API tokens table
CREATE TABLE IF NOT EXISTS api_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE INDEX IF NOT EXISTS idx_contacts_blacklisted ON contacts(blacklisted);
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_campaign ON campaign_contacts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_contacts_next_retry ON campaign_contacts(next_retry_at) WHERE next_retry_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_call_results_campaign ON call_results(campaign_id);
CREATE INDEX IF NOT EXISTS idx_call_results_status ON call_results(status);
CREATE INDEX IF NOT EXISTS idx_call_results_created ON call_results(created_at);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_blacklist_phone ON blacklist(phone);
CREATE INDEX IF NOT EXISTS idx_api_tokens_token ON api_tokens(token);

-- Insert default settings
INSERT INTO settings (key, value, description, category) VALUES 
    ('system_enabled', 'true', 'Global system enable/disable', 'system'),
    ('global_max_calls', '50', 'Maximum concurrent calls globally', 'dialer'),
    ('default_cps', '5', 'Default calls per second', 'dialer'),
    ('call_timeout', '30', 'Call timeout in seconds', 'dialer'),
    ('max_retries', '3', 'Maximum retry attempts', 'dialer'),
    ('retry_busy_max', '2', 'Max retries for busy', 'dialer'),
    ('retry_busy_delay', '120', 'Delay for busy retry (seconds)', 'dialer'),
    ('retry_noanswer_max', '3', 'Max retries for no answer', 'dialer'),
    ('retry_noanswer_delay', '300', 'Delay for no answer retry', 'dialer'),
    ('audio_retention_days', '30', 'Audio files retention period', 'storage'),
    ('max_upload_size_mb', '10', 'Maximum upload file size', 'storage')
ON CONFLICT (key) DO NOTHING;

-- Insert default admin user (password: admin)
INSERT INTO users (username, password_hash, role, email, force_password_change) VALUES (
    'admin',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIqK0hVdGW',
    'admin',
    'admin@localhost',
    TRUE
) ON CONFLICT (username) DO NOTHING;

-- Create function for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create triggers
DROP TRIGGER IF EXISTS update_campaigns_updated_at ON campaigns;
CREATE TRIGGER update_campaigns_updated_at 
    BEFORE UPDATE ON campaigns 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_contacts_updated_at ON contacts;
CREATE TRIGGER update_contacts_updated_at 
    BEFORE UPDATE ON contacts 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at 
    BEFORE UPDATE ON users 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
EOF
fi

# Apply schema
print_info "Applying schema from $SCHEMA_FILE"
sudo -u postgres psql -d "$DB_NAME" -f "$SCHEMA_FILE"

if [ $? -eq 0 ]; then
    print_success "Schema created successfully"
else
    print_error "Schema creation failed"
    exit 1
fi

# =============================================
# Verify Database
# =============================================
print_step "Verifying database..."

# Test connection
if PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" &>/dev/null; then
    print_success "Database connection verified"
else
    print_error "Database connection failed"
    exit 1
fi

# Count tables
TABLE_COUNT=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" | xargs)
print_info "Tables created: $TABLE_COUNT"

# Check default user
ADMIN_EXISTS=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM users WHERE username = 'admin';" | xargs)
if [ "$ADMIN_EXISTS" == "1" ]; then
    print_success "Default admin user exists"
else
    print_warn "Default admin user not found"
fi

# =============================================
# Summary
# =============================================
print_success "PostgreSQL setup completed!"
echo ""
print_info "Database Configuration:"
echo "  Host: $DB_HOST"
echo "  Port: $DB_PORT"
echo "  Database: $DB_NAME"
echo "  User: $DB_USER"
echo "  Password: $DB_PASSWORD"
echo ""
print_info "Tables Created:"
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "\dt" 2>/dev/null | head -20 || true
echo ""
print_info "Default Login:"
echo "  Username: admin"
echo "  Password: admin"
echo ""
print_info "Connection String:"
echo "  postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
echo ""
print_info "Useful Commands:"
echo "  sudo -u postgres psql -d $DB_NAME"
echo "  PGPASSWORD='$DB_PASSWORD' psql -h $DB_HOST -U $DB_USER -d $DB_NAME"
echo ""
