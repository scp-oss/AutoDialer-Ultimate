#!/bin/bash
# =============================================
# AutoDialer Ultimate - Nginx Setup
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

DOMAIN_NAME="${DOMAIN_NAME:-}"
SERVER_IP=$(hostname -I | awk '{print $1}')

# =============================================
# Install Nginx
# =============================================
print_step "Checking Nginx installation..."

if ! command -v nginx &> /dev/null; then
    print_info "Installing Nginx..."
    apt update
    apt install -y nginx nginx-extras
    print_success "Nginx installed"
else
    NGINX_VERSION=$(nginx -v 2>&1 | cut -d'/' -f2)
    print_success "Nginx already installed: $NGINX_VERSION"
fi

# =============================================
# Create Nginx Configuration
# =============================================
print_step "Creating Nginx configuration..."

# Backup default config
if [ -f /etc/nginx/sites-available/default ] && [ ! -f /etc/nginx/sites-available/default.backup ]; then
    cp /etc/nginx/sites-available/default /etc/nginx/sites-available/default.backup
    print_info "Default configuration backed up"
fi

# Create AutoDialer configuration
cat > /etc/nginx/sites-available/autodialer << 'EOF'
# =============================================
# AutoDialer Ultimate Nginx Configuration
# =============================================

# Upstream backend
upstream autodialer_backend {
    least_conn;
    server 127.0.0.1:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}

# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;
limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

# WebSocket upgrade map
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    
    # Maximum client body size (for audio uploads)
    client_max_body_size 50M;
    
    # Timeouts
    client_body_timeout 60s;
    client_header_timeout 60s;
    send_timeout 60s;
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 120s;
    
    # Buffering
    proxy_buffering off;
    proxy_request_buffering off;
    
    # Connection limits
    limit_conn conn_limit 100;
    limit_conn_status 429;
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    server_tokens off;
    
    # =============================================
    # API Endpoints
    # =============================================
    location /api {
        limit_req zone=api_limit burst=20 nodelay;
        limit_req_status 429;
        
        proxy_pass http://autodialer_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_no_cache 1;
        proxy_cache_bypass 1;
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
    }
    
    # =============================================
    # Auth Endpoints (stricter rate limits)
    # =============================================
    location /api/auth/login {
        limit_req zone=login_limit burst=3 nodelay;
        limit_req_status 429;
        proxy_pass http://autodialer_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # =============================================
    # Documentation
    # =============================================
    location /docs {
        proxy_pass http://autodialer_backend;
        proxy_set_header Host $host;
    }
    
    location /redoc {
        proxy_pass http://autodialer_backend;
        proxy_set_header Host $host;
    }
    
    location /openapi.json {
        proxy_pass http://autodialer_backend;
        proxy_set_header Host $host;
    }
    
    # =============================================
    # Metrics (Restricted)
    # =============================================
    location /metrics {
        allow 127.0.0.1;
        allow ::1;
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        deny all;
        
        proxy_pass http://autodialer_backend;
        proxy_set_header Host $host;
    }
    
    # =============================================
    # Health Check
    # =============================================
    location /api/health {
        proxy_pass http://autodialer_backend;
        proxy_set_header Host $host;
    }
    
    # =============================================
    # WebSocket
    # =============================================
    location /ws {
        proxy_pass http://autodialer_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }
    
    # =============================================
    # Static Frontend
    # =============================================
    location / {
        root /opt/autodialer/frontend/dist;
        try_files $uri $uri/ /index.html;
        index index.html;
        
        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 30d;
            add_header Cache-Control "public, immutable";
        }
        
        # HTML - no cache
        location ~* \.html$ {
            expires -1;
            add_header Cache-Control "no-cache, no-store, must-revalidate";
        }
    }
    
    # =============================================
    # Audio Files
    # =============================================
    location /audio/ {
        alias /var/lib/asterisk/sounds/tts/;
        add_header Access-Control-Allow-Origin "*";
        add_header Accept-Ranges bytes;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
    
    # =============================================
    # Deny hidden files
    # =============================================
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
    
    # =============================================
    # Error Pages
    # =============================================
    error_page 404 /index.html;
    error_page 500 502 503 504 /50x.html;
    
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}
EOF

print_success "Nginx configuration created"

# =============================================
# Enable Site
# =============================================
print_step "Enabling site..."

# Remove default site
rm -f /etc/nginx/sites-enabled/default

# Enable AutoDialer site
ln -sf /etc/nginx/sites-available/autodialer /etc/nginx/sites-enabled/autodialer

print_success "Site enabled"

# =============================================
# Configure Nginx Main Settings
# =============================================
print_step "Configuring Nginx main settings..."

# Backup nginx.conf
if [ -f /etc/nginx/nginx.conf ] && [ ! -f /etc/nginx/nginx.conf.backup ]; then
    cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup
fi

# Update worker settings
cat > /etc/nginx/nginx.conf << 'EOF'
user www-data;
worker_processes auto;
worker_rlimit_nofile 65535;
pid /run/nginx.pid;

include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 4096;
    multi_accept on;
    use epoll;
}

