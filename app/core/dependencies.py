#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Зависимости FastAPI
AutoDialer Ultimate v3.0.0

Предоставляет:
- Зависимости для аутентификации (get_current_user, require_admin, etc.)
- Зависимости для получения ресурсов (БД, Redis, Dialer)
- Rate limiting зависимости
- Зависимости для пагинации и фильтрации
- Зависимости для фоновых задач

ИСПОЛЬЗОВАНИЕ:
    from app.core.dependencies import get_current_user, require_admin, get_db_pool
    
    @router.get("/protected")
    async def protected_route(user: TokenData = Depends(get_current_user)):
        ...
"""

import asyncio
import time
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps

from fastapi import Depends, HTTPException, status, Request, Query, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from fastapi.security.utils import get_authorization_scheme_param

from app.core.config import settings
from app.core.logger import logger, get_correlation_id
from app.core.security import (
    decode_token, verify_token, TokenExpiredError, TokenInvalidError,
    verify_api_key, hash_api_key
)
from app.core.database import get_db_pool as _get_db_pool, ConnectionPool
from app.core.redis import get_redis_client as _get_redis_client, RedisClient

# Импорт утилит
from app.utils.rate_limiter import SlidingWindowRateLimiter, RateLimitExceeded
from app.utils.task_registry import TaskRegistry, get_task_registry as _get_task_registry


# =============================================
# Схемы аутентификации
# =============================================
class OAuth2PasswordBearerWithCookie(HTTPBearer):
    """
    OAuth2 с поддержкой cookie.
    Используется для веб-интерфейса.
    """
    
    def __init__(
        self,
        token_url: str = "/api/auth/login",
        scheme_name: str = "Bearer",
        auto_error: bool = True
    ):
        super().__init__(
            scheme_name=scheme_name,
            auto_error=auto_error,
            bearerFormat="JWT"
        )
        self.token_url = token_url
    
    async def __call__(self, request: Request) -> Optional[str]:
        # Сначала проверяем заголовок Authorization
        authorization = request.headers.get("Authorization")
        scheme, param = get_authorization_scheme_param(authorization)
        
        if scheme.lower() == "bearer":
            return param
        
        # Затем проверяем cookie
        cookie_token = request.cookies.get("access_token")
        if cookie_token:
            # Убираем префикс Bearer если есть
            if cookie_token.startswith("Bearer "):
                cookie_token = cookie_token[7:]
            return cookie_token
        
        if self.auto_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": f"Bearer realm=\"{self.token_url}\""}
            )
        
        return None


# Схемы аутентификации
oauth2_scheme = HTTPBearer(auto_error=False)
oauth2_cookie_scheme = OAuth2PasswordBearerWithCookie(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# =============================================
# Модели данных токена
# =============================================
@dataclass
class TokenData:
    """Данные пользователя из токена"""
    user_id: int
    username: str
    role: str
    permissions: List[str] = field(default_factory=list)
    campaign_id: Optional[int] = None
    session_id: Optional[str] = None
    token_jti: Optional[str] = None
    token_type: Optional[str] = None
    expires_at: Optional[datetime] = None
    
    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
    
    @property
    def is_operator(self) -> bool:
        return self.role in ("admin", "operator")
    
    @property
    def is_viewer(self) -> bool:
        return self.role in ("admin", "operator", "viewer")
    
    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or self.is_admin


@dataclass
class ApiKeyData:
    """Данные API ключа"""
    key_id: int
    name: str
    user_id: Optional[int]
    permissions: List[str]
    expires_at: Optional[datetime]
    
    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at


# =============================================
# Зависимости аутентификации
# =============================================
async def get_token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
    cookie_token: Optional[str] = Depends(oauth2_cookie_scheme),
    api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> Optional[str]:
    """
    Получить токен из разных источников.
    Приоритет: API Key > Authorization Header > Cookie
    """
    # API Key имеет наивысший приоритет
    if api_key:
        return api_key
    
    # Затем Bearer токен
    if credentials:
        return credentials.credentials
    
    # Затем cookie
    if cookie_token:
        return cookie_token
    
    return None


async def get_current_user_optional(
    token: Optional[str] = Depends(get_token_from_request),
) -> Optional[TokenData]:
    """
    Получить текущего пользователя (опционально).
    Не выбрасывает исключение если пользователь не аутентифицирован.
    """
    if not token:
        return None
    
    # Проверяем, является ли токен API ключом
    if token.startswith(('ak_', 'api_')):
        return await _verify_api_key(token)
    
    # JWT токен
    return await _verify_jwt_token(token)


async def get_current_user(
    token: Optional[str] = Depends(get_token_from_request),
) -> TokenData:
    """
    Получить текущего пользователя (обязательно).
    Выбрасывает 401 если пользователь не аутентифицирован.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Проверяем, является ли токен API ключом
    if token.startswith(('ak_', 'api_')):
        user = await _verify_api_key(token)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key"
            )
        return user
    
    # JWT токен
    user = await _verify_jwt_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Проверяем, не отозван ли refresh токен
    if user.token_type == "refresh":
        redis_client = _get_redis_client()
        jti = user.token_jti
        if jti and not await redis_client.exists(f"refresh:{jti}"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token revoked"
            )
    
    # Проверяем, активен ли пользователь
    db_pool = _get_db_pool()
    async with db_pool.acquire() as conn:
        db_user = await conn.fetchrow(
            "SELECT is_active FROM users WHERE id = $1",
            user.user_id
        )
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        if not db_user['is_active']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled"
            )
    
    return user


