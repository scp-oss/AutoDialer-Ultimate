#!/usr/bin/env python3
"""
API Request/Response Schemas
AutoDialer Ultimate v3.0.0

Pydantic schemas for all API endpoints.
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, validator, EmailStr, ConfigDict
from enum import Enum


# =============================================
# Base Schemas
# =============================================
class BaseResponse(BaseModel):
    """Base response schema"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PaginationParams(BaseModel):
    """Pagination parameters"""
    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseModel):
    """Paginated response wrapper"""
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
    
    @classmethod
    def create(cls, items: List[Any], total: int, page: int, page_size: int):
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size
        )


class ErrorResponse(BaseModel):
    """Error response schema"""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SuccessResponse(BaseModel):
    """Success response schema"""
    success: bool = True
    message: str
    data: Optional[Any] = None


# =============================================
# Auth Schemas
# =============================================
class LoginRequest(BaseModel):
    """Login request"""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    force_password_change: bool
    user_id: int
    username: str
    expires_in: int = 3600


class RefreshTokenRequest(BaseModel):
    """Refresh token request"""
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    """Refresh token response"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class ChangePasswordRequest(BaseModel):
    """Change password request"""
    old_password: str
    new_password: str = Field(..., min_length=8)
    
    @validator('new_password')
    def validate_password(cls, v: str) -> str:
        import re
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v


class ResetPasswordRequest(BaseModel):
    """Reset password request (admin only)"""
    user_id: int
    new_password: str = Field(..., min_length=8)


class LogoutResponse(BaseModel):
    """Logout response"""
    success: bool = True
    message: str = "Logged out successfully"


# =============================================
# User Schemas
# =============================================
class UserCreateRequest(BaseModel):
    """Create user request"""
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    password: str = Field(..., min_length=8)
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=255)
    role: str = Field("operator", pattern=r'^(admin|operator|viewer)$')
    
    @validator('password')
    def validate_password(cls, v: str) -> str:
        import re
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v


class UserUpdateRequest(BaseModel):
    """Update user request"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[str] = Field(None, pattern=r'^(admin|operator|viewer)$')
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """User response"""
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool
    force_password_change: bool
    last_login: Optional[datetime] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class UserProfileResponse(BaseModel):
    """Current user profile response"""
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    permissions: List[str] = []
    last_login: Optional[datetime] = None
    created_at: datetime


# =============================================
# Campaign Schemas
# =============================================
class RetryStrategySchema(BaseModel):
    """Retry strategy configuration"""
    busy: int = Field(2, ge=0, le=10)
    busy_delay: int = Field(120, ge=30, le=3600)
    noanswer: int = Field(3, ge=0, le=10)
    noanswer_delay: int = Field(300, ge=60, le=7200)
    failed: int = Field(1, ge=0, le=5)
    failed_delay: int = Field(60, ge=30, le=1800)
    timeout: int = Field(1, ge=0, le=5)
    timeout_delay: int = Field(60, ge=30, le=1800)


class CampaignScheduleSchema(BaseModel):
    """Campaign schedule"""
    enabled: bool = False
    schedule_type: str = Field("once", pattern=r'^(once|daily|weekly|monthly|cron)$')
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    timezone: str = "UTC"
    cron_expression: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    hours: Optional[List[int]] = None


class CampaignCreateRequest(BaseModel):
    """Create campaign request"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    max_calls: int = Field(30, ge=1, le=100)
    cps: int = Field(5, ge=1, le=50)
    audio_id: Optional[int] = None
    caller_id: Optional[str] = Field(None, max_length=80)
    retry_strategy: Optional[RetryStrategySchema] = None
    schedule: Optional[CampaignScheduleSchema] = None
    contact_group_ids: Optional[List[int]] = None
    contact_ids: Optional[List[int]] = None


class CampaignUpdateRequest(BaseModel):
    """Update campaign request"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    max_calls: Optional[int] = Field(None, ge=1, le=100)
    cps: Optional[int] = Field(None, ge=1, le=50)
    audio_id: Optional[int] = None
    caller_id: Optional[str] = Field(None, max_length=80)
    retry_strategy: Optional[RetryStrategySchema] = None
    schedule: Optional[CampaignScheduleSchema] = None


class CampaignStatsResponse(BaseModel):
    """Campaign statistics"""
    total_contacts: int = 0
    called_contacts: int = 0
    remaining_contacts: int = 0
    total_calls: int = 0
    agreed: int = 0
    declined: int = 0
    busy: int = 0
    noanswer: int = 0
    failed: int = 0
    timeout: int = 0
    machine: int = 0
    conversion_rate: float = 0.0
    avg_duration: float = 0.0
    progress_percent: float = 0.0


