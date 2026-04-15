#!/usr/bin/env python3
"""
AutoDialer Ultimate - Main FastAPI Application
Version: 3.0.0
"""

import asyncio
import asyncpg
import redis.asyncio as redis
import os
import json
import signal
import uuid
import re
import subprocess
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from prometheus_client import Counter, Gauge, Histogram, generate_latest

from logger import logger, correlation_id_var
from auth import (
    TokenData, get_current_user, require_admin, verify_metrics_auth,
    hash_password, verify_password, create_token, decode_token
)
from circuit_breaker import CircuitBreaker
from rate_limiter import TokenBucket, GlobalRateLimiter, SlidingWindowRateLimiter
from leader_election import LeaderElection
from task_registry import TaskRegistry

# =============================================
# Prometheus Metrics
# =============================================
active_calls_gauge = Gauge('autodialer_active_calls', 'Active calls')
calls_total = Counter('autodialer_calls_total', 'Total calls', ['status'])
cps_histogram = Histogram('autodialer_cps', 'Calls per second')
http_requests = Counter('autodialer_http_requests', 'HTTP requests', ['method', 'endpoint', 'status'])

# =============================================
# Global Variables
# =============================================
db_pool = None
redis_client = None
dialer_manager = None
task_registry = TaskRegistry()

# Circuit breakers
db_breaker = CircuitBreaker("database", failure_threshold=3, recovery_timeout=30)
redis_breaker = CircuitBreaker("redis", failure_threshold=3, recovery_timeout=30)

# Rate limiters
rate_limiter = None  # Will be initialized after redis_client
global_cps_limiter = None  # Will be initialized after redis_client

# Leader election for cleanup tasks
cleanup_leader = None  # Will be initialized after redis_client

# =============================================
# Pydantic Models
# =============================================
class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class CampaignCreate(BaseModel):
    name: str
    max_calls: int = 30
    cps: int = 5
    audio_id: Optional[int] = None
    retry_strategy: Optional[dict] = None

class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    max_calls: Optional[int] = None
    cps: Optional[int] = None
    audio_id: Optional[int] = None
    status: Optional[str] = None

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "operator"

class UserUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None

class SettingsUpdate(BaseModel):
    value: str

class AudioGenerate(BaseModel):
    text: str
    name: str
    campaign_id: Optional[int] = None
    voice: str = "denis"

class ContactImport(BaseModel):
    group_id: Optional[int] = None
    contacts: List[dict]

class BlacklistAdd(BaseModel):
    phone: str
    reason: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    role: str
    force_password_change: bool

# =============================================
# Lifespan
# =============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client, dialer_manager, rate_limiter, global_cps_limiter, cleanup_leader
    
    # Startup
    logger.info("=" * 50)
    logger.info("Starting AutoDialer Ultimate v3.0.0...")
    logger.info("=" * 50)
    
    # Database pool
    db_pool = await asyncpg.create_pool(
        user=os.getenv('DB_USER', 'autodialer'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME', 'autodialer'),
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', 5432)),
        min_size=5,
        max_size=50,
        command_timeout=60
    )
    logger.info("✅ Database connected")
    
    # Redis client
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30
    )
    await redis_client.ping()
    logger.info("✅ Redis connected")
    
    # Initialize rate limiters
    rate_limiter = SlidingWindowRateLimiter(redis_client)
    global_cps_limiter = GlobalRateLimiter(redis_client, "global_cps", rate=100)
    
    # Initialize leader election
    cleanup_leader = LeaderElection(redis_client, "leader:cleanup", ttl=120)
    
    # Import and initialize DialerManager
    from ami_manager import DialerManager
    dialer_manager = DialerManager(db_pool, redis_client)
    await dialer_manager.ensure_connected()
    
    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(graceful_shutdown()))
    
    # Start background tasks
    asyncio.create_task(cleanup_old_audio_files())
    asyncio.create_task(process_retry_queue())
    
    logger.info("=" * 50)
    logger.info("✅ AutoDialer Ultimate is ready!")
    logger.info("=" * 50)
    
    yield
    
    # Shutdown
    logger.info("Shutting down gracefully...")
    await graceful_shutdown()
    logger.info("Shutdown complete")