async def _verify_jwt_token(token: str) -> Optional[TokenData]:
    """Проверить JWT токен"""
    try:
        payload = decode_token(token)
        
        return TokenData(
            user_id=payload.get("user_id"),
            username=payload.get("sub"),
            role=payload.get("role", "viewer"),
            permissions=payload.get("permissions", []),
            campaign_id=payload.get("campaign_id"),
            session_id=payload.get("session_id"),
            token_jti=payload.get("jti"),
            token_type=payload.get("type"),
            expires_at=datetime.fromtimestamp(payload.get("exp")) if payload.get("exp") else None
        )
    except TokenExpiredError:
        return None
    except TokenInvalidError:
        return None
    except Exception as e:
        logger.error(f"JWT verification error: {e}")
        return None


async def _verify_api_key(api_key: str) -> Optional[TokenData]:
    """Проверить API ключ"""
    db_pool = _get_db_pool()
    
    # Хешируем ключ для поиска в БД
    key_hash = hash_api_key(api_key)
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                ak.id, ak.name, ak.user_id, ak.permissions, ak.expires_at,
                ak.last_used_at, u.username, u.role, u.is_active
            FROM api_keys ak
            LEFT JOIN users u ON ak.user_id = u.id
            WHERE ak.key_hash = $1 AND ak.is_active = TRUE
        """, key_hash)
        
        if not row:
            return None
        
        # Проверяем срок действия
        if row['expires_at'] and row['expires_at'] < datetime.utcnow():
            return None
        
        # Проверяем, активен ли пользователь (если ключ привязан к пользователю)
        if row['user_id'] and not row['is_active']:
            return None
        
        # Обновляем last_used_at
        await conn.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1",
            row['id']
        )
        
        # Возвращаем данные
        if row['user_id']:
            return TokenData(
                user_id=row['user_id'],
                username=row['username'] or f"api_key_{row['id']}",
                role=row['role'] or "api",
                permissions=row['permissions'] or [],
            )
        else:
            return TokenData(
                user_id=0,
                username=f"api_key_{row['id']}",
                role="api",
                permissions=row['permissions'] or [],
            )


async def get_current_active_user(
    user: TokenData = Depends(get_current_user)
) -> TokenData:
    """
    Получить текущего активного пользователя.
    Дополнительно проверяет, что пользователь активен.
    """
    # Проверка уже выполнена в get_current_user
    return user


async def require_admin(
    user: TokenData = Depends(get_current_user)
) -> TokenData:
    """
    Требовать роль admin.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return user


async def require_operator(
    user: TokenData = Depends(get_current_user)
) -> TokenData:
    """
    Требовать роль operator или admin.
    """
    if not user.is_operator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator privileges required"
        )
    return user


async def require_viewer(
    user: TokenData = Depends(get_current_user)
) -> TokenData:
    """
    Требовать роль viewer или выше.
    """
    if not user.is_viewer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Viewer privileges required"
        )
    return user


def require_permission(permission: str):
    """
    Фабрика зависимостей для проверки конкретного разрешения.
    
    Использование:
        @router.post("/something")
        async def something(user: TokenData = Depends(require_permission("campaigns:create"))):
            ...
    """
    async def dependency(user: TokenData = Depends(get_current_user)) -> TokenData:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required"
            )
        return user
    
    return dependency