http {
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;
    
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;
    
    # Gzip
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml application/json application/javascript application/xml+rss application/atom+xml image/svg+xml;
    
    # Virtual Host Configs
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
EOF

print_success "Nginx main configuration updated"

# =============================================
# Test Configuration
# =============================================
print_step "Testing Nginx configuration..."

if nginx -t; then
    print_success "Configuration test passed"
else
    print_error "Configuration test failed"
    exit 1
fi

# =============================================
# Create Systemd Override
# =============================================
print_step "Creating systemd override for Nginx..."

mkdir -p /etc/systemd/system/nginx.service.d

cat > /etc/systemd/system/nginx.service.d/limits.conf << 'EOF'
[Service]
LimitNOFILE=65535
LimitMEMLOCK=infinity
EOF

systemctl daemon-reload
print_success "Systemd override created"

# =============================================
# Start and Enable Nginx
# =============================================
print_step "Starting Nginx..."

systemctl enable nginx
systemctl restart nginx

if systemctl is-active --quiet nginx; then
    print_success "Nginx started"
else
    print_error "Nginx failed to start"
    systemctl status nginx --no-pager
    exit 1
fi

# =============================================
# Configure HTTPS with Let's Encrypt (Optional)
# =============================================
if [ -n "$DOMAIN_NAME" ]; then
    print_step "Configuring HTTPS with Let's Encrypt..."
    
    if command -v certbot &> /dev/null; then
        print_info "Requesting certificate for $DOMAIN_NAME"
        
        # Stop nginx temporarily for standalone verification
        systemctl stop nginx
        
        certbot certonly --standalone \
            -d "$DOMAIN_NAME" \
            --non-interactive \
            --agree-tos \
            --email "admin@$DOMAIN_NAME" \
            --keep-until-expiring \
            --expand 2>/dev/null || {
            print_warn "Certificate request failed"
            systemctl start nginx
        }
        
        if [ -f "/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem" ]; then
            # Create HTTPS configuration
            cat > /etc/nginx/sites-available/autodialer-ssl << EOF
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $DOMAIN_NAME;
    
    ssl_certificate /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/$DOMAIN_NAME/chain.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    
    add_header Strict-Transport-Security "max-age=63072000" always;
    
    client_max_body_size 50M;
    
    location / {
        proxy_pass http://autodialer_backend;
        include /etc/nginx/sites-available/autodialer;
    }
}

server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN_NAME;
    return 301 https://\$server_name\$request_uri;
}
EOF
            
            ln -sf /etc/nginx/sites-available/autodialer-ssl /etc/nginx/sites-enabled/autodialer-ssl
            systemctl start nginx
            nginx -t && systemctl reload nginx
            print_success "HTTPS configured for $DOMAIN_NAME"
        fi
    else
        print_warn "Certbot not installed, HTTPS not configured"
    fi
fi

# =============================================
# Verify Nginx
# =============================================
print_step "Verifying Nginx..."

# Test HTTP
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/ | grep -q "200\|301\|302"; then
    print_success "HTTP endpoint responding"
else
    print_warn "HTTP endpoint not responding"
fi

# Test API health
if curl -s http://127.0.0.1/api/health | grep -q "ok"; then
    print_success "API health check passed"
else
    print_warn "API health check failed"
fi

# =============================================
# Summary
# =============================================
print_success "Nginx setup completed!"
echo ""
print_info "Nginx Configuration:"
echo "  Server IP: $SERVER_IP"
if [ -n "$DOMAIN_NAME" ]; then
    echo "  Domain: $DOMAIN_NAME"
fi
echo "  Config: /etc/nginx/sites-available/autodialer"
echo "  Logs: /var/log/nginx/"
echo ""
print_info "Endpoints:"
echo "  Web UI: http://$SERVER_IP/"
if [ -n "$DOMAIN_NAME" ]; then
    echo "  Web UI (HTTPS): https://$DOMAIN_NAME/"
fi
echo "  API: http://$SERVER_IP/api"
echo "  Docs: http://$SERVER_IP/docs"
echo "  Metrics: http://$SERVER_IP/metrics (restricted)"
echo ""
print_info "Useful Commands:"
echo "  nginx -t                     - Test configuration"
echo "  systemctl reload nginx       - Reload configuration"
echo "  systemctl status nginx       - Check status"
echo "  tail -f /var/log/nginx/error.log - Watch error log"
echo "  tail -f /var/log/nginx/access.log - Watch access log"
echo ""
