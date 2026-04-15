#!/usr/bin/env python3
"""
Database Models and Pydantic Schemas
AutoDialer Ultimate v3.0.0
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from enum import Enum
from pydantic import BaseModel, Field, validator, EmailStr, ConfigDict
import re
import json


# =============================================
# Enums
# =============================================
class CampaignStatus(str, Enum):
    """Campaign status enum"""
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
    SCHEDULED = "scheduled"


class ContactStatus(str, Enum):
    """Contact status enum"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    BLACKLISTED = "blacklisted"


class CallResultStatus(str, Enum):
    """Call result status enum"""
    AGREED = "agreed"
    DECLINED = "declined"
    BUSY = "busy"
    NOANSWER = "noanswer"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELED = "canceled"
    MACHINE = "machine"


class UserRole(str, Enum):
    """User role enum"""
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AudioFormat(str, Enum):
    """Audio format enum"""
    SLN = "sln"
    WAV = "wav"
    MP3 = "mp3"
    GSM = "gsm"


class ScheduleType(str, Enum):
    """Schedule type enum"""
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CRON = "cron"


# =============================================
# Base Model
# =============================================
class BaseSchema(BaseModel):
    """Base schema with common configuration"""
    
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore"
    )


class TimestampSchema(BaseSchema):
    """Schema with timestamp fields"""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# =============================================
# Campaign Models
# =============================================
class RetryStrategy(BaseModel):
    """Retry strategy configuration"""
    busy: int = Field(2, ge=0, le=10, description="Max retries for busy")
    noanswer: int = Field(3, ge=0, le=10, description="Max retries for no answer")
    failed: int = Field(1, ge=0, le=5, description="Max retries for failed")
    timeout: int = Field(1, ge=0, le=5, description="Max retries for timeout")
    
    # Delays in seconds
    busy_delay: int = Field(120, ge=30, le=3600)
    noanswer_delay: int = Field(300, ge=60, le=7200)
    failed_delay: int = Field(60, ge=30, le=1800)
    timeout_delay: int = Field(60, ge=30, le=1800)


class CampaignSchedule(BaseModel):
    """Campaign schedule configuration"""
    enabled: bool = False
    schedule_type: ScheduleType = ScheduleType.ONCE
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    timezone: str = "UTC"
    cron_expression: Optional[str] = None
    days_of_week: Optional[List[int]] = None  # 0-6, Monday=0
    hours: Optional[List[int]] = None  # 0-23
    minutes: Optional[List[int]] = None  # 0-59


class CampaignBase(BaseSchema):
    """Base campaign schema"""
    name: str = Field(..., min_length=1, max_length=255, description="Campaign name")
    description: Optional[str] = Field(None, max_length=1000)
    max_calls: int = Field(30, ge=1, le=100, description="Maximum concurrent calls")
    cps: int = Field(5, ge=1, le=50, description="Calls per second")
    audio_id: Optional[int] = Field(None, description="Default audio file ID")
    caller_id: Optional[str] = Field(None, max_length=80, description="Caller ID")
    retry_strategy: Optional[RetryStrategy] = None
    schedule: Optional[CampaignSchedule] = None
    metadata: Optional[Dict[str, Any]] = None


class CampaignCreate(CampaignBase):
    """Schema for creating a campaign"""
    pass


class CampaignUpdate(BaseSchema):
    """Schema for updating a campaign"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    max_calls: Optional[int] = Field(None, ge=1, le=100)
    cps: Optional[int] = Field(None, ge=1, le=50)
    audio_id: Optional[int] = None
    caller_id: Optional[str] = Field(None, max_length=80)
    retry_strategy: Optional[RetryStrategy] = None
    schedule: Optional[CampaignSchedule] = None
    metadata: Optional[Dict[str, Any]] = None


class CampaignStats(BaseModel):
    """Campaign statistics"""
    total_contacts: int = 0
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
    total_duration: int = 0
    remaining_contacts: int = 0
    estimated_completion: Optional[datetime] = None


class CampaignResponse(CampaignBase, TimestampSchema):
    """Schema for campaign response"""
    id: int
    status: CampaignStatus = CampaignStatus.DRAFT
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    stats: Optional[CampaignStats] = None
    audio_name: Optional[str] = None


class CampaignListResponse(BaseSchema):
    """Schema for paginated campaign list"""
    items: List[CampaignResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================
# Contact Models
# =============================================
class ContactBase(BaseSchema):
    """Base contact schema"""
    phone: str = Field(..., description="Phone number")
    name: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    group_id: Optional[int] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    
    @validator('phone')
    def validate_phone(cls, v: str) -> str:
        """Validate and normalize phone number"""
        # Remove all non-digits
        phone = re.sub(r'[^\d]', '', v)
        
        if len(phone) < 10:
            raise ValueError('Phone number must have at least 10 digits')
        
        # Normalize Russian numbers
        if len(phone) == 11 and phone.startswith('8'):
            phone = '7' + phone[1:]
        elif len(phone) == 10 and phone.startswith('9'):
            phone = '7' + phone
        
        return phone


class ContactCreate(ContactBase):
    """Schema for creating a contact"""
    pass


class ContactUpdate(BaseSchema):
    """Schema for updating a contact"""
    name: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    group_id: Optional[int] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    status: Optional[ContactStatus] = None


class ContactResponse(ContactBase, TimestampSchema):
    """Schema for contact response"""
    id: int
    status: ContactStatus = ContactStatus.ACTIVE
    blacklisted: bool = False
    blacklist_reason: Optional[str] = None
    last_call_at: Optional[datetime] = None
    total_calls: int = 0
    group_name: Optional[str] = None


class ContactImportRequest(BaseSchema):
    """Schema for bulk contact import"""
    group_id: Optional[int] = None
    contacts: List[Dict[str, str]] = Field(..., min_length=1, max_length=10000)
    skip_duplicates: bool = True
    skip_blacklisted: bool = True


class ContactImportResponse(BaseSchema):
    """Schema for contact import response"""
    imported: int
    skipped: int
    duplicates: int
    blacklisted: int
    errors: List[str] = []


class ContactListResponse(BaseSchema):
    """Schema for paginated contact list"""
    items: List[ContactResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================
# Contact Group Models
# =============================================
class ContactGroupBase(BaseSchema):
    """Base contact group schema"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: str = Field("#667eea", pattern=r'^#[0-9A-Fa-f]{6}$')