# =============================================
# Зависимости для метрик и вебхуков
# =============================================
async def verify_metrics_auth(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> bool:
    """
    Проверка аутентификации для /metrics эндпоинта.
    Поддерживает Basic Auth и Bearer токен.
    """
    # Если метрики отключены
    if not settings.METRICS_ENABLED:
        return False
    
    # В development режиме можно без аутентификации
    if settings.DEBUG:
        return True
    
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
            detail="Authentication required"
        )
    
    # Basic Auth
    if authorization.startswith("Basic "):
        import base64
        try:
            encoded = authorization[6:]
            decoded = base64.b64decode(encoded).decode()
            username, password = decoded.split(":", 1)
            
            # Проверяем через переменные окружения
            metrics_user = getattr(settings, 'METRICS_USER', 'admin')
            metrics_password = getattr(settings, 'METRICS_PASSWORD', '')
            
            if username == metrics_user and metrics_password and password == metrics_password:
                return True
        except Exception:
            pass
    
    # Bearer токен (только admin)
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        user = await _verify_jwt_token(token)
        if user and user.is_admin:
            return True
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Basic"},
        detail="Invalid credentials"
    )


async def verify_webhook_auth(
    request: Request,
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token"),
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature")
) -> bool:
    """
    Проверка подписи вебхука.
    Используется для входящих уведомлений от Asterisk.
    """
    webhook_secret = getattr(settings, 'WEBHOOK_SECRET', '')
    
    if not webhook_secret:
        logger.warning("WEBHOOK_SECRET not set, webhook authentication disabled")
        return True
    
    # Проверка по токену
    if x_webhook_token and x_webhook_token == webhook_secret:
        return True
    
    # Проверка по HMAC подписи
    if x_webhook_signature:
        import hmac
        import hashlib
        
        body = await request.body()
        expected = hmac.new(
            webhook_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if hmac.compare_digest(x_webhook_signature, expected):
            return True
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid webhook signature"
    )


# =============================================
# Зависимости для ресурсов
# =============================================
def get_db_pool() -> ConnectionPool:
    """Получить пул соединений с БД"""
    return _get_db_pool()


def get_redis_client() -> RedisClient:
    """Получить клиент Redis"""
    return _get_redis_client()


def get_task_registry() -> TaskRegistry:
    """Получить реестр задач"""
    return _get_task_registry()


async def get_dialer_manager():
    """Получить менеджер дозвона (ленивая загрузка)"""
    from app.services.dialer import get_dialer_manager as _get_dialer
    return _get_dialer()


async def get_transcription_service():
    """Получить сервис транскрибации (ленивая загрузка)"""
    from app.services.transcription import get_transcription_service as _get_transcription
    return _get_transcription()


# =============================================
# Rate Limiting
# =============================================
class RateLimiter:
    """
    Зависимость для ограничения частоты запросов.
    
    Использование:
        @router.post("/action")
        async def action(limiter: RateLimiter = Depends()):
            await limiter.check("action", limit=10, window=60)
            ...
    """
    
    def __init__(self):
        self._limiter: Optional[SlidingWindowRateLimiter] = None
    
    async def _get_limiter(self) -> SlidingWindowRateLimiter:
        if not self._limiter:
            redis_client = _get_redis_client()
            self._limiter = SlidingWindowRateLimiter(redis_client)
        return self._limiter
    
    async def check(
        self,
        key: str,
        limit: int = 100,
        window: int = 60,
        identifier: Optional[str] = None
    ) -> bool:
        """
        Проверить лимит запросов.
        
        Args:
            key: Ключ операции (например, "login", "api_call")
            limit: Максимальное количество запросов
            window: Временное окно в секундах
            identifier: Идентификатор (если None, берётся из запроса)
        
        Raises:
            HTTPException: 429 если лимит превышен
        """
        limiter = await self._get_limiter()
        
        # Получаем идентификатор
        if not identifier:
            identifier = key
        
        result = await limiter.check(
            f"rate_limit:{identifier}",
            limit=limit,
            window=window
        )
        
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(result.reset_at.timestamp())),
                    "Retry-After": str(int(result.retry_after))
                }
            )
        
        return True
    
    async def get_remaining(self, key: str, window: int = 60) -> int:
        """Получить оставшееся количество запросов"""
        limiter = await self._get_limiter()
        status = await limiter.get_status(f"rate_limit:{key}", window)
        return settings.RATE_LIMIT_GLOBAL - status.get('current', 0)


