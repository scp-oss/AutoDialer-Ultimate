"""
Pydantic schemas for API requests/responses
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import re

# =============================================
# Auth Schemas
# =============================================
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    force_password_change: bool

class RefreshRequest(BaseModel):
    refresh_token: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)
    
    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v

# =============================================
# Campaign Schemas
# =============================================
class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    max_calls: int = Field(30, ge=1, le=100)
    cps: int = Field(5, ge=1, le=50)
    audio_id: Optional[int] = None
    retry_strategy: Optional[Dict[str, int]] = None
    schedule_start: Optional[datetime] = None
    schedule_end: Optional[datetime] = None

class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    max_calls: Optional[int] = Field(None, ge=1, le=100)
    cps: Optional[int] = Field(None, ge=1, le=50)
    audio_id: Optional[int] = None
    retry_strategy: Optional[Dict[str, int]] = None
    schedule_start: Optional[datetime] = None
    schedule_end: Optional[datetime] = None

class CampaignResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    status: str
    max_calls: int
    cps: int
    audio_id: Optional[int]
    retry_strategy: Optional[Dict[str, int]]
    schedule_start: Optional[datetime]
    schedule_end: Optional[datetime]
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime

# =============================================
# Contact Schemas
# =============================================
class ContactCreate(BaseModel):
    phone: str
    name: Optional[str] = None
    email: Optional[str] = None
    group_id: Optional[int] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    
    @validator('phone')
    def validate_phone(cls, v):
        phone = re.sub(r'[^\d]', '', v)
        if len(phone) < 10:
            raise ValueError('Invalid phone number')
        return phone

class ContactImport(BaseModel):
    group_id: Optional[int] = None
    contacts: List[Dict[str, str]]

class ContactResponse(BaseModel):
    id: int
    phone: str
    name: Optional[str]
    email: Optional[str]
    group_id: Optional[int]
    tags: Optional[List[str]]
    custom_fields: Optional[Dict[str, Any]]
    status: str
    blacklisted: bool
    created_at: datetime

# =============================================
# Contact Group Schemas
# =============================================
class ContactGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: str = "#667eea"

class ContactGroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    color: str
    created_at: datetime

# =============================================
# User Schemas
# =============================================
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "operator"
    
    @validator('role')
    def validate_role(cls, v):
        if v not in ['admin', 'operator', 'viewer']:
            raise ValueError('Invalid role')
        return v

class UserUpdate(BaseModel):
    password: Optional[str] = Field(None, min_length=6)
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    full_name: Optional[str]
    role: str
    force_password_change: bool
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime

# =============================================
# Settings Schemas
# =============================================
class SettingUpdate(BaseModel):
    value: str

class SettingResponse(BaseModel):
    key: str
    value: str
    description: Optional[str]
    category: str
    is_public: bool

# =============================================
# Audio Schemas
# =============================================
class AudioGenerate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=10, max_length=500)
    voice: str = "denis"
    campaign_id: Optional[int] = None
    
    @validator('voice')
    def validate_voice(cls, v):
        if v not in ['denis', 'irina']:
            raise ValueError('Invalid voice')
        return v

class AudioResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    file_path: str
    file_size: Optional[int]
    duration: Optional[int]
    format: str
    campaign_id: Optional[int]
    campaign_name: Optional[str]
    created_by: Optional[int]
    created_by_name: Optional[str]
    is_public: bool
    created_at: datetime

# =============================================
# Statistics Schemas
# =============================================
class StatsResponse(BaseModel):
    total_calls: int
    agreed: int
    busy: int
    noanswer: int
    failed: int
    timeout: int
    today_calls: int
    conversion_rate: float
    daily: List[Dict[str, Any]]

class SystemStatusResponse(BaseModel):
    enabled: bool
    active_calls: int
    max_calls: int
    ami_connected: bool
    tasks_running: int
    queue_size: int
    redis_connected: bool
    database_connected: bool

# =============================================
# Blacklist Schemas
# =============================================
class BlacklistAdd(BaseModel):
    phone: str
    reason: Optional[str] = None
    
    @validator('phone')
    def validate_phone(cls, v):
        return re.sub(r'[^\d]', '', v)

class BlacklistResponse(BaseModel):
    id: int
    phone: str
    reason: Optional[str]
    created_by: Optional[int]
    created_at: datetime

# =============================================
# Audit Log Schemas
# =============================================
class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    username: Optional[str]
    action: str
    entity_type: Optional[str]
    entity_id: Optional[int]
    details: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    created_at: datetime

# =============================================
# Pagination
# =============================================
class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
