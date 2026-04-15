#!/usr/bin/env python3
"""
Authentication and Authorization Module
AutoDialer Ultimate v3.0.0
"""

import os
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, Depends, Request, status
from fastapi.security import HTTPBearer, HTTPBasic, HTTPBasicCredentials, OAuth2PasswordBearer
from pydantic import BaseModel
import jwt
import secrets
import re

from logger import logger


# =============================================
# Security Configuration
# =============================================
SECRET_KEY = os.getenv('JWT_SECRET')
if not SECRET_KEY:
    raise ValueError("JWT_SECRET environment variable is required")

ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
ACCESS_TOKEN_EXPIRE = int(os.getenv('ACCESS_TOKEN_EXPIRE', 3600))  # 1 hour
REFRESH_TOKEN_EXPIRE = int(os.getenv('REFRESH_TOKEN_EXPIRE', 604800))  # 7 days

# Security schemes
security = HTTPBearer(auto_error=True)
basic_security = HTTPBasic(auto_error=True)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# =============================================
# Password Utilities
# =============================================
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    if not password:
        raise ValueError("Password cannot be empty")
    
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    if not plain_password or not hashed_password:
        return False
    
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit"
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    
    return True, None


# =============================================
# JWT Token Utilities
# =============================================
class TokenData(BaseModel):
    """Token payload data structure"""
    username: str
    role: str
    user_id: int
    exp: Optional[datetime] = None
    jti: Optional[str] = None
    type: Optional[str] = None


def create_token(
    data: Dict[str, Any],
    expires_delta: Optional[int] = None,
    token_type: str = "access"
) -> str:
    """Create a JWT token"""
    to_encode = data.copy()
    
    if expires_delta is None:
        expires_delta = ACCESS_TOKEN_EXPIRE if token_type == "access" else REFRESH_TOKEN_EXPIRE
    
    expire = datetime.utcnow() + timedelta(seconds=expires_delta)
    
    # Add standard claims
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": token_type,
        "jti": secrets.token_hex(16)
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT token"""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": True, "verify_signature": True}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_access_token(data: Dict[str, Any]) -> str:
    """Create an access token"""
    return create_token(data, ACCESS_TOKEN_EXPIRE, "access")


def create_refresh_token(data: Dict[str, Any]) -> str:
    """Create a refresh token"""
    return create_token(data, REFRESH_TOKEN_EXPIRE, "refresh")


def decode_access_token(token: str) -> TokenData:
    """Decode and validate an access token"""
    payload = decode_token(token)
    
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type, expected access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return TokenData(
        username=payload["sub"],
        role=payload["role"],
        user_id=payload["user_id"],
        exp=datetime.fromtimestamp(payload["exp"]),
        jti=payload.get("jti"),
        type=payload.get("type")
    )


def decode_refresh_token(token: str) -> TokenData:
    """Decode and validate a refresh token"""
    payload = decode_token(token)
    
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type, expected refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return TokenData(
        username=payload["sub"],
        role=payload["role"],
        user_id=payload["user_id"],
        exp=datetime.fromtimestamp(payload["exp"]),
        jti=payload.get("jti"),
        type=payload.get("type")
    )


# =============================================
# Dependency Injection for FastAPI
# =============================================
async def get_current_user(
    credentials: HTTPBearer.Depends = Depends(security)
) -> TokenData:
    """Get current authenticated user from access token"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    return decode_access_token(token)


async def get_current_user_optional(
    credentials: Optional[HTTPBearer.Depends] = Depends(security)
) -> Optional[TokenData]:
    """Get current user if authenticated, otherwise None"""
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        return decode_access_token(token)
    except HTTPException:
        return None


async def get_current_active_user(
    current_user: TokenData = Depends(get_current_user)
) -> TokenData:
    """Get current active user"""
    # Additional checks can be added here (e.g., check if user is active in DB)
    return current_user


async def require_role(required_roles: list[str]):
    """Factory for role-based access control"""
    async def role_checker(current_user: TokenData = Depends(get_current_user)):
        if current_user.role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(required_roles)}"
            )
        return current_user
    return role_checker


# Pre-defined role checkers
require_admin = require_role(["admin"])
require_operator = require_role(["admin", "operator"])
require_any_role = require_role(["admin", "operator", "viewer"])