async def check_rate_limit(
    request: Request,
    user: Optional[TokenData] = Depends(get_current_user_optional)
) -> None:
    """
    Автоматическая проверка rate limit для API запросов.
    Используется в middleware.
    """
    # api.rate_limit_enabled/api.rate_limit_requests (Настройки → API) раньше
    # сохранялись в БД, но эта проверка всегда использовала только
    # settings.RATE_LIMIT_ENABLED/RATE_LIMIT_API из .env - значения из
    # веб-интерфейса ни на что не влияли. Читаем их заново на каждый запрос
    # (без кеша в памяти - SettingsService сам кеширует в Redis), с тем же
    # запасным вариантом на .env при любом сбое, чтобы уже работающий
    # rate-limiting никогда не сломался из-за недоступности SettingsService.
    try:
        from app.services import get_settings_service
        settings_service = get_settings_service()
        rate_limit_enabled = await settings_service.get_setting_value("api.rate_limit_enabled")
        rate_limit_requests = await settings_service.get_setting_value("api.rate_limit_requests")
        if rate_limit_enabled is None:
            rate_limit_enabled = settings.RATE_LIMIT_ENABLED
        if not rate_limit_requests:
            rate_limit_requests = settings.RATE_LIMIT_API
    except Exception:
        rate_limit_enabled = settings.RATE_LIMIT_ENABLED
        rate_limit_requests = settings.RATE_LIMIT_API

    if not rate_limit_enabled:
        return

    # Определяем идентификатор
    if user:
        identifier = f"user:{user.user_id}"
    else:
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.headers.get("X-Real-IP", request.client.host if request.client else "unknown")
        identifier = f"ip:{client_ip}"

    # Определяем лимит в зависимости от эндпоинта. /api/auth/* сохраняет
    # отдельный, более строгий .env-лимит (RATE_LIMIT_AUTH) - настройка
    # api.rate_limit_requests относится к общему API, как и написано в её
    # описании, и подменяет только settings.RATE_LIMIT_API.
    path = request.url.path

    if path.startswith("/api/auth"):
        limit = settings.RATE_LIMIT_AUTH
    else:
        limit = rate_limit_requests
    
    redis_client = _get_redis_client()
    limiter = SlidingWindowRateLimiter(redis_client)
    
    result = await limiter.check(
        f"rate_limit:{identifier}:{path}",
        limit=limit,
        window=60
    )
    
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": str(int(result.retry_after))}
        )


# Готовая FastAPI-зависимость для маршрутов, требующих автоматической
# проверки rate limit без ручного создания Depends(check_rate_limit):
#     @router.post("/action")
#     async def action(_: None = RateLimitDep):
#         ...
RateLimitDep = Depends(check_rate_limit)


# =============================================
# Пагинация и фильтрация
# =============================================
@dataclass
class PaginationParams:
    """Параметры пагинации"""
    page: int = 1
    page_size: int = 20
    offset: int = 0
    
    @classmethod
    async def from_request(
        cls,
        page: int = Query(1, ge=1, description="Номер страницы"),
        page_size: int = Query(20, ge=1, le=100, description="Размер страницы")
    ) -> "PaginationParams":
        return cls(
            page=page,
            page_size=page_size,
            offset=(page - 1) * page_size
        )