async def graceful_shutdown():
    """Graceful shutdown handler"""
    logger.info("Initiating graceful shutdown...")
    
    # Stop accepting new calls
    if dialer_manager:
        dialer_manager.running = False
        await redis_client.set("system_enabled", "false")
    
    # Cancel all running tasks
    await task_registry.cancel_all()
    
    # Wait for active calls to finish (max 30 seconds)
    for i in range(30):
        if dialer_manager:
            active = await redis_client.scard(dialer_manager.active_channels_key)
            if active == 0:
                break
            logger.info(f"Waiting for {active} active calls to finish... ({30-i}s)")
        await asyncio.sleep(1)
    
    # Force kill remaining calls
    if dialer_manager:
        remaining = await dialer_manager.stop_all_calls()
        if remaining > 0:
            logger.warning(f"Force killed {remaining} remaining calls")
    
    # Close connections
    if dialer_manager and dialer_manager.connected:
        await dialer_manager.manager.close()
    
    if db_pool:
        await db_pool.close()
    
    if redis_client:
        await redis_client.close()
    
    logger.info("Graceful shutdown complete")

async def cleanup_old_audio_files():
    """Background task to cleanup old audio files"""
    while True:
        await asyncio.sleep(86400)  # Once per day
        
        if await cleanup_leader.try_acquire():
            try:
                retention_days = int(os.getenv('AUDIO_RETENTION_DAYS', 30))
                logger.info(f"Cleaning up audio files older than {retention_days} days")
                
                async with db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT id, file_path FROM audio_files 
                        WHERE created_at < NOW() - INTERVAL '1 day' * $1
                        AND campaign_id IS NULL
                    """, retention_days)
                    
                    for row in rows:
                        try:
                            if os.path.exists(row['file_path']):
                                os.remove(row['file_path'])
                            await conn.execute("DELETE FROM audio_files WHERE id = $1", row['id'])
                        except Exception as e:
                            logger.error(f"Failed to cleanup audio {row['id']}: {e}")
                    
                    logger.info(f"Cleaned up {len(rows)} old audio files")
            finally:
                await cleanup_leader.release()

async def process_retry_queue():
    """Background task to process scheduled retries"""
    while True:
        await asyncio.sleep(10)
        
        if not dialer_manager or not dialer_manager.running:
            continue
        
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT cc.id, cc.campaign_id, c.phone, cc.retry_count
                    FROM campaign_contacts cc
                    JOIN contacts c ON cc.contact_id = c.id
                    WHERE cc.next_retry_at IS NOT NULL 
                    AND cc.next_retry_at <= NOW()
                    LIMIT 50
                    FOR UPDATE SKIP LOCKED
                """)
                
                for row in rows:
                    await conn.execute("""
                        UPDATE campaign_contacts 
                        SET next_retry_at = NULL
                        WHERE id = $1
                    """, row['id'])
                    
                    await dialer_manager.start_call(
                        row['phone'], 
                        row['campaign_id'], 
                        row['retry_count']
                    )
                
                if rows:
                    logger.debug(f"Processed {len(rows)} retry tasks")
        except Exception as e:
            logger.error(f"Retry queue error: {e}")

