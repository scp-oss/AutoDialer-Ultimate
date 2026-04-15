import os
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import jwt
import secrets

security = HTTPBearer()
basic_security = HTTPBasic()

SECRET_KEY = os.getenv('JWT_SECRET', 'dev-secret-key')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = int(os.getenv('ACCESS_TOKEN_EXPIRE', 3600))
REFRESH_TOKEN_EXPIRE = int(os.getenv('REFRESH_TOKEN_EXPIRE', 604800))

class TokenData(BaseModel):
    username: str
    role: str
    user_id: int

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(data: dict, expires_delta: Optional[int] = None, token_type: str = "access") -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=expires_delta or ACCESS_TOKEN_EXPIRE)
    to_encode.update({"exp": expire, "type": token_type, "jti": secrets.token_hex(8)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

async def get_current_user(credentials: HTTPBearer.Depends = Depends(security)):
    token = credentials.credentials
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")
    return TokenData(
        username=payload["sub"],
        role=payload["role"],
        user_id=payload["user_id"]
    )

async def require_admin(user: TokenData = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user

def verify_metrics_auth(credentials: HTTPBasicCredentials = Depends(basic_security)):
    is_correct = secrets.compare_digest(credentials.username, os.getenv('METRICS_USER', 'admin')) and \
                 secrets.compare_digest(credentials.password, os.getenv('METRICS_PASS', ''))
    if not is_correct:
        raise HTTPException(401, "Invalid credentials")
    return True