@dataclass
class DateRangeParams:
    """Параметры диапазона дат"""
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    
    @classmethod
    async def from_request(
        cls,
        from_date: Optional[str] = Query(None, description="Дата начала (YYYY-MM-DD)"),
        to_date: Optional[str] = Query(None, description="Дата окончания (YYYY-MM-DD)")
    ) -> "DateRangeParams":
        params = cls()
        
        if from_date:
            try:
                params.from_date = datetime.strptime(from_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(400, "Invalid from_date format. Use YYYY-MM-DD")
        
        if to_date:
            try:
                params.to_date = datetime.strptime(to_date, "%Y-%m-%d")
                # Устанавливаем конец дня
                params.to_date = params.to_date.replace(hour=23, minute=59, second=59)
            except ValueError:
                raise HTTPException(400, "Invalid to_date format. Use YYYY-MM-DD")
        
        if params.from_date and params.to_date and params.from_date > params.to_date:
            raise HTTPException(400, "from_date cannot be after to_date")
        
        return params


@dataclass
class SortParams:
    """Параметры сортировки"""
    sort_by: str = "id"
    sort_order: str = "DESC"
    
    @classmethod
    async def from_request(
        cls,
        sort_by: Optional[str] = Query(None, description="Поле для сортировки"),
        sort_order: Optional[str] = Query("DESC", description="Порядок (ASC/DESC)")
    ) -> "SortParams":
        if sort_order.upper() not in ("ASC", "DESC"):
            sort_order = "DESC"
        
        return cls(
            sort_by=sort_by or "id",
            sort_order=sort_order.upper()
        )
    
    @property
    def order_clause(self) -> str:
        """SQL ORDER BY clause"""
        return f"{self.sort_by} {self.sort_order}"


# =============================================
# Фоновые задачи
# =============================================
async def get_background_tasks():
    """
    Получить менеджер фоновых задач.
    """
    from fastapi import BackgroundTasks
    return BackgroundTasks()


# =============================================
# Кеширование
# =============================================
class CacheDependency:
    """
    Зависимость для кеширования результатов.
    
    Использование:
        @router.get("/expensive")
        async def expensive(cache: CacheDependency = Depends()):
            return await cache.get_or_set("key", expensive_function, ttl=60)
    """
    
    def __init__(self, prefix: str = "api", default_ttl: int = 60):
        self.prefix = prefix
        self.default_ttl = default_ttl
        self._cache = None
    
    def _get_cache(self):
        if not self._cache:
            from app.core.redis import RedisCache
            redis_client = _get_redis_client()
            self._cache = RedisCache(redis_client, prefix=self.prefix, default_ttl=self.default_ttl)
        return self._cache
    
    async def get(self, key: str) -> Optional[Any]:
        return await self._get_cache().get(key)
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        await self._get_cache().set(key, value, ttl)
    
    async def get_or_set(self, key: str, factory: Callable, ttl: Optional[int] = None) -> Any:
        return await self._get_cache().get_or_set(key, factory, ttl)
    
    async def delete(self, key: str) -> int:
        return await self._get_cache().delete(key)
    
    async def clear_pattern(self, pattern: str) -> int:
        """Очистить ключи по паттерну"""
        redis_client = _get_redis_client()
        deleted = 0
        cursor = 0
        full_pattern = f"{self.prefix}:{pattern}"
        
        while True:
            cursor, keys = await redis_client.scan(cursor, match=full_pattern, count=100)
            if keys:
                deleted += await redis_client.delete(*keys)
            if cursor == 0:
                break
        
        return deleted


# =============================================
# Аудит
# =============================================
async def log_audit(
    request: Request,
    user: Optional[TokenData] = Depends(get_current_user_optional),
):
    """
    Зависимость для логирования аудит событий.
    
    Использование:
        @router.post("/something")
        async def something(audit: Callable = Depends(log_audit)):
            ...
            await audit("something_created", entity_type="something", entity_id=123)
    """
    
    async def _log(
        action: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        db_pool = _get_db_pool()
        
        user_id = user.user_id if user else None
        ip_address = request.client.host if request and request.client else None
        user_agent = request.headers.get("User-Agent") if request else None
        correlation_id = get_correlation_id()
        
        try:
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO audit_log 
                    (user_id, action, entity_type, entity_id, details, ip_address, user_agent, correlation_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, user_id, action, entity_type, entity_id, 
                   json.dumps(details) if details else None,
                   ip_address, user_agent, correlation_id)
                
                logger.audit(
                    f"AUDIT: {action}",
                    user_id=user_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    details=details
                )
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    return _log


# Импорт json для аудита
import json


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Схемы аутентификации
    "oauth2_scheme",
    "oauth2_cookie_scheme",
    "api_key_header",
    
    # Модели
    "TokenData",
    "ApiKeyData",
    
    # Зависимости пользователя
    "get_token_from_request",
    "get_current_user_optional",
    "get_current_user",
    "get_current_active_user",
    "require_admin",
    "require_operator",
    "require_viewer",
    "require_permission",
    
    # Метрики и вебхуки
    "verify_metrics_auth",
    "verify_webhook_auth",
    
    # Ресурсы
    "get_db_pool",
    "get_redis_client",
    "get_task_registry",
    "get_dialer_manager",
    "get_transcription_service",
    
    # Rate Limiting
    "RateLimiter",
    "check_rate_limit",
    "RateLimitDep",
    
    # Пагинация
    "PaginationParams",
    "DateRangeParams",
    "SortParams",
    
    # Фоновые задачи
    "get_background_tasks",
    
    # Кеширование
    "CacheDependency",
    
    # Аудит
    "log_audit",
]