# =============================================
# FastAPI App
# =============================================
app = FastAPI(
    title="AutoDialer Ultimate API",
    version="3.0.0",
    description="Enterprise-grade auto dialer system",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================
# Middleware
# =============================================
@app.middleware("http")
async def middleware(request: Request, call_next):
    # Correlation ID
    corr_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    correlation_id_var.set(corr_id)
    
    # Rate limiting for API endpoints
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.headers.get("X-Real-IP", request.client.host)
        
        if not await rate_limiter.check(f"rate_limit:{client_ip}", limit=200):
            http_requests.labels(method=request.method, endpoint=request.url.path, status=429).inc()
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
    
    # Process request
    response = await call_next(request)
    response.headers["X-Request-ID"] = corr_id
    
    # Metrics
    http_requests.labels(
        method=request.method, 
        endpoint=request.url.path, 
        status=response.status_code
    ).inc()
    
    return response

# =============================================
# Health & Metrics
# =============================================
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    status = {"status": "healthy", "components": {}, "version": "3.0.0"}
    overall_healthy = True
    
    # Check database
    try:
        await db_breaker.call(db_pool.fetchval, "SELECT 1")
        status["components"]["database"] = "healthy"
    except Exception as e:
        status["components"]["database"] = f"unhealthy: {str(e)[:50]}"
        overall_healthy = False
    
    # Check Redis
    try:
        await redis_breaker.call(redis_client.ping)
        status["components"]["redis"] = "healthy"
    except Exception as e:
        status["components"]["redis"] = f"unhealthy: {str(e)[:50]}"
        overall_healthy = False
    
    # Check AMI
    if dialer_manager and dialer_manager.connected:
        status["components"]["ami"] = "healthy"
    else:
        status["components"]["ami"] = "unhealthy"
        overall_healthy = False
    
    # Active calls
    active = await redis_client.scard(dialer_manager.active_channels_key) if dialer_manager else 0
    status["active_calls"] = active
    status["max_calls"] = dialer_manager.max_calls if dialer_manager else 50
    
    if not overall_healthy:
        status["status"] = "degraded"
    
    return status

@app.get("/metrics")
async def metrics(_: bool = Depends(verify_metrics_auth)):
    """Prometheus metrics endpoint"""
    if dialer_manager:
        active = await redis_client.scard(dialer_manager.active_channels_key)
        active_calls_gauge.set(active)
    return Response(generate_latest(), media_type="text/plain")

# =============================================
# Auth Endpoints
# =============================================
@app.post("/api/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request):
    """User login"""
    # Rate limit check
    login_key = f"login_attempts:{req.username}"
    attempts = await redis_client.get(login_key)
    if attempts and int(attempts) >= 5:
        raise HTTPException(429, "Too many login attempts. Try again later.")
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, username, password_hash, role, force_password_change FROM users WHERE username = $1",
            req.username
        )
        
        if not user or not verify_password(req.password, user['password_hash']):
            await redis_client.incr(login_key)
            await redis_client.expire(login_key, 300)
            raise HTTPException(401, "Invalid credentials")
        
        # Clear attempts on success
        await redis_client.delete(login_key)
        
        # Update last login
        await conn.execute("UPDATE users SET last_login = NOW() WHERE id = $1", user['id'])
        
        # Create tokens
        token_data = {
            "sub": user['username'],
            "role": user['role'],
            "user_id": user['id']
        }
        
        access_token = create_token(token_data, token_type="access")
        refresh_token = create_token(token_data, expires_delta=604800, token_type="refresh")
        
        # Store refresh token in Redis
        payload = decode_token(refresh_token)
        await redis_client.setex(f"refresh:{payload['jti']}", 604800, str(user['id']))
        
        # Audit log
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details, ip_address)
            VALUES ($1, $2, $3, $4)
        """, user['id'], 'login', json.dumps({"username": req.username}), request.client.host)
        
        logger.info(f"User {req.username} logged in")
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            role=user['role'],
            force_password_change=user['force_password_change']
        )

@app.post("/api/auth/refresh")
async def refresh(request: Request):
    """Refresh access token"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing token")
    
    token = auth_header.replace("Bearer ", "")
    payload = decode_token(token)
    
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid token type")
    
    user_id = await redis_client.get(f"refresh:{payload['jti']}")
    if not user_id:
        raise HTTPException(401, "Token revoked")
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT username, role FROM users WHERE id = $1",
            int(user_id)
        )
        if not user:
            raise HTTPException(401, "User not found")
        
        token_data = {"sub": user['username'], "role": user['role'], "user_id": int(user_id)}
        access_token = create_token(token_data, token_type="access")
        
        return {"access_token": access_token}