# =============================================
# Metrics Authentication
# =============================================
def verify_metrics_auth(credentials: HTTPBasicCredentials = Depends(basic_security)) -> bool:
    """Verify credentials for metrics endpoint"""
    expected_username = os.getenv('METRICS_USER', 'admin')
    expected_password = os.getenv('METRICS_PASS', '')
    
    if not expected_password:
        logger.warning("METRICS_PASS not set, metrics endpoint is unprotected")
        return True
    
    is_correct_username = secrets.compare_digest(
        credentials.username.encode('utf-8'),
        expected_username.encode('utf-8')
    )
    is_correct_password = secrets.compare_digest(
        credentials.password.encode('utf-8'),
        expected_password.encode('utf-8')
    )
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return True


# =============================================
# API Key Authentication (for external integrations)
# =============================================
async def verify_api_key(api_key: str) -> Optional[TokenData]:
    """Verify API key and return user data"""
    # This would check against database
    # Placeholder implementation
    return None


class APIKeyHeader(HTTPBearer):
    """API Key authentication scheme"""
    def __init__(self):
        super().__init__(scheme_name="API Key", description="API Key for external access")


async def get_user_from_api_key(
    credentials: HTTPBearer.Depends = Depends(APIKeyHeader())
) -> TokenData:
    """Authenticate using API key"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )
    
    api_key = credentials.credentials
    user_data = await verify_api_key(api_key)
    
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    
    return user_data


# =============================================
# Token Blacklist (for logout)
# =============================================
class TokenBlacklist:
    """Manage blacklisted tokens (for logout)"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.prefix = "blacklist:token"
    
    async def add(self, jti: str, expires_at: datetime) -> bool:
        """Add token to blacklist"""
        ttl = int((expires_at - datetime.utcnow()).total_seconds())
        if ttl > 0:
            await self.redis.setex(f"{self.prefix}:{jti}", ttl, "1")
            return True
        return False
    
    async def is_blacklisted(self, jti: str) -> bool:
        """Check if token is blacklisted"""
        return await self.redis.exists(f"{self.prefix}:{jti}") > 0
    
    async def remove(self, jti: str) -> bool:
        """Remove token from blacklist"""
        return await self.redis.delete(f"{self.prefix}:{jti}") > 0


# =============================================
# Refresh Token Storage
# =============================================
class RefreshTokenStorage:
    """Manage refresh tokens in Redis"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.prefix = "refresh"
    
    async def store(self, jti: str, user_id: int, ttl: int = REFRESH_TOKEN_EXPIRE) -> None:
        """Store refresh token"""
        await self.redis.setex(f"{self.prefix}:{jti}", ttl, str(user_id))
    
    async def validate(self, jti: str) -> Optional[int]:
        """Validate refresh token and return user_id"""
        user_id = await self.redis.get(f"{self.prefix}:{jti}")
        if user_id:
            return int(user_id)
        return None
    
    async def revoke(self, jti: str) -> bool:
        """Revoke refresh token"""
        return await self.redis.delete(f"{self.prefix}:{jti}") > 0
    
    async def revoke_all_for_user(self, user_id: int) -> int:
        """Revoke all refresh tokens for a user"""
        # Find all tokens for user
        pattern = f"{self.prefix}:*"
        keys = await self.redis.keys(pattern)
        revoked = 0
        
        for key in keys:
            stored_user_id = await self.redis.get(key)
            if stored_user_id and int(stored_user_id) == user_id:
                await self.redis.delete(key)
                revoked += 1
        
        return revoked


# =============================================
# Login Attempt Rate Limiting
# =============================================
class LoginRateLimiter:
    """Rate limiting for login attempts"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.prefix = "login_attempts"
        self.max_attempts = 5
        self.block_duration = 300  # 5 minutes
    
    async def check(self, username: str) -> bool:
        """Check if user is rate limited"""
        key = f"{self.prefix}:{username}"
        attempts = await self.redis.get(key)
        
        if attempts and int(attempts) >= self.max_attempts:
            return False
        return True
    
    async def increment(self, username: str) -> int:
        """Increment failed attempt counter"""
        key = f"{self.prefix}:{username}"
        count = await self.redis.incr(key)
        await self.redis.expire(key, self.block_duration)
        return count
    
    async def reset(self, username: str) -> None:
        """Reset counter on successful login"""
        key = f"{self.prefix}:{username}"
        await self.redis.delete(key)
    
    async def get_remaining_attempts(self, username: str) -> int:
        """Get remaining attempts"""
        key = f"{self.prefix}:{username}"
        attempts = await self.redis.get(key)
        current = int(attempts) if attempts else 0
        return max(0, self.max_attempts - current)