class ContactGroupCreate(ContactGroupBase):
    """Schema for creating a contact group"""
    pass


class ContactGroupUpdate(BaseSchema):
    """Schema for updating a contact group"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')


class ContactGroupResponse(ContactGroupBase, TimestampSchema):
    """Schema for contact group response"""
    id: int
    contacts_count: int = 0
    created_by: Optional[int] = None


# =============================================
# Call Result Models
# =============================================
class CallResultBase(BaseSchema):
    """Base call result schema"""
    campaign_id: Optional[int] = None
    contact_id: Optional[int] = None
    phone: str
    status: CallResultStatus
    dtmf_result: Optional[str] = Field(None, max_length=10)
    duration: Optional[int] = Field(None, ge=0, description="Call duration in seconds")
    billable_seconds: Optional[int] = Field(None, ge=0)
    hangup_cause: Optional[str] = None
    hangup_cause_code: Optional[int] = None
    retry_count: int = 0
    recording_path: Optional[str] = None
    recording_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CallResultCreate(CallResultBase):
    """Schema for creating a call result"""
    unique_id: Optional[str] = None
    linked_id: Optional[str] = None
    channel: Optional[str] = None
    caller_id: Optional[str] = None


class CallResultResponse(CallResultBase, TimestampSchema):
    """Schema for call result response"""
    id: int
    unique_id: Optional[str] = None
    linked_id: Optional[str] = None
    campaign_name: Optional[str] = None
    contact_name: Optional[str] = None


class CallResultListResponse(BaseSchema):
    """Schema for paginated call result list"""
    items: List[CallResultResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================
# User Models
# =============================================
class UserBase(BaseSchema):
    """Base user schema"""
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=255)
    role: UserRole = UserRole.OPERATOR


class UserCreate(UserBase):
    """Schema for creating a user"""
    password: str = Field(..., min_length=8)
    
    @validator('password')
    def validate_password(cls, v: str) -> str:
        """Validate password strength"""
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v


class UserUpdate(BaseSchema):
    """Schema for updating a user"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserPasswordChange(BaseSchema):
    """Schema for changing password"""
    old_password: str
    new_password: str = Field(..., min_length=8)
    
    @validator('new_password')
    def validate_password(cls, v: str) -> str:
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v


class UserResponse(UserBase, TimestampSchema):
    """Schema for user response"""
    id: int
    is_active: bool = True
    force_password_change: bool = True
    last_login: Optional[datetime] = None
    last_ip: Optional[str] = None


class UserListResponse(BaseSchema):
    """Schema for paginated user list"""
    items: List[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================
# Settings Models
# =============================================
class SettingBase(BaseSchema):
    """Base setting schema"""
    key: str = Field(..., min_length=1, max_length=100)
    value: str
    description: Optional[str] = None
    category: str = "general"


class SettingCreate(SettingBase):
    """Schema for creating a setting"""
    pass


class SettingUpdate(BaseSchema):
    """Schema for updating a setting"""
    value: str


class SettingResponse(SettingBase, TimestampSchema):
    """Schema for setting response"""
    updated_by: Optional[int] = None
    updated_by_name: Optional[str] = None


class SettingsBulkUpdate(BaseSchema):
    """Schema for bulk updating settings"""
    settings: Dict[str, str]


# =============================================
# Audio File Models
# =============================================
class AudioFileBase(BaseSchema):
    """Base audio file schema"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    campaign_id: Optional[int] = None
    is_public: bool = False
    metadata: Optional[Dict[str, Any]] = None


class AudioFileCreate(AudioFileBase):
    """Schema for creating an audio file"""
    pass


class AudioFileUpdate(BaseSchema):
    """Schema for updating an audio file"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    campaign_id: Optional[int] = None
    is_public: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class AudioFileResponse(AudioFileBase, TimestampSchema):
    """Schema for audio file response"""
    id: int
    file_path: str
    file_size: Optional[int] = None
    duration: Optional[int] = None
    format: AudioFormat = AudioFormat.SLN
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    campaign_name: Optional[str] = None
    download_url: Optional[str] = None


class AudioGenerateRequest(BaseSchema):
    """Schema for TTS generation request"""
    name: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=10, max_length=500)
    voice: str = "denis"
    campaign_id: Optional[int] = None
    is_public: bool = False
    
    @validator('voice')
    def validate_voice(cls, v: str) -> str:
        allowed = ['denis', 'irina']
        if v not in allowed:
            raise ValueError(f"Voice must be one of: {', '.join(allowed)}")
        return v