@app.post("/api/auth/logout")
async def logout(request: Request, user: TokenData = Depends(get_current_user)):
    """User logout"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        try:
            payload = decode_token(token)
            await redis_client.delete(f"refresh:{payload['jti']}")
        except:
            pass
    
    logger.info(f"User {user.username} logged out")
    return {"status": "logged_out"}

@app.post("/api/auth/change-password")
async def change_password(req: ChangePasswordRequest, user: TokenData = Depends(get_current_user)):
    """Change user password"""
    if len(req.new_password) < 6:
        raise HTTPException(400, "Password too short (min 6 chars)")
    
    async with db_pool.acquire() as conn:
        u = await conn.fetchrow("SELECT password_hash FROM users WHERE id = $1", user.user_id)
        if not verify_password(req.old_password, u['password_hash']):
            raise HTTPException(400, "Wrong old password")
        
        await conn.execute(
            "UPDATE users SET password_hash = $1, force_password_change = FALSE WHERE id = $2",
            hash_password(req.new_password), user.user_id
        )
    
    logger.info(f"Password changed for user {user.username}")
    return {"status": "changed"}

# =============================================
# System Endpoints
# =============================================
@app.get("/api/system/status")
async def system_status(user: TokenData = Depends(get_current_user)):
    """Get system status"""
    enabled = await redis_client.get("system_enabled") or "true"
    active = await redis_client.scard(dialer_manager.active_channels_key) if dialer_manager else 0
    
    return {
        "enabled": enabled == "true",
        "active_calls": active,
        "max_calls": dialer_manager.max_calls if dialer_manager else 50,
        "ami_connected": dialer_manager.connected if dialer_manager else False,
        "tasks_running": task_registry.get_count(),
        "queue_size": await redis_client.llen("dial_queue")
    }

@app.post("/api/system/enable")
async def system_enable(admin: TokenData = Depends(require_admin)):
    """Enable the dialer system"""
    if dialer_manager:
        dialer_manager.running = True
    await redis_client.set("system_enabled", "true")
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details)
            VALUES ($1, $2, $3)
        """, admin.user_id, 'system_enable', json.dumps({}))
    
    logger.warning(f"System enabled by {admin.username}")
    return {"status": "enabled"}

@app.post("/api/system/disable")
async def system_disable(admin: TokenData = Depends(require_admin)):
    """Disable the dialer system (kill switch)"""
    if dialer_manager:
        dialer_manager.running = False
    await redis_client.set("system_enabled", "false")
    
    # Kill all active calls
    killed = 0
    if dialer_manager:
        killed = await dialer_manager.stop_all_calls()
    
    # Clear queue
    await redis_client.delete("dial_queue")
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details)
            VALUES ($1, $2, $3)
        """, admin.user_id, 'system_disable', json.dumps({"killed_calls": killed}))
    
    logger.warning(f"System disabled by {admin.username}, killed {killed} calls")
    return {"status": "disabled", "killed_calls": killed}

# =============================================
# Campaign Endpoints
# =============================================
@app.get("/api/campaigns")
async def list_campaigns(
    skip: int = 0,
    limit: int = 100,
    user: TokenData = Depends(get_current_user)
):
    """List all campaigns"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.*, 
                   COUNT(DISTINCT cc.contact_id) as total_contacts,
                   COUNT(DISTINCT cr.id) as total_calls
            FROM campaigns c
            LEFT JOIN campaign_contacts cc ON c.id = cc.campaign_id
            LEFT JOIN call_results cr ON c.id = cr.campaign_id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            OFFSET $1 LIMIT $2
        """, skip, limit)
    return [dict(r) for r in rows]

@app.post("/api/campaigns")
async def create_campaign(c: CampaignCreate, user: TokenData = Depends(get_current_user)):
    """Create a new campaign"""
    async with db_pool.acquire() as conn:
        r = await conn.fetchrow("""
            INSERT INTO campaigns (name, max_calls, cps, audio_id, retry_strategy)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """, c.name, c.max_calls, c.cps, c.audio_id, 
           json.dumps(c.retry_strategy) if c.retry_strategy else None)
        
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details)
            VALUES ($1, $2, $3)
        """, user.user_id, 'create_campaign', json.dumps({"name": c.name}))
    
    logger.info(f"Campaign created: {c.name} by {user.username}")
    return {"campaign_id": r['id']}

