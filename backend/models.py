"""
Database models for AutoDialer Ultimate
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class Campaign(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    status: str = "draft"
    max_calls: int = 30
    cps: int = 5
    audio_id: Optional[int] = None
    retry_strategy: Optional[Dict[str, int]] = None
    schedule_start: Optional[datetime] = None
    schedule_end: Optional[datetime] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class Contact(BaseModel):
    id: Optional[int] = None
    phone: str
    name: Optional[str] = None
    email: Optional[str] = None
    group_id: Optional[int] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    status: str = "active"
    blacklisted: bool = False
    blacklist_reason: Optional[str] = None
    created_at: Optional[datetime] = None

class ContactGroup(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    color: str = "#667eea"
    created_at: Optional[datetime] = None

class CallResult(BaseModel):
    id: Optional[int] = None
    campaign_id: Optional[int] = None
    contact_id: Optional[int] = None
    unique_id: Optional[str] = None
    linked_id: Optional[str] = None
    channel: Optional[str] = None
    caller_id: Optional[str] = None
    status: Optional[str] = None
    dtmf_result: Optional[str] = None
    duration: Optional[int] = None
    billable_seconds: Optional[int] = None
    hangup_cause: Optional[str] = None
    hangup_cause_txt: Optional[str] = None
    retry_count: int = 0
    recording_path: Optional[str] = None
    recording_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

class User(BaseModel):
    id: Optional[int] = None
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "operator"
    force_password_change: bool = True
    is_active: bool = True
    last_login: Optional[datetime] = None
    last_ip: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "operator"

class UserUpdate(BaseModel):
    password: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class Setting(BaseModel):
    key: str
    value: str
    description: Optional[str] = None
    category: str = "general"
    is_public: bool = False

class AudioFile(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    file_path: str
    file_size: Optional[int] = None
    duration: Optional[int] = None
    format: str = "sln"
    campaign_id: Optional[int] = None
    created_by: Optional[int] = None
    is_public: bool = False
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

class AuditLog(BaseModel):
    id: Optional[int] = None
    user_id: Optional[int] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: Optional[datetime] = None

class Blacklist(BaseModel):
    id: Optional[int] = None
    phone: str
    reason: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None

class ApiToken(BaseModel):
    id: Optional[int] = None
    user_id: int
    token: str
    name: Optional[str] = None
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