class CampaignResponse(BaseModel):
    """Campaign response"""
    id: int
    name: str
    description: Optional[str] = None
    status: str
    max_calls: int
    cps: int
    audio_id: Optional[int] = None
    audio_name: Optional[str] = None
    caller_id: Optional[str] = None
    retry_strategy: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stats: Optional[CampaignStatsResponse] = None
    
    model_config = ConfigDict(from_attributes=True)


class CampaignDetailResponse(CampaignResponse):
    """Campaign detail response with additional info"""
    contact_groups: List[Dict[str, Any]] = []
    recent_calls: List[Dict[str, Any]] = []


# =============================================
# Contact Schemas
# =============================================
class ContactCreateRequest(BaseModel):
    """Create contact request"""
    phone: str
    name: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    group_id: Optional[int] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    
    @validator('phone')
    def validate_phone(cls, v: str) -> str:
        import re
        phone = re.sub(r'[^\d]', '', v)
        if len(phone) < 10:
            raise ValueError('Phone number must have at least 10 digits')
        if len(phone) == 11 and phone.startswith('8'):
            phone = '7' + phone[1:]
        elif len(phone) == 10 and phone.startswith('9'):
            phone = '7' + phone
        return phone


class ContactUpdateRequest(BaseModel):
    """Update contact request"""
    name: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    group_id: Optional[int] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    status: Optional[str] = Field(None, pattern=r'^(active|inactive|blocked)$')


class ContactBulkImportRequest(BaseModel):
    """Bulk import contacts request"""
    group_id: Optional[int] = None
    contacts: List[Dict[str, str]] = Field(..., min_length=1, max_length=10000)
    skip_duplicates: bool = True
    skip_blacklisted: bool = True


class ContactBulkImportResponse(BaseModel):
    """Bulk import response"""
    imported: int
    skipped: int
    duplicates: int
    blacklisted: int
    errors: List[str] = []


class ContactResponse(BaseModel):
    """Contact response"""
    id: int
    phone: str
    name: Optional[str] = None
    email: Optional[str] = None
    group_id: Optional[int] = None
    group_name: Optional[str] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    status: str
    blacklisted: bool
    last_call_at: Optional[datetime] = None
    total_calls: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


# =============================================
# Contact Group Schemas
# =============================================
class ContactGroupCreateRequest(BaseModel):
    """Create contact group request"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: str = Field("#667eea", pattern=r'^#[0-9A-Fa-f]{6}$')


class ContactGroupUpdateRequest(BaseModel):
    """Update contact group request"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')


class ContactGroupResponse(BaseModel):
    """Contact group response"""
    id: int
    name: str
    description: Optional[str] = None
    color: str
    contacts_count: int = 0
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# =============================================
# Call Result Schemas
# =============================================
class CallResultResponse(BaseModel):
    """Call result response"""
    id: int
    campaign_id: Optional[int] = None
    campaign_name: Optional[str] = None
    contact_id: Optional[int] = None
    phone: str
    contact_name: Optional[str] = None
    status: str
    dtmf_result: Optional[str] = None
    duration: Optional[int] = None
    hangup_cause: Optional[str] = None
    retry_count: int = 0
    recording_path: Optional[str] = None
    recording_url: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class CallHistoryFilter(BaseModel):
    """Call history filter"""
    campaign_id: Optional[int] = None
    status: Optional[str] = None
    phone: Optional[str] = None
    from_date: Optional[date] = None
    to_date: Optional[date] = None


# =============================================
# Statistics Schemas
# =============================================
class SystemStatsResponse(BaseModel):
    """System statistics response"""
    total_campaigns: int = 0
    active_campaigns: int = 0
    total_contacts: int = 0
    active_contacts: int = 0
    blacklisted_contacts: int = 0
    total_calls: int = 0
    calls_today: int = 0
    agreed_calls: int = 0
    declined_calls: int = 0
    conversion_rate: float = 0.0
    avg_call_duration: float = 0.0
    total_call_duration: int = 0


class DailyStatsResponse(BaseModel):
    """Daily statistics response"""
    date: str
    total_calls: int
    agreed: int
    declined: int
    busy: int
    noanswer: int
    failed: int
    conversion_rate: float


class CampaignStatsSummary(BaseModel):
    """Campaign statistics summary"""
    campaign_id: int
    campaign_name: str
    status: str
    total_calls: int
    agreed: int
    conversion_rate: float


class FullStatsResponse(BaseModel):
    """Full statistics response"""
    system: SystemStatsResponse
    daily: List[DailyStatsResponse]
    by_campaign: List[CampaignStatsSummary]
    by_status: Dict[str, int]


# =============================================
# Audio Schemas
# =============================================
class AudioGenerateRequest(BaseModel):
    """TTS generation request"""
    name: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=10, max_length=500)
    voice: str = Field("denis", pattern=r'^(denis|irina)$')
    campaign_id: Optional[int] = None
    is_public: bool = False


class AudioUploadRequest(BaseModel):
    """Audio upload request"""
    name: str = Field(..., min_length=1, max_length=255)
    campaign_id: Optional[int] = None
    is_public: bool = False