@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int, user: TokenData = Depends(get_current_user)):
    """Get campaign details"""
    async with db_pool.acquire() as conn:
        camp = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
        if not camp:
            raise HTTPException(404, "Campaign not found")
        
        # Get stats
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_calls,
                SUM(CASE WHEN status = 'agreed' THEN 1 ELSE 0 END) as agreed,
                SUM(CASE WHEN status = 'busy' THEN 1 ELSE 0 END) as busy,
                SUM(CASE WHEN status = 'noanswer' THEN 1 ELSE 0 END) as noanswer,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM call_results
            WHERE campaign_id = $1
        """, campaign_id)
        
        # Get contacts count
        contacts_count = await conn.fetchval("""
            SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id = $1
        """, campaign_id)
        
        return {
            "campaign": dict(camp),
            "stats": dict(stats) if stats else {},
            "contacts_count": contacts_count
        }

@app.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: int,
    bg: BackgroundTasks,
    user: TokenData = Depends(get_current_user)
):
    """Start a campaign"""
    # Check system enabled
    enabled = await redis_client.get("system_enabled") or "true"
    if enabled != "true":
        raise HTTPException(403, "System is disabled")
    
    # Idempotency lock
    lock_key = f"campaign_start_lock:{campaign_id}"
    lock = await redis_client.set(lock_key, "1", ex=60, nx=True)
    if not lock:
        raise HTTPException(400, "Campaign start already in progress")
    
    try:
        async with db_pool.acquire() as conn:
            camp = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)
            if not camp:
                raise HTTPException(404, "Campaign not found")
            if camp['status'] == 'running':
                raise HTTPException(400, "Campaign already running")
            
            # Update status atomically
            result = await conn.execute(
                "UPDATE campaigns SET status = 'running' WHERE id = $1 AND status != 'running'",
                campaign_id
            )
            if result == "UPDATE 0":
                raise HTTPException(400, "Campaign was started by another request")
            
            # Get contacts
            contacts = await conn.fetch("""
                SELECT c.phone, COALESCE(cc.retry_count, 0) as retry_count
                FROM contacts c
                JOIN campaign_contacts cc ON c.id = cc.contact_id
                WHERE cc.campaign_id = $1 AND NOT c.blacklisted
            """, campaign_id)
            
            # Get retry strategy
            retry_strategy = camp['retry_strategy'] or {"busy": 2, "noanswer": 3, "failed": 1}
            
            await conn.execute("""
                INSERT INTO audit_log (user_id, action, details)
                VALUES ($1, $2, $3)
            """, user.user_id, 'start_campaign', json.dumps({"campaign_id": campaign_id, "contacts": len(contacts)}))
        
        # Update dialer settings
        if dialer_manager:
            dialer_manager.max_calls = camp['max_calls']
            dialer_manager.cps_limiter.rate = camp['cps']
        
        # Dial function
        async def dial():
            bucket = TokenBucket(camp['cps'])
            for contact in contacts:
                # Check system status
                if not dialer_manager or not dialer_manager.running:
                    break
                
                enabled = await redis_client.get("system_enabled") or "true"
                if enabled != "true":
                    break
                
                await bucket.acquire()
                await dialer_manager.start_call(contact['phone'], campaign_id, contact['retry_count'])
            
            # Update campaign status
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE campaigns SET status = 'completed' WHERE id = $1",
                    campaign_id
                )
            
            logger.info(f"Campaign {campaign_id} completed")
        
        # Start background task
        task_id = f"campaign_{campaign_id}"
        task = asyncio.create_task(dial())
        await task_registry.register(task_id, task)
        
        logger.info(f"Campaign {campaign_id} started by {user.username}, contacts: {len(contacts)}")
        return {"status": "started", "total_contacts": len(contacts)}
    
    finally:
        await redis_client.delete(lock_key)

@app.post("/api/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: int, admin: TokenData = Depends(require_admin)):
    """Stop a running campaign (admin only)"""
    await task_registry.cancel(f"campaign_{campaign_id}")
    
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE campaigns SET status = 'stopped' WHERE id = $1",
            campaign_id
        )
        
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details)
            VALUES ($1, $2, $3)
        """, admin.user_id, 'stop_campaign', json.dumps({"campaign_id": campaign_id}))
    
    logger.info(f"Campaign {campaign_id} stopped by {admin.username}")
    return {"status": "stopped"}