# =============================================
# Session Management
# =============================================
class SessionManager:
    """Manage user sessions"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.prefix = "session"
        self.session_ttl = 3600  # 1 hour
    
    async def create(self, user_id: int, metadata: Dict[str, Any] = None) -> str:
        """Create a new session"""
        session_id = secrets.token_hex(32)
        key = f"{self.prefix}:{session_id}"
        
        data = {
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        
        await self.redis.setex(key, self.session_ttl, json.dumps(data))
        return session_id
    
    async def validate(self, session_id: str) -> Optional[int]:
        """Validate session and return user_id"""
        key = f"{self.prefix}:{session_id}"
        data = await self.redis.get(key)
        
        if data:
            session_data = json.loads(data)
            return session_data["user_id"]
        return None
    
    async def revoke(self, session_id: str) -> bool:
        """Revoke a session"""
        key = f"{self.prefix}:{session_id}"
        return await self.redis.delete(key) > 0
    
    async def extend(self, session_id: str) -> bool:
        """Extend session TTL"""
        key = f"{self.prefix}:{session_id}"
        return await self.redis.expire(key, self.session_ttl) > 0


# =============================================
# Permission Checking Utilities
# =============================================
class PermissionChecker:
    """Advanced permission checking"""
    
    @staticmethod
    def can_manage_campaigns(user: TokenData) -> bool:
        return user.role in ["admin", "operator"]
    
    @staticmethod
    def can_manage_users(user: TokenData) -> bool:
        return user.role == "admin"
    
    @staticmethod
    def can_manage_settings(user: TokenData) -> bool:
        return user.role == "admin"
    
    @staticmethod
    def can_view_stats(user: TokenData) -> bool:
        return True  # All roles can view stats
    
    @staticmethod
    def can_manage_audio(user: TokenData) -> bool:
        return user.role in ["admin", "operator"]
    
    @staticmethod
    def can_manage_contacts(user: TokenData) -> bool:
        return user.role in ["admin", "operator"]
    
    @staticmethod
    def can_start_campaign(user: TokenData) -> bool:
        return user.role in ["admin", "operator"]
    
    @staticmethod
    def can_stop_campaign(user: TokenData) -> bool:
        return user.role == "admin"
    
    @staticmethod
    def can_delete_campaign(user: TokenData) -> bool:
        return user.role == "admin"
    
    @staticmethod
    def can_manage_blacklist(user: TokenData) -> bool:
        return user.role in ["admin", "operator"]
    
    @staticmethod
    def can_enable_system(user: TokenData) -> bool:
        return user.role == "admin"
    
    @staticmethod
    def can_disable_system(user: TokenData) -> bool:
        return user.role == "admin"


# =============================================
# Audit Logging for Auth Events
# =============================================
class AuthAuditLogger:
    """Log authentication events"""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
    
    async def log_login_success(self, user_id: int, username: str, ip_address: str, user_agent: str = None):
        """Log successful login"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_log (user_id, action, entity_type, details, ip_address, user_agent)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, user_id, 'login_success', 'user', json.dumps({"username": username}), ip_address, user_agent)
        except Exception as e:
            logger.error(f"Failed to log login success: {e}")
    
    async def log_login_failure(self, username: str, ip_address: str, reason: str, user_agent: str = None):
        """Log failed login attempt"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_log (action, entity_type, details, ip_address, user_agent)
                    VALUES ($1, $2, $3, $4, $5)
                """, 'login_failure', 'user', json.dumps({"username": username, "reason": reason}), ip_address, user_agent)
        except Exception as e:
            logger.error(f"Failed to log login failure: {e}")
    
    async def log_logout(self, user_id: int, username: str, ip_address: str):
        """Log user logout"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_log (user_id, action, entity_type, details, ip_address)
                    VALUES ($1, $2, $3, $4, $5)
                """, user_id, 'logout', 'user', json.dumps({"username": username}), ip_address)
        except Exception as e:
            logger.error(f"Failed to log logout: {e}")
    
    async def log_password_change(self, user_id: int, username: str, ip_address: str):
        """Log password change"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_log (user_id, action, entity_type, details, ip_address)
                    VALUES ($1, $2, $3, $4, $5)
                """, user_id, 'password_change', 'user', json.dumps({"username": username}), ip_address)
        except Exception as e:
            logger.error(f"Failed to log password change: {e}")
    
    async def log_token_refresh(self, user_id: int, username: str, ip_address: str):
        """Log token refresh"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_log (user_id, action, entity_type, details, ip_address)
                    VALUES ($1, $2, $3, $4, $5)
                """, user_id, 'token_refresh', 'user', json.dumps({"username": username}), ip_address)
        except Exception as e:
            logger.error(f"Failed to log token refresh: {e}")


# =============================================
# Import json for audit logging
# =============================================
import json