class AudioGenerateResponse(BaseSchema):
    """Schema for TTS generation response"""
    id: int
    name: str
    file_path: str
    file_size: int
    duration: Optional[int] = None


# =============================================
# Blacklist Models
# =============================================
class BlacklistBase(BaseSchema):
    """Base blacklist schema"""
    phone: str
    reason: Optional[str] = None
    
    @validator('phone')
    def validate_phone(cls, v: str) -> str:
        return re.sub(r'[^\d]', '', v)


class BlacklistCreate(BlacklistBase):
    """Schema for creating a blacklist entry"""
    pass


class BlacklistResponse(BlacklistBase, TimestampSchema):
    """Schema for blacklist response"""
    id: int
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None


class BlacklistListResponse(BaseSchema):
    """Schema for paginated blacklist"""
    items: List[BlacklistResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================
# Audit Log Models
# =============================================
class AuditLogBase(BaseSchema):
    """Base audit log schema"""
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogResponse(AuditLogBase, TimestampSchema):
    """Schema for audit log response"""
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None


class AuditLogListResponse(BaseSchema):
    """Schema for paginated audit log"""
    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================
# Statistics Models
# =============================================
class SystemStats(BaseModel):
    """System-wide statistics"""
    total_campaigns: int = 0
    active_campaigns: int = 0
    total_contacts: int = 0
    active_contacts: int = 0
    blacklisted_contacts: int = 0
    total_calls: int = 0
    calls_today: int = 0
    agreed_calls: int = 0
    conversion_rate: float = 0.0
    avg_call_duration: float = 0.0
    total_call_duration: int = 0


class DailyStats(BaseModel):
    """Daily statistics"""
    date: str
    total_calls: int = 0
    agreed: int = 0
    declined: int = 0
    busy: int = 0
    noanswer: int = 0
    failed: int = 0
    conversion_rate: float = 0.0
    avg_duration: float = 0.0


class CampaignStatsResponse(BaseModel):
    """Full statistics response"""
    system: SystemStats
    daily: List[DailyStats]
    by_campaign: List[Dict[str, Any]]
    by_status: Dict[str, int]


# =============================================
# System Status Models
# =============================================
class ComponentStatus(BaseModel):
    """Component health status"""
    status: str  # "healthy", "degraded", "unhealthy"
    message: Optional[str] = None
    latency_ms: Optional[float] = None


class SystemStatusResponse(BaseModel):
    """System status response"""
    status: str  # "healthy", "degraded", "unhealthy"
    version: str = "3.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    uptime_seconds: float
    components: Dict[str, ComponentStatus]
    active_calls: int = 0
    max_calls: int = 50
    queue_size: int = 0


# =============================================
# API Token Models
# =============================================
class ApiTokenCreate(BaseSchema):
    """Schema for creating an API token"""
    name: str = Field(..., min_length=1, max_length=255)
    expires_at: Optional[datetime] = None


class ApiTokenResponse(BaseSchema):
    """Schema for API token response"""
    id: int
    name: str
    token: str  # Only shown once on creation
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime


class ApiTokenListResponse(BaseSchema):
    """Schema for API token list (without actual tokens)"""
    id: int
    name: str
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    is_expired: bool


# =============================================
# WebSocket Models
# =============================================
class WebSocketMessage(BaseModel):
    """WebSocket message schema"""
    type: str
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LiveCallUpdate(BaseModel):
    """Live call update for WebSocket"""
    event: str  # "dial_begin", "answer", "hangup", "dtmf"
    unique_id: str
    linked_id: Optional[str] = None
    campaign_id: Optional[int] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    dtmf: Optional[str] = None
    duration: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CampaignProgressUpdate(BaseModel):
    """Campaign progress update for WebSocket"""
    campaign_id: int
    campaign_name: str
    total_contacts: int
    called_contacts: int
    agreed: int
    declined: int
    progress_percent: float
    active_calls: int
    estimated_completion: Optional[datetime] = None


# =============================================
# Utility Functions
# =============================================
def model_to_dict(model: BaseModel, exclude_none: bool = True) -> Dict[str, Any]:
    """Convert Pydantic model to dictionary"""
    return model.model_dump(exclude_none=exclude_none)


def dict_to_model(data: Dict[str, Any], model_class: type) -> BaseModel:
    """Convert dictionary to Pydantic model"""
    return model_class(**data)


def parse_json_field(value: Union[str, Dict, List]) -> Any:
    """Parse a JSON field from database"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value