@app.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, admin: TokenData = Depends(require_admin)):
    """Delete a campaign (admin only)"""
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM campaign_contacts WHERE campaign_id = $1", campaign_id)
        await conn.execute("DELETE FROM campaigns WHERE id = $1", campaign_id)
        
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details)
            VALUES ($1, $2, $3)
        """, admin.user_id, 'delete_campaign', json.dumps({"campaign_id": campaign_id}))
    
    logger.info(f"Campaign {campaign_id} deleted by {admin.username}")
    return {"status": "deleted"}

# =============================================
# Stats Endpoints
# =============================================
@app.get("/api/stats")
async def get_stats(user: TokenData = Depends(get_current_user)):
    """Get overall statistics"""
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM call_results")
        agreed = await conn.fetchval("SELECT COUNT(*) FROM call_results WHERE status = 'agreed'")
        busy = await conn.fetchval("SELECT COUNT(*) FROM call_results WHERE status = 'busy'")
        noanswer = await conn.fetchval("SELECT COUNT(*) FROM call_results WHERE status = 'noanswer'")
        failed = await conn.fetchval("SELECT COUNT(*) FROM call_results WHERE status = 'failed'")
        today = await conn.fetchval("SELECT COUNT(*) FROM call_results WHERE created_at::date = CURRENT_DATE")
        
        # Daily stats for last 7 days
        daily = await conn.fetch("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'agreed' THEN 1 ELSE 0 END) as agreed
            FROM call_results
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
    
    return {
        "total_calls": total or 0,
        "agreed": agreed or 0,
        "busy": busy or 0,
        "noanswer": noanswer or 0,
        "failed": failed or 0,
        "today_calls": today or 0,
        "conversion_rate": round(agreed / total * 100, 2) if total else 0,
        "daily": [dict(d) for d in daily]
    }

@app.get("/api/history")
async def get_history(
    skip: int = 0,
    limit: int = 100,
    campaign_id: Optional[int] = None,
    status: Optional[str] = None,
    user: TokenData = Depends(get_current_user)
):
    """Get call history"""
    async with db_pool.acquire() as conn:
        query = """
            SELECT cr.*, c.name as campaign_name, ct.phone
            FROM call_results cr
            LEFT JOIN campaigns c ON cr.campaign_id = c.id
            LEFT JOIN contacts ct ON cr.contact_id = ct.id
            WHERE 1=1
        """
        params = []
        param_idx = 1
        
        if campaign_id:
            query += f" AND cr.campaign_id = ${param_idx}"
            params.append(campaign_id)
            param_idx += 1
        
        if status:
            query += f" AND cr.status = ${param_idx}"
            params.append(status)
            param_idx += 1
        
        query += " ORDER BY cr.created_at DESC"
        query += f" LIMIT ${param_idx} OFFSET ${param_idx+1}"
        params.extend([limit, skip])
        
        rows = await conn.fetch(query, *params)
        total = await conn.fetchval("SELECT COUNT(*) FROM call_results")
    
    return {"history": [dict(r) for r in rows], "total": total}

# =============================================
# Contacts Endpoints
# =============================================
@app.get("/api/contacts")
async def list_contacts(
    skip: int = 0,
    limit: int = 100,
    user: TokenData = Depends(get_current_user)
):
    """List contacts"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM contacts 
            WHERE NOT blacklisted
            ORDER BY created_at DESC 
            OFFSET $1 LIMIT $2
        """, skip, limit)
        total = await conn.fetchval("SELECT COUNT(*) FROM contacts WHERE NOT blacklisted")
    
    return {"contacts": [dict(r) for r in rows], "total": total}

@app.post("/api/contacts/import")
async def import_contacts(
    import_data: ContactImport,
    user: TokenData = Depends(get_current_user)
):
    """Import contacts"""
    imported = 0
    skipped = 0
    
    async with db_pool.acquire() as conn:
        for contact in import_data.contacts:
            phone = contact.get('phone', '').strip()
            if not phone:
                skipped += 1
                continue
            
            # Normalize phone
            phone = re.sub(r'[^\d]', '', phone)
            if len(phone) == 11 and phone.startswith('8'):
                phone = '7' + phone[1:]
            elif len(phone) == 10 and phone.startswith('9'):
                phone = '7' + phone
            
            if not phone or len(phone) < 10:
                skipped += 1
                continue
            
            try:
                await conn.execute("""
                    INSERT INTO contacts (phone, name, group_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
                """, phone, contact.get('name', ''), import_data.group_id)
                imported += 1
            except Exception as e:
                logger.error(f"Failed to import {phone}: {e}")
                skipped += 1
    
    logger.info(f"Contacts imported by {user.username}: {imported} imported, {skipped} skipped")
    return {"imported": imported, "skipped": skipped}

# =============================================
# Blacklist Endpoints
# =============================================
@app.get("/api/blacklist")
async def list_blacklist(user: TokenData = Depends(get_current_user)):
    """List blacklisted numbers"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM blacklist ORDER BY created_at DESC")
    return [dict(r) for r in rows]