class AudioResponse(BaseModel):
    """Audio file response"""
    id: int
    name: str
    description: Optional[str] = None
    file_path: str
    file_size: Optional[int] = None
    duration: Optional[int] = None
    format: str
    campaign_id: Optional[int] = None
    campaign_name: Optional[str] = None
    is_public: bool
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    download_url: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# =============================================
# Blacklist Schemas
# =============================================
class BlacklistAddRequest(BaseModel):
    """Add to blacklist request"""
    phone: str
    reason: Optional[str] = None
    
    @validator('phone')
    def validate_phone(cls, v: str) -> str:
        import re
        return re.sub(r'[^\d]', '', v)


class BlacklistResponse(BaseModel):
    """Blacklist response"""
    id: int
    phone: str
    reason: Optional[str] = None
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# =============================================
# Settings Schemas
# =============================================
class SettingUpdateRequest(BaseModel):
    """Update setting request"""
    value: str


class SettingResponse(BaseModel):
    """Setting response"""
    key: str
    value: str
    description: Optional[str] = None
    category: str
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class SettingsBulkUpdateRequest(BaseModel):
    """Bulk update settings request"""
    settings: Dict[str, str]


# =============================================
# System Schemas
# =============================================
class SystemStatusResponse(BaseModel):
    """System status response"""
    status: str  # "healthy", "degraded", "unhealthy"
    version: str = "3.0.0"
    timestamp: datetime
    uptime_seconds: float
    enabled: bool
    active_calls: int
    max_calls: int
    queue_size: int
    components: Dict[str, Dict[str, Any]]
    
    model_config = ConfigDict(from_attributes=True)


class SystemEnableResponse(BaseModel):
    """System enable response"""
    success: bool = True
    message: str = "System enabled"
    enabled: bool = True


class SystemDisableResponse(BaseModel):
    """System disable response"""
    success: bool = True
    message: str = "System disabled"
    enabled: bool = False
    killed_calls: int = 0


# =============================================
# WebSocket Schemas
# =============================================
class WebSocketMessage(BaseModel):
    """WebSocket message"""
    type: str
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LiveCallEvent(BaseModel):
    """Live call event for WebSocket"""
    event: str  # "dial_begin", "answer", "hangup", "dtmf"
    unique_id: str
    linked_id: Optional[str] = None
    campaign_id: Optional[int] = None
    campaign_name: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    dtmf: Optional[str] = None
    duration: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CampaignProgressEvent(BaseModel):
    """Campaign progress event for WebSocket"""
    campaign_id: int
    campaign_name: str
    total_contacts: int
    called_contacts: int
    agreed: int
    declined: int
    progress_percent: float
    active_calls: int
    estimated_completion: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================
# Audit Log Schemas
# =============================================
class AuditLogResponse(BaseModel):
    """Audit log response"""
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AuditLogFilter(BaseModel):
    """Audit log filter"""
    user_id: Optional[int] = None
    action: Optional[str] = None
    entity_type: Optional[str] = None
    from_date: Optional[date] = None
    to_date: Optional[date] = None


# =============================================
# API Token Schemas
# =============================================
class ApiTokenCreateRequest(BaseModel):
    """Create API token request"""
    name: str = Field(..., min_length=1, max_length=255)
    expires_at: Optional[datetime] = None


class ApiTokenResponse(BaseModel):
    """API token response (with token - only shown once)"""
    id: int
    name: str
    token: str
    expires_at: Optional[datetime] = None
    created_at: datetime


class ApiTokenListItem(BaseModel):
    """API token list item (without token)"""
    id: int
    name: str
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    is_expired: bool


# =============================================
# Health Check Schemas
# =============================================
class HealthCheckResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    timestamp: datetime
    components: Dict[str, Dict[str, Any]]
    active_calls: int = 0
    max_calls: int = 50


# =============================================
# Incoming Call Schemas (НОВОЕ)
# =============================================
class IncomingCallResponse(BaseModel):
    """Incoming call response"""
    id: int
    caller_number: str
    recording_path: str
    transcription: Optional[str] = None
    transcription_status: str
    duration: Optional[int] = None
    file_size: Optional[int] = None
    call_date: datetime
    listened: bool
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


class IncomingCallDetailResponse(IncomingCallResponse):
    """Incoming call detail response"""
    recording_url: Optional[str] = None


class IncomingCallUpdateRequest(BaseModel):
    """Update incoming call request"""
    notes: Optional[str] = None
    listened: Optional[bool] = None


class IncomingCallStatsResponse(BaseModel):
    """Incoming calls statistics"""
    total: int = 0
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    avg_duration: float = 0.0
    total_duration: int = 0


class IncomingCallWebhookRequest(BaseModel):
    """Webhook request from Asterisk for incoming call"""
    caller_number: str
    recording_path: str
    duration: Optional[int] = None
    file_size: Optional[int] = None