@app.post("/api/blacklist")
async def add_to_blacklist(
    data: BlacklistAdd,
    user: TokenData = Depends(get_current_user)
):
    """Add number to blacklist"""
    phone = re.sub(r'[^\d]', '', data.phone)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO blacklist (phone, reason, created_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (phone) DO NOTHING
        """, phone, data.reason, user.user_id)
        
        # Mark contact as blacklisted
        await conn.execute("UPDATE contacts SET blacklisted = TRUE WHERE phone = $1", phone)
    
    logger.info(f"Number {phone} blacklisted by {user.username}")
    return {"status": "blacklisted", "phone": phone}

@app.delete("/api/blacklist/{phone}")
async def remove_from_blacklist(phone: str, admin: TokenData = Depends(require_admin)):
    """Remove number from blacklist (admin only)"""
    phone = re.sub(r'[^\d]', '', phone)
    
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM blacklist WHERE phone = $1", phone)
        await conn.execute("UPDATE contacts SET blacklisted = FALSE WHERE phone = $1", phone)
    
    logger.info(f"Number {phone} removed from blacklist by {admin.username}")
    return {"status": "removed"}

# =============================================
# Audio Endpoints
# =============================================
@app.post("/api/audio/generate")
async def generate_audio(
    req: AudioGenerate,
    user: TokenData = Depends(get_current_user)
):
    """Generate TTS audio"""
    if len(req.text) > 500:
        raise HTTPException(400, "Text too long (max 500 chars)")
    
    # Safe filename
    safe_name = re.sub(r'[^\w\-]', '_', req.name)
    filename = f"audio_{int(datetime.now().timestamp())}_{safe_name}"
    wav_path = f"/var/lib/asterisk/sounds/tts/{filename}.wav"
    sln_path = f"/var/lib/asterisk/sounds/tts/{filename}.sln"
    
    voice = req.voice if req.voice in ['denis', 'irina'] else 'denis'
    model = f"/var/lib/asterisk/sounds/tts/models/ru_RU-{voice}-medium.onnx"
    
    try:
        # Generate TTS
        result = subprocess.run(
            ["/usr/local/bin/piper", "--model", model, "--output_file", wav_path],
            input=req.text.encode('utf-8'),
            capture_output=True,
            timeout=30
        )
        if result.returncode != 0:
            raise HTTPException(500, f"TTS generation failed: {result.stderr.decode()[:200]}")
        
        # Convert to SLN
        result = subprocess.run(
            ["/usr/bin/sox", wav_path, "-r", "8000", "-c", "1", sln_path],
            capture_output=True,
            timeout=10
        )
        if result.returncode != 0:
            raise HTTPException(500, f"Conversion failed: {result.stderr.decode()[:200]}")
        
        # Cleanup WAV
        os.remove(wav_path)
        
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "TTS generation timeout")
    
    async with db_pool.acquire() as conn:
        r = await conn.fetchrow("""
            INSERT INTO audio_files (name, file_path, campaign_id, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """, req.name, sln_path, req.campaign_id, user.user_id)
    
    logger.info(f"Audio generated: {req.name} by {user.username}")
    return {"id": r['id'], "name": req.name, "path": sln_path}

@app.get("/api/audio")
async def list_audio(user: TokenData = Depends(get_current_user)):
    """List audio files"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.*, u.username as created_by_name, c.name as campaign_name
            FROM audio_files a
            LEFT JOIN users u ON a.created_by = u.id
            LEFT JOIN campaigns c ON a.campaign_id = c.id
            ORDER BY a.created_at DESC
        """)
    return [dict(r) for r in rows]

@app.delete("/api/audio/{audio_id}")
async def delete_audio(audio_id: int, user: TokenData = Depends(get_current_user)):
    """Delete audio file"""
    async with db_pool.acquire() as conn:
        # Check ownership or admin
        if user.role != 'admin':
            audio = await conn.fetchrow(
                "SELECT * FROM audio_files WHERE id = $1 AND created_by = $2",
                audio_id, user.user_id
            )
        else:
            audio = await conn.fetchrow("SELECT * FROM audio_files WHERE id = $1", audio_id)
        
        if not audio:
            raise HTTPException(404, "Audio not found or access denied")
        
        # Delete file
        try:
            if os.path.exists(audio['file_path']):
                os.remove(audio['file_path'])
        except Exception as e:
            logger.error(f"Failed to delete audio file: {e}")
        
        await conn.execute("DELETE FROM audio_files WHERE id = $1", audio_id)
    
    logger.info(f"Audio {audio_id} deleted by {user.username}")
    return {"status": "deleted"}

# =============================================
# Users Endpoints (Admin only)
# =============================================
@app.get("/api/users")
async def list_users(
    skip: int = 0,
    limit: int = 50,
    admin: TokenData = Depends(require_admin)
):
    """List all users"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, username, role, force_password_change, last_login, created_at
            FROM users
            ORDER BY id
            OFFSET $1 LIMIT $2
        """, skip, limit)
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
    
    return {"users": [dict(r) for r in rows], "total": total}

@app.post("/api/users")
async def create_user(
    req: UserCreate,
    admin: TokenData = Depends(require_admin)
):
    """Create a new user"""
    if len(req.password) < 6:
        raise HTTPException(400, "Password too short (min 6 chars)")
    
    async with db_pool.acquire() as conn:
        try:
            r = await conn.fetchrow("""
                INSERT INTO users (username, password_hash, role)
                VALUES ($1, $2, $3)
                RETURNING id
            """, req.username, hash_password(req.password), req.role)
            
            await conn.execute("""
                INSERT INTO audit_log (user_id, action, details)
                VALUES ($1, $2, $3)
            """, admin.user_id, 'create_user', json.dumps({"username": req.username, "role": req.role}))
            
            logger.info(f"User {req.username} created by {admin.username}")
            return {"id": r['id'], "username": req.username}
        except asyncpg.UniqueViolationError:
            raise HTTPException(400, "Username already exists")

@app.put("/api/users/{user_id}")
async def update_user(
    user_id: int,
    req: UserUpdate,
    admin: TokenData = Depends(require_admin)
):
    """Update user"""
    if user_id == 1 and admin.user_id != 1:
        raise HTTPException(403, "Cannot modify default admin")
    
    async with db_pool.acquire() as conn:
        if req.password:
            if len(req.password) < 6:
                raise HTTPException(400, "Password too short")
            await conn.execute(
                "UPDATE users SET password_hash = $1, force_password_change = TRUE WHERE id = $2",
                hash_password(req.password), user_id
            )
        
        if req.role:
            await conn.execute("UPDATE users SET role = $1 WHERE id = $2", req.role, user_id)
        
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details)
            VALUES ($1, $2, $3)
        """, admin.user_id, 'update_user', json.dumps({"user_id": user_id}))
    
    logger.info(f"User {user_id} updated by {admin.username}")
    return {"status": "updated"}

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, admin: TokenData = Depends(require_admin)):
    """Delete user"""
    if user_id == 1:
        raise HTTPException(400, "Cannot delete default admin")
    
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details)
            VALUES ($1, $2, $3)
        """, admin.user_id, 'delete_user', json.dumps({"user_id": user_id}))
    
    logger.info(f"User {user_id} deleted by {admin.username}")
    return {"status": "deleted"}

# =============================================
# Settings Endpoints
# =============================================
@app.get("/api/settings")
async def get_settings(user: TokenData = Depends(get_current_user)):
    """Get system settings"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value, description FROM settings")
    return {r['key']: {"value": r['value'], "description": r['description']} for r in rows}

@app.put("/api/settings/{key}")
async def update_setting(
    key: str,
    req: SettingsUpdate,
    admin: TokenData = Depends(require_admin)
):
    """Update setting"""
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE settings SET value = $1, updated_at = NOW() WHERE key = $2
        """, req.value, key)
        
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, details)
            VALUES ($1, $2, $3)
        """, admin.user_id, 'update_setting', json.dumps({"key": key, "value": req.value}))
        
        # Apply setting immediately
        if key == 'global_max_calls' and dialer_manager:
            dialer_manager.max_calls = int(req.value)
        elif key == 'default_cps' and dialer_manager:
            dialer_manager.cps_limiter.rate = int(req.value)
    
    logger.info(f"Setting {key} updated to {req.value} by {admin.username}")
    return {"status": "updated"}

# =============================================
# Static Files
# =============================================
app.mount("/", StaticFiles(directory="/opt/autodialer/frontend/dist", html=True), name="static")
