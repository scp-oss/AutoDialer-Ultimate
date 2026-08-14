#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления пользователями и аутентификацией
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Управления пользователями (CRUD)
- Аутентификации и авторизации
- Управления ролями и разрешениями
- Двухфакторной аутентификации (TOTP)
- Управления сессиями
- API ключей
"""

import json
import uuid
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from app.core.config import settings
from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient
from app.core.security import (
    hash_password, verify_password, validate_password_strength,
    create_access_token, create_refresh_token, decode_token,
    generate_api_key, hash_api_key, verify_api_key,
    totp_manager, LoginAttemptTracker
)
from app.models.user import (
    UserRole, UserStatus, Permission, ROLE_PERMISSIONS,
    UserCreateRequest, UserUpdateRequest, UserProfileUpdateRequest,
    UserResponse, UserProfileResponse, UserListResponse, UserSummaryResponse,
    NotificationPreferences, UserFilterRequest
)
from app.models.auth import (
    LoginRequest, LoginResponse, TokenResponse,
    RefreshTokenRequest, RefreshTokenResponse,
    ChangePasswordRequest, ResetPasswordRequest,
    ForgotPasswordRequest, ForgotPasswordConfirmRequest,
    TOTPSetupResponse, TOTPVerifyRequest, TOTPVerifyResponse,
    TOTPStatusResponse, TOTPDisableRequest,
    ApiKeyCreateRequest, ApiKeyResponse, ApiKeyListItem, ApiKeyListResponse,
    SessionInfo, SessionsListResponse
)
from prometheus_client import Counter, Gauge


# =============================================
# Метрики
# =============================================
users_total_gauge = Gauge(
    'autodialer_users_total',
    'Total users',
    ['role', 'status']
)
login_success_counter = Counter(
    'autodialer_login_success_total',
    'Successful logins'
)
login_failed_counter = Counter(
    'autodialer_login_failed_total',
    'Failed logins',
    ['reason']
)
active_sessions_gauge = Gauge(
    'autodialer_active_sessions',
    'Active user sessions'
)


# =============================================
# Исключения
# =============================================
class UserError(Exception):
    """Базовое исключение сервиса пользователей"""
    pass


class UserNotFoundError(UserError):
    """Пользователь не найден"""
    pass


class UserAlreadyExistsError(UserError):
    """Пользователь уже существует"""
    pass


class InvalidCredentialsError(UserError):
    """Неверные учётные данные"""
    pass


class AccountDisabledError(UserError):
    """Аккаунт отключён"""
    pass


class AccountLockedError(UserError):
    """Аккаунт заблокирован"""
    pass


class InvalidTokenError(UserError):
    """Неверный токен"""
    pass


class TokenExpiredError(UserError):
    """Токен истёк"""
    pass


class TOTPError(UserError):
    """Ошибка двухфакторной аутентификации"""
    pass


# =============================================
# Сервис пользователей
# =============================================
class UserService:
    """
    Сервис управления пользователями.
    
    Отвечает за:
    - CRUD операции с пользователями
    - Управление ролями и разрешениями
    - Блокировку/разблокировку
    - Сброс паролей
    """
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        self.login_tracker = LoginAttemptTracker(redis_client)
        
        logger.info("UserService инициализирован")
    
    # =============================================
    # CRUD операции
    # =============================================
    async def create_user(
        self,
        request: UserCreateRequest,
        created_by: Optional[int] = None
    ) -> UserResponse:
        """
        Создать нового пользователя.
        
        Args:
            request: Данные пользователя
            created_by: ID создателя
        
        Returns:
            Созданный пользователь
        """
        # Проверяем сложность пароля
        validate_password_strength(request.password)
        
        async with self.db_pool.acquire() as conn:
            # Проверяем существование
            existing = await conn.fetchrow("""
                SELECT id FROM users WHERE username = $1 OR email = $2
            """, request.username, request.email)
            
            if existing:
                raise UserAlreadyExistsError("Пользователь с таким именем или email уже существует")
            
            # Хешируем пароль
            password_hash = hash_password(request.password)
            
            # Создаём пользователя
            user_id = await conn.fetchval("""
                INSERT INTO users (
                    username, password_hash, email, full_name,
                    role, phone, department, position,
                    status, force_password_change,
                    created_by, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW(), NOW())
                RETURNING id
            """,
                request.username,
                password_hash,
                request.email,
                request.full_name,
                request.role,
                request.phone,
                request.department,
                request.position,
                UserStatus.ACTIVE.value if not request.force_password_change else UserStatus.PENDING.value,
                request.force_password_change,
                created_by
            )
            
            # Добавляем кастомные разрешения
            if request.custom_permissions:
                await self._add_custom_permissions(conn, user_id, request.custom_permissions)
            
            # Сохраняем метаданные
            if request.metadata:
                await conn.execute("""
                    UPDATE users SET metadata = $1 WHERE id = $2
                """, json.dumps(request.metadata), user_id)
            
            # Логируем
            await self._log_audit(conn, created_by, 'user_created', 'user', user_id, {
                'username': request.username,
                'role': request.role
            })

            # Получаем созданного пользователя
            user = await self._get_user_by_id(conn, user_id)

        users_total_gauge.labels(
            role=request.role,
            status=UserStatus.ACTIVE.value
        ).inc()
        
        logger.info(f"Пользователь создан: {request.username} (ID: {user_id})")
        
        # Отправляем приветственное письмо если нужно
        if request.send_welcome_email:
            await self._send_welcome_email(user)
        
        return user
    
    async def get_user(self, user_id: int) -> Optional[UserResponse]:
        """Получить пользователя по ID"""
        async with self.db_pool.acquire() as conn:
            return await self._get_user_by_id(conn, user_id)
    
    async def get_user_by_username(self, username: str) -> Optional[UserResponse]:
        """Получить пользователя по имени"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id FROM users WHERE username = $1 AND deleted_at IS NULL
            """, username)
            
            if not row:
                return None
            
            return await self._get_user_by_id(conn, row['id'])
    
    async def get_user_by_email(self, email: str) -> Optional[UserResponse]:
        """Получить пользователя по email"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id FROM users WHERE email = $1 AND deleted_at IS NULL
            """, email.lower())
            
            if not row:
                return None
            
            return await self._get_user_by_id(conn, row['id'])
    
    async def update_user(
        self,
        user_id: int,
        request: UserUpdateRequest,
        updated_by: Optional[int] = None
    ) -> UserResponse:
        """
        Обновить пользователя.
        
        Args:
            user_id: ID пользователя
            request: Данные для обновления
            updated_by: ID обновившего
        
        Returns:
            Обновлённый пользователь
        """
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id FROM users WHERE id = $1 AND deleted_at IS NULL
            """, user_id)
            
            if not existing:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            updates = []
            params = []
            param_idx = 1
            
            if request.email is not None:
                # Проверяем уникальность
                email_exists = await conn.fetchval("""
                    SELECT id FROM users WHERE email = $1 AND id != $2
                """, request.email.lower(), user_id)
                if email_exists:
                    raise UserAlreadyExistsError("Email уже используется")
                
                updates.append(f"email = ${param_idx}")
                params.append(request.email.lower())
                param_idx += 1
            
            if request.full_name is not None:
                updates.append(f"full_name = ${param_idx}")
                params.append(request.full_name)
                param_idx += 1
            
            if request.role is not None:
                updates.append(f"role = ${param_idx}")
                params.append(request.role)
                param_idx += 1
            
            if request.phone is not None:
                updates.append(f"phone = ${param_idx}")
                params.append(request.phone)
                param_idx += 1
            
            if request.department is not None:
                updates.append(f"department = ${param_idx}")
                params.append(request.department)
                param_idx += 1
            
            if request.position is not None:
                updates.append(f"position = ${param_idx}")
                params.append(request.position)
                param_idx += 1
            
            if request.status is not None:
                updates.append(f"status = ${param_idx}")
                params.append(request.status)
                param_idx += 1

            if request.force_password_change is not None:
                updates.append(f"force_password_change = ${param_idx}")
                params.append(request.force_password_change)
                param_idx += 1
            
            if request.metadata is not None:
                updates.append(f"metadata = ${param_idx}")
                params.append(json.dumps(request.metadata))
                param_idx += 1
            
            if updates:
                updates.append(f"updated_at = NOW()")
                params.append(user_id)
                query = f"""
                    UPDATE users 
                    SET {', '.join(updates)}
                    WHERE id = ${param_idx}
                """
                await conn.execute(query, *params)
            
            # Обновляем кастомные разрешения
            if request.custom_permissions is not None:
                await self._update_custom_permissions(conn, user_id, request.custom_permissions)
            
            # Логируем
            await self._log_audit(conn, updated_by, 'user_updated', 'user', user_id)
            
            # Получаем обновлённого пользователя
            user = await self._get_user_by_id(conn, user_id)
        
        logger.info(f"Пользователь {user_id} обновлён")
        
        return user
    
    async def update_profile(
        self,
        user_id: int,
        request: UserProfileUpdateRequest
    ) -> UserProfileResponse:
        """
        Обновить свой профиль.
        
        Args:
            user_id: ID пользователя
            request: Данные для обновления
        
        Returns:
            Обновлённый профиль
        """
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id FROM users WHERE id = $1 AND deleted_at IS NULL
            """, user_id)
            
            if not existing:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            updates = []
            params = []
            param_idx = 1
            
            if request.email is not None:
                email_exists = await conn.fetchval("""
                    SELECT id FROM users WHERE email = $1 AND id != $2
                """, request.email.lower(), user_id)
                if email_exists:
                    raise UserAlreadyExistsError("Email уже используется")
                
                updates.append(f"email = ${param_idx}")
                params.append(request.email.lower())
                param_idx += 1
            
            if request.full_name is not None:
                updates.append(f"full_name = ${param_idx}")
                params.append(request.full_name)
                param_idx += 1
            
            if request.phone is not None:
                updates.append(f"phone = ${param_idx}")
                params.append(request.phone)
                param_idx += 1
            
            if request.avatar_url is not None:
                updates.append(f"avatar_url = ${param_idx}")
                params.append(request.avatar_url)
                param_idx += 1
            
            if request.preferences:
                updates.append(f"preferences = ${param_idx}")
                params.append(json.dumps(request.preferences))
                param_idx += 1
            
            if updates:
                updates.append(f"updated_at = NOW()")
                params.append(user_id)
                query = f"""
                    UPDATE users 
                    SET {', '.join(updates)}
                    WHERE id = ${param_idx}
                """
                await conn.execute(query, *params)
            
            # Получаем обновлённый профиль
            user = await self._get_user_profile_by_id(conn, user_id)
        
        logger.info(f"Профиль пользователя {user_id} обновлён")
        
        return user
    
    async def delete_user(
        self,
        user_id: int,
        deleted_by: Optional[int] = None
    ) -> bool:
        """
        Удалить пользователя (мягкое удаление).
        
        Args:
            user_id: ID пользователя
            deleted_by: ID удалившего
        
        Returns:
            True если удалён
        """
        if user_id == 1:
            raise UserError("Нельзя удалить администратора по умолчанию")
        
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id, role FROM users WHERE id = $1 AND deleted_at IS NULL
            """, user_id)
            
            if not existing:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            # Мягкое удаление
            await conn.execute("""
                UPDATE users 
                SET deleted_at = NOW(), status = $1, updated_at = NOW()
                WHERE id = $2
            """, UserStatus.INACTIVE.value, user_id)
            
            # Отзываем все сессии
            await self._revoke_all_sessions(user_id)
            
            # Отзываем API ключи
            await conn.execute("""
                UPDATE api_keys SET is_active = FALSE WHERE user_id = $1
            """, user_id)
            
            # Логируем
            await self._log_audit(conn, deleted_by, 'user_deleted', 'user', user_id)
            
            # Обновляем метрику
            users_total_gauge.labels(
                role=existing['role'],
                status=UserStatus.ACTIVE.value
            ).dec()
        
        logger.info(f"Пользователь {user_id} удалён")
        
        return True
    
    async def restore_user(
        self,
        user_id: int,
        restored_by: Optional[int] = None
    ) -> UserResponse:
        """
        Восстановить удалённого пользователя.
        
        Args:
            user_id: ID пользователя
            restored_by: ID восстановившего
        
        Returns:
            Восстановленный пользователь
        """
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id, role FROM users WHERE id = $1 AND deleted_at IS NOT NULL
            """, user_id)
            
            if not existing:
                raise UserNotFoundError(f"Удалённый пользователь {user_id} не найден")
            
            await conn.execute("""
                UPDATE users 
                SET deleted_at = NULL, status = $1, updated_at = NOW()
                WHERE id = $2
            """, UserStatus.ACTIVE.value, user_id)
            
            await self._log_audit(conn, restored_by, 'user_restored', 'user', user_id)
            
            user = await self._get_user_by_id(conn, user_id)
            
            users_total_gauge.labels(
                role=existing['role'],
                status=UserStatus.ACTIVE.value
            ).inc()
        
        logger.info(f"Пользователь {user_id} восстановлен")
        
        return user
    
    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        filter_params: Optional[UserFilterRequest] = None
    ) -> UserListResponse:
        """
        Получить список пользователей с фильтрацией.
        
        Args:
            page: Номер страницы
            page_size: Размер страницы
            filter_params: Параметры фильтрации
        
        Returns:
            Список пользователей
        """
        offset = (page - 1) * page_size
        
        async with self.db_pool.acquire() as conn:
            where_conditions = ["deleted_at IS NULL"]
            params = []
            param_idx = 1
            
            if filter_params:
                if filter_params.search:
                    where_conditions.append(f"""
                        (username ILIKE ${param_idx} 
                         OR email ILIKE ${param_idx}
                         OR full_name ILIKE ${param_idx})
                    """)
                    params.append(f"%{filter_params.search}%")
                    param_idx += 1
                
                if filter_params.role:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.role))])
                    where_conditions.append(f"role IN ({placeholders})")
                    params.extend(list(filter_params.role))
                    param_idx += len(filter_params.role)

                if filter_params.status:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.status))])
                    where_conditions.append(f"status IN ({placeholders})")
                    params.extend(list(filter_params.status))
                    param_idx += len(filter_params.status)
                
                if filter_params.department:
                    where_conditions.append(f"department = ${param_idx}")
                    params.append(filter_params.department)
                    param_idx += 1
                
                if filter_params.created_after:
                    where_conditions.append(f"created_at >= ${param_idx}")
                    params.append(filter_params.created_after)
                    param_idx += 1
                
                if filter_params.created_before:
                    where_conditions.append(f"created_at <= ${param_idx}")
                    params.append(filter_params.created_before)
                    param_idx += 1
                
                if filter_params.last_login_after:
                    where_conditions.append(f"last_login >= ${param_idx}")
                    params.append(filter_params.last_login_after)
                    param_idx += 1
                
                if filter_params.has_totp is not None:
                    if filter_params.has_totp:
                        where_conditions.append("totp_secret IS NOT NULL")
                    else:
                        where_conditions.append("totp_secret IS NULL")
                
                if filter_params.force_password_change is not None:
                    where_conditions.append(f"force_password_change = ${param_idx}")
                    params.append(filter_params.force_password_change)
                    param_idx += 1
            
            where_clause = "WHERE " + " AND ".join(where_conditions)
            
            # Общее количество
            count_query = f"SELECT COUNT(*) FROM users {where_clause}"
            total = await conn.fetchval(count_query, *params)
            
            # Сортировка
            sort_by = filter_params.sort_by if filter_params else "id"
            sort_order = filter_params.sort_order if filter_params else "DESC"
            
            # Получаем данные
            query = f"""
                SELECT 
                    id, username, email, full_name, role, status,
                    force_password_change, last_login, last_ip,
                    login_count, totp_secret IS NOT NULL as totp_enabled,
                    avatar_url, phone, department, position,
                    created_at, updated_at
                FROM users
                {where_clause}
                ORDER BY {sort_by} {sort_order}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([page_size, offset])
            
            rows = await conn.fetch(query, *params)
            
            items = []
            for row in rows:
                # Получаем кастомные разрешения
                custom_perms = await self._get_custom_permissions(conn, row['id'])
                
                # Получаем метаданные
                metadata_row = await conn.fetchrow("""
                    SELECT metadata FROM users WHERE id = $1
                """, row['id'])
                metadata = json.loads(metadata_row['metadata']) if metadata_row and metadata_row['metadata'] else {}
                
                # Получаем статистику
                campaigns_created = await conn.fetchval("""
                    SELECT COUNT(*) FROM campaigns WHERE created_by = $1
                """, row['id'])
                
                user = UserResponse(
                    id=row['id'],
                    username=row['username'],
                    email=row['email'],
                    full_name=row['full_name'],
                    role=UserRole(row['role']),
                    custom_permissions=custom_perms,
                    permissions=[],  # Вычисляется в модели
                    phone=row['phone'],
                    department=row['department'],
                    position=row['position'],
                    avatar_url=row['avatar_url'],
                    status=UserStatus(row['status']),
                    force_password_change=row['force_password_change'],
                    last_login=row['last_login'],
                    last_ip=str(row['last_ip']) if row['last_ip'] else None,
                    login_count=row['login_count'] or 0,
                    totp_enabled=row['totp_enabled'],
                    campaigns_created=campaigns_created,
                    calls_made=0,
                    metadata=metadata,
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
                items.append(user)
            
            return UserListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=(total + page_size - 1) // page_size
            )
    
    # =============================================
    # Управление статусом
    # =============================================
    async def enable_user(
        self,
        user_id: int,
        enabled_by: Optional[int] = None
    ) -> UserResponse:
        """Активировать пользователя"""
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id, status FROM users WHERE id = $1 AND deleted_at IS NULL
            """, user_id)
            
            if not existing:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            await conn.execute("""
                UPDATE users 
                SET status = $1, updated_at = NOW()
                WHERE id = $2
            """, UserStatus.ACTIVE.value, user_id)
            
            await self._log_audit(conn, enabled_by, 'user_enabled', 'user', user_id)
            
            return await self._get_user_by_id(conn, user_id)
    
    async def disable_user(
        self,
        user_id: int,
        disabled_by: Optional[int] = None
    ) -> UserResponse:
        """Деактивировать пользователя"""
        if user_id == 1:
            raise UserError("Нельзя деактивировать администратора по умолчанию")
        
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id, status FROM users WHERE id = $1 AND deleted_at IS NULL
            """, user_id)
            
            if not existing:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            await conn.execute("""
                UPDATE users 
                SET status = $1, updated_at = NOW()
                WHERE id = $2
            """, UserStatus.INACTIVE.value, user_id)
            
            # Отзываем все сессии
            await self._revoke_all_sessions(user_id)
            
            await self._log_audit(conn, disabled_by, 'user_disabled', 'user', user_id)
            
            return await self._get_user_by_id(conn, user_id)
    
    async def reset_password(
        self,
        user_id: int,
        new_password: str,
        force_change: bool = True,
        reset_by: Optional[int] = None
    ) -> bool:
        """
        Сбросить пароль пользователя (администратором).
        
        Args:
            user_id: ID пользователя
            new_password: Новый пароль
            force_change: Потребовать смену при следующем входе
            reset_by: ID сбросившего
        
        Returns:
            True если сброшен
        """
        validate_password_strength(new_password)
        
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id FROM users WHERE id = $1 AND deleted_at IS NULL
            """, user_id)
            
            if not existing:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            password_hash = hash_password(new_password)
            
            await conn.execute("""
                UPDATE users 
                SET password_hash = $1, 
                    force_password_change = $2,
                    updated_at = NOW()
                WHERE id = $3
            """, password_hash, force_change, user_id)
            
            # Отзываем все сессии
            await self._revoke_all_sessions(user_id)
            
            await self._log_audit(conn, reset_by, 'password_reset', 'user', user_id)
        
        logger.info(f"Пароль пользователя {user_id} сброшен")
        
        return True
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    async def _get_user_by_id(self, conn, user_id: int) -> Optional[UserResponse]:
        """Получить пользователя по ID (внутренний метод)"""
        row = await conn.fetchrow("""
            SELECT 
                id, username, email, full_name, role, status,
                force_password_change, last_login, last_ip,
                login_count, totp_secret IS NOT NULL as totp_enabled,
                avatar_url, phone, department, position,
                created_at, updated_at
            FROM users
            WHERE id = $1 AND deleted_at IS NULL
        """, user_id)
        
        if not row:
            return None
        
        custom_perms = await self._get_custom_permissions(conn, user_id)
        
        metadata_row = await conn.fetchrow("""
            SELECT metadata FROM users WHERE id = $1
        """, user_id)
        metadata = json.loads(metadata_row['metadata']) if metadata_row and metadata_row['metadata'] else {}
        
        campaigns_created = await conn.fetchval("""
            SELECT COUNT(*) FROM campaigns WHERE created_by = $1
        """, user_id)
        
        return UserResponse(
            id=row['id'],
            username=row['username'],
            email=row['email'],
            full_name=row['full_name'],
            role=UserRole(row['role']),
            custom_permissions=custom_perms,
            permissions=[],
            phone=row['phone'],
            department=row['department'],
            position=row['position'],
            avatar_url=row['avatar_url'],
            status=UserStatus(row['status']),
            force_password_change=row['force_password_change'],
            last_login=row['last_login'],
            last_ip=str(row['last_ip']) if row['last_ip'] else None,
            login_count=row['login_count'] or 0,
            totp_enabled=row['totp_enabled'],
            campaigns_created=campaigns_created,
            calls_made=0,
            metadata=metadata,
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )

    async def _get_user_profile_by_id(self, conn, user_id: int) -> Optional[UserProfileResponse]:
        """Получить профиль пользователя"""
        user = await self._get_user_by_id(conn, user_id)
        if not user:
            return None
        
        # Получаем настройки
        prefs_row = await conn.fetchrow("""
            SELECT preferences, notifications FROM users WHERE id = $1
        """, user_id)
        
        preferences = {}
        notifications = {}
        if prefs_row:
            preferences = json.loads(prefs_row['preferences']) if prefs_row['preferences'] else {}
            notifications = json.loads(prefs_row['notifications']) if prefs_row['notifications'] else {}
        
        # Количество API ключей
        api_keys_count = await conn.fetchval("""
            SELECT COUNT(*) FROM api_keys WHERE user_id = $1 AND is_active = TRUE
        """, user_id)
        
        # Количество активных сессий
        active_sessions = await self._get_active_sessions_count(user_id)
        
        return UserProfileResponse(
            **user.model_dump(),
            preferences=preferences,
            notifications=notifications,
            api_keys_count=api_keys_count,
            active_sessions_count=active_sessions,
            limits={}
        )
    
    async def _get_custom_permissions(self, conn, user_id: int) -> List[Permission]:
        rows = await conn.fetch("""
            SELECT permission FROM user_permissions WHERE user_id = $1
        """, user_id)
        return [Permission(row['permission']) for row in rows]
    
    async def _add_custom_permissions(self, conn, user_id: int, permissions: List[Permission]) -> None:
        # permissions comes from a BaseSchema field (use_enum_values=True in
        # app/models/common.py), so items are already the plain string values,
        # not Permission instances - see app/services/blacklist.py for the
        # same pattern documented in ROADMAP.md.
        for perm in permissions:
            await conn.execute("""
                INSERT INTO user_permissions (user_id, permission)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, user_id, perm)
    
    async def _update_custom_permissions(self, conn, user_id: int, permissions: List[Permission]) -> None:
        await conn.execute("DELETE FROM user_permissions WHERE user_id = $1", user_id)
        await self._add_custom_permissions(conn, user_id, permissions)
    
    async def _revoke_all_sessions(self, user_id: int) -> None:
        """Отозвать все сессии пользователя"""
        pattern = f"session:{user_id}:*"
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break
    
    async def _get_active_sessions_count(self, user_id: int) -> int:
        """Получить количество активных сессий"""
        pattern = f"session:{user_id}:*"
        count = 0
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            count += len(keys)
            if cursor == 0:
                break
        return count
    
    async def _send_welcome_email(self, user: UserResponse) -> None:
        """Отправить приветственное письмо"""
        # TODO: Интеграция с email сервисом
        logger.info(f"Приветственное письмо отправлено пользователю {user.email}")
    
    async def _log_audit(
        self,
        conn,
        user_id: Optional[int],
        action: str,
        entity_type: str,
        entity_id: int,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Записать аудит"""
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, entity_type, entity_id, details)
            VALUES ($1, $2, $3, $4, $5)
        """, user_id, action, entity_type, entity_id, json.dumps(details) if details else None)
    
    # =============================================
    # Health check
    # =============================================
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        logger.info("UserService остановлен")


# =============================================
# Сервис аутентификации
# =============================================
class AuthService:
    """
    Сервис аутентификации и авторизации.
    
    Отвечает за:
    - Вход/выход пользователей
    - Управление токенами
    - Двухфакторную аутентификацию
    - Управление API ключами
    - Управление сессиями
    """
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        self.login_tracker = LoginAttemptTracker(redis_client)
        self.user_service = UserService(db_pool, redis_client)
        
        logger.info("AuthService инициализирован")
    
    # =============================================
    # Аутентификация
    # =============================================
    async def login(
        self,
        request: LoginRequest,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> LoginResponse:
        """
        Вход в систему.
        
        Args:
            request: Данные для входа
            ip_address: IP адрес
            user_agent: User Agent
        
        Returns:
            Токены и информация о пользователе
        """
        # Проверяем блокировку
        if await self.login_tracker.is_blocked(request.username):
            login_failed_counter.labels(reason='blocked').inc()
            raise AccountLockedError("Аккаунт временно заблокирован. Попробуйте позже.")
        
        async with self.db_pool.acquire() as conn:
            # Ищем пользователя
            user = await conn.fetchrow("""
                SELECT 
                    id, username, password_hash, role, status,
                    force_password_change, email, full_name,
                    totp_secret, totp_enabled
                FROM users
                WHERE (username = $1 OR email = $1)
                AND deleted_at IS NULL
            """, request.username)
            
            if not user:
                await self.login_tracker.record_failure(request.username)
                login_failed_counter.labels(reason='invalid_credentials').inc()
                raise InvalidCredentialsError("Неверное имя пользователя или пароль")
            
            # Проверяем статус
            if user['status'] != UserStatus.ACTIVE.value:
                login_failed_counter.labels(reason='account_disabled').inc()
                raise AccountDisabledError("Аккаунт отключён")
            
            # Проверяем пароль
            if not verify_password(request.password, user['password_hash']):
                await self.login_tracker.record_failure(request.username)
                login_failed_counter.labels(reason='invalid_credentials').inc()
                raise InvalidCredentialsError("Неверное имя пользователя или пароль")
            
            # Проверяем TOTP если включён
            if user['totp_enabled']:
                if not request.totp_code:
                    return LoginResponse(
                        access_token="",
                        refresh_token="",
                        token_type="bearer",
                        role=user['role'],
                        force_password_change=False,
                        user_id=user['id'],
                        username=user['username'],
                        full_name=user['full_name'],
                        email=user['email'],
                        permissions=[],
                        expires_in=0
                    )
                
                if not totp_manager.verify_totp(user['totp_secret'], request.totp_code):
                    await self.login_tracker.record_failure(request.username)
                    login_failed_counter.labels(reason='invalid_totp').inc()
                    raise TOTPError("Неверный код двухфакторной аутентификации")
            
            # Успешный вход
            await self.login_tracker.record_success(request.username)
            
            # Обновляем last_login
            await conn.execute("""
                UPDATE users 
                SET last_login = NOW(), 
                    last_ip = $1,
                    login_count = login_count + 1,
                    updated_at = NOW()
                WHERE id = $2
            """, ip_address, user['id'])
            
            # Получаем разрешения
            permissions = await self._get_user_permissions(conn, user['id'], user['role'])
            
            # Создаём токены
            token_data = {
                "user_id": user['id'],
                "sub": user['username'],
                "role": user['role'],
                "permissions": [p.value for p in permissions]
            }
            
            access_token = create_access_token(token_data)
            refresh_token = create_refresh_token(token_data)
            
            # Сохраняем refresh токен в Redis
            refresh_payload = decode_token(refresh_token)
            await self.redis.setex(
                f"refresh:{refresh_payload['jti']}",
                settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
                str(user['id'])
            )
            
            # Создаём сессию
            session_id = await self._create_session(
                user['id'], ip_address, user_agent, request.remember_me
            )
            
            # Логируем
            await self._log_audit(conn, user['id'], 'login', 'user', user['id'], {
                'ip_address': ip_address,
                'session_id': session_id
            })
            
            login_success_counter.inc()
            
            logger.info(f"Пользователь {user['username']} вошёл в систему")
            
            return LoginResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                role=user['role'],
                force_password_change=user['force_password_change'],
                user_id=user['id'],
                username=user['username'],
                full_name=user['full_name'],
                email=user['email'],
                permissions=[p.value for p in permissions],
                expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
            )
    
    async def refresh(self, refresh_token: str) -> RefreshTokenResponse:
        """
        Обновить access токен.
        
        Args:
            refresh_token: Refresh токен
        
        Returns:
            Новый access токен
        """
        try:
            payload = decode_token(refresh_token)
        except Exception:
            raise InvalidTokenError("Неверный токен")
        
        if payload.get('type') != 'refresh':
            raise InvalidTokenError("Неверный тип токена")
        
        # Проверяем в Redis
        user_id_str = await self.redis.get(f"refresh:{payload['jti']}")
        if not user_id_str:
            raise InvalidTokenError("Токен отозван")
        
        user_id = int(user_id_str)
        
        async with self.db_pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT username, role, status FROM users WHERE id = $1 AND deleted_at IS NULL
            """, user_id)
            
            if not user:
                raise UserNotFoundError("Пользователь не найден")
            
            if user['status'] != UserStatus.ACTIVE.value:
                raise AccountDisabledError("Аккаунт отключён")
            
            # Получаем разрешения
            permissions = await self._get_user_permissions(conn, user_id, user['role'])
            
            # Создаём новый access токен
            token_data = {
                "user_id": user_id,
                "sub": user['username'],
                "role": user['role'],
                "permissions": [p.value for p in permissions]
            }
            
            access_token = create_access_token(token_data)
            
            return RefreshTokenResponse(
                access_token=access_token,
                token_type="bearer",
                expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
            )
    
    async def logout(self, user_data) -> bool:
        """
        Выход из системы.
        
        Args:
            user_data: Данные пользователя из токена
        
        Returns:
            True если успешно
        """
        # Удаляем refresh токен
        if user_data.token_jti:
            await self.redis.delete(f"refresh:{user_data.token_jti}")
        
        # Удаляем сессию
        if user_data.session_id:
            await self.redis.delete(f"session:{user_data.user_id}:{user_data.session_id}")
        
        logger.info(f"Пользователь {user_data.username} вышёл из системы")
        
        return True
    
    async def change_password(
        self,
        user_id: int,
        request: ChangePasswordRequest
    ) -> bool:
        """
        Сменить пароль.
        
        Args:
            user_id: ID пользователя
            request: Данные для смены пароля
        
        Returns:
            True если сменён
        """
        validate_password_strength(request.new_password)
        
        if request.old_password == request.new_password:
            raise UserError("Новый пароль должен отличаться от старого")
        
        async with self.db_pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT password_hash FROM users WHERE id = $1 AND deleted_at IS NULL
            """, user_id)
            
            if not user:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            if not verify_password(request.old_password, user['password_hash']):
                raise InvalidCredentialsError("Неверный текущий пароль")
            
            password_hash = hash_password(request.new_password)
            
            await conn.execute("""
                UPDATE users 
                SET password_hash = $1, 
                    force_password_change = FALSE,
                    updated_at = NOW()
                WHERE id = $2
            """, password_hash, user_id)
            
            # Отзываем все сессии кроме текущей?
            # await self._revoke_all_sessions(user_id)
            
            await self._log_audit(conn, user_id, 'password_changed', 'user', user_id)
        
        logger.info(f"Пароль пользователя {user_id} изменён")
        
        return True
    
    async def forgot_password(self, request: ForgotPasswordRequest) -> bool:
        """
        Запросить восстановление пароля.
        
        Args:
            request: Данные запроса
        
        Returns:
            True если запрос обработан
        """
        user = await self.user_service.get_user_by_email(request.email)
        if not user:
            # Не раскрываем, что пользователь не найден
            return True
        
        # Генерируем токен восстановления
        reset_token = secrets.token_urlsafe(32)
        
        # Сохраняем в Redis
        await self.redis.setex(
            f"password_reset:{reset_token}",
            3600,  # 1 час
            str(user.id)
        )
        
        # TODO: Отправить email с токеном
        logger.info(f"Токен восстановления создан для пользователя {user.id}")
        
        return True
    
    async def confirm_forgot_password(
        self,
        request: ForgotPasswordConfirmRequest
    ) -> bool:
        """
        Подтвердить восстановление пароля.
        
        Args:
            request: Данные подтверждения
        
        Returns:
            True если пароль изменён
        """
        # Проверяем токен
        user_id_str = await self.redis.get(f"password_reset:{request.token}")
        if not user_id_str:
            raise InvalidTokenError("Неверный или истекший токен")
        
        user_id = int(user_id_str)
        
        # Меняем пароль
        await self.user_service.reset_password(user_id, request.new_password, False)
        
        # Удаляем токен
        await self.redis.delete(f"password_reset:{request.token}")
        
        logger.info(f"Пароль восстановлен для пользователя {user_id}")
        
        return True
    
    # =============================================
    # TOTP (2FA)
    # =============================================
    async def setup_totp(self, user_id: int) -> TOTPSetupResponse:
        """
        Настроить двухфакторную аутентификацию.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Данные для настройки TOTP
        """
        async with self.db_pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT username, totp_enabled FROM users WHERE id = $1
            """, user_id)
            
            if not user:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            if user['totp_enabled']:
                raise TOTPError("2FA уже настроена")
            
            # Генерируем секрет
            secret = totp_manager.generate_secret()
            uri = totp_manager.get_totp_uri(secret, user['username'])
            
            # Генерируем коды восстановления
            recovery_codes = totp_manager.generate_recovery_codes(10)
            
            # Сохраняем секрет (но пока не активируем)
            await conn.execute("""
                UPDATE users 
                SET totp_secret = $1,
                    totp_recovery_codes = $2
                WHERE id = $3
            """, secret, json.dumps(recovery_codes), user_id)
        
        logger.info(f"Настройка 2FA начата для пользователя {user_id}")
        
        return TOTPSetupResponse(
            secret=secret,
            uri=uri,
            recovery_codes=recovery_codes
        )
    
    async def verify_totp(
        self,
        user_id: int,
        request: TOTPVerifyRequest
    ) -> TOTPVerifyResponse:
        """
        Подтвердить настройку 2FA.
        
        Args:
            user_id: ID пользователя
            request: Данные проверки
        
        Returns:
            Результат проверки
        """
        async with self.db_pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT totp_secret, totp_recovery_codes FROM users WHERE id = $1
            """, user_id)
            
            if not user:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            if not user['totp_secret']:
                raise TOTPError("2FA не настроена")
            
            # Проверяем код
            if request.code:
                verified = totp_manager.verify_totp(user['totp_secret'], request.code)
            elif request.recovery_code:
                # Проверяем код восстановления
                recovery_codes = json.loads(user['totp_recovery_codes']) if user['totp_recovery_codes'] else []
                code_hash = totp_manager.hash_recovery_code(request.recovery_code)
                
                verified = False
                for stored_code in recovery_codes:
                    if totp_manager.hash_recovery_code(stored_code) == code_hash:
                        verified = True
                        # Удаляем использованный код
                        recovery_codes.remove(stored_code)
                        await conn.execute("""
                            UPDATE users SET totp_recovery_codes = $1 WHERE id = $2
                        """, json.dumps(recovery_codes), user_id)
                        break
            else:
                raise TOTPError("Необходимо указать code или recovery_code")
            
            if verified:
                # Активируем 2FA
                await conn.execute("""
                    UPDATE users 
                    SET totp_enabled = TRUE,
                        updated_at = NOW()
                    WHERE id = $1
                """, user_id)
                
                await self._log_audit(conn, user_id, 'totp_enabled', 'user', user_id)
                
                logger.info(f"2FA активирована для пользователя {user_id}")
                
                return TOTPVerifyResponse(
                    verified=True,
                    message="2FA успешно активирована"
                )
            else:
                return TOTPVerifyResponse(
                    verified=False,
                    message="Неверный код"
                )
    
    async def disable_totp(
        self,
        user_id: int,
        request: TOTPDisableRequest
    ) -> bool:
        """
        Отключить 2FA.
        
        Args:
            user_id: ID пользователя
            request: Данные для отключения
        
        Returns:
            True если отключена
        """
        async with self.db_pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT password_hash, totp_secret, totp_enabled FROM users WHERE id = $1
            """, user_id)
            
            if not user:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            if not user['totp_enabled']:
                return True
            
            # Проверяем пароль
            if not verify_password(request.password, user['password_hash']):
                raise InvalidCredentialsError("Неверный пароль")
            
            # Проверяем TOTP или код восстановления
            verified = False
            if request.code:
                verified = totp_manager.verify_totp(user['totp_secret'], request.code)
            elif request.recovery_code:
                recovery_codes = json.loads(user['totp_recovery_codes']) if user['totp_recovery_codes'] else []
                for stored_code in recovery_codes:
                    if totp_manager.hash_recovery_code(stored_code) == totp_manager.hash_recovery_code(request.recovery_code):
                        verified = True
                        break
            
            if not verified:
                raise TOTPError("Неверный код подтверждения")
            
            # Отключаем 2FA
            await conn.execute("""
                UPDATE users 
                SET totp_enabled = FALSE,
                    totp_secret = NULL,
                    totp_recovery_codes = NULL,
                    updated_at = NOW()
                WHERE id = $1
            """, user_id)
            
            await self._log_audit(conn, user_id, 'totp_disabled', 'user', user_id)
        
        logger.info(f"2FA отключена для пользователя {user_id}")
        
        return True
    
    async def get_totp_status(self, user_id: int) -> TOTPStatusResponse:
        """Получить статус 2FA"""
        async with self.db_pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT 
                    totp_enabled,
                    totp_secret IS NOT NULL as setup_completed,
                    totp_recovery_codes,
                    totp_last_used
                FROM users WHERE id = $1
            """, user_id)
            
            if not user:
                raise UserNotFoundError(f"Пользователь {user_id} не найден")
            
            codes_remaining = 0
            if user['totp_recovery_codes']:
                codes = json.loads(user['totp_recovery_codes'])
                codes_remaining = len(codes)
            
            return TOTPStatusResponse(
                enabled=user['totp_enabled'],
                setup_completed=user['setup_completed'],
                backup_codes_remaining=codes_remaining,
                last_used_at=user['totp_last_used']
            )
    
    # =============================================
    # API ключи
    # =============================================
    async def create_api_key(
        self,
        user_id: int,
        request: ApiKeyCreateRequest
    ) -> ApiKeyResponse:
        """
        Создать API ключ.
        
        Args:
            user_id: ID пользователя
            request: Данные ключа
        
        Returns:
            Созданный ключ (показывается только один раз!)
        """
        # Генерируем ключ
        full_key, stored_key, key_hash = generate_api_key()
        
        async with self.db_pool.acquire() as conn:
            key_id = await conn.fetchval("""
                INSERT INTO api_keys (
                    user_id, name, key_hash, key_prefix,
                    permissions, expires_at, ip_whitelist
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
            """,
                user_id,
                request.name,
                key_hash,
                stored_key.split('_')[0] + '_',
                json.dumps(request.permissions),
                request.expires_at,
                json.dumps(request.ip_whitelist) if request.ip_whitelist else None
            )
            
            await self._log_audit(conn, user_id, 'api_key_created', 'api_key', key_id, {
                'name': request.name
            })
        
        logger.info(f"API ключ создан для пользователя {user_id}: {request.name}")
        
        return ApiKeyResponse(
            id=key_id,
            name=request.name,
            key=full_key,  # Показываем только при создании!
            prefix=stored_key.split('_')[0] + '_',
            created_at=datetime.utcnow(),
            expires_at=request.expires_at,
            permissions=request.permissions
        )
    
    async def list_api_keys(self, user_id: int) -> ApiKeyListResponse:
        """Получить список API ключей пользователя"""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    id, name, key_prefix,
                    created_at, last_used_at, expires_at,
                    is_active, permissions
                FROM api_keys
                WHERE user_id = $1
                ORDER BY created_at DESC
            """, user_id)
            
            items = []
            for row in rows:
                permissions = json.loads(row['permissions']) if row['permissions'] else []
                
                items.append(ApiKeyListItem(
                    id=row['id'],
                    name=row['name'],
                    prefix=row['key_prefix'],
                    created_at=row['created_at'],
                    last_used_at=row['last_used_at'],
                    expires_at=row['expires_at'],
                    is_active=row['is_active'],
                    permissions=permissions
                ))
            
            return ApiKeyListResponse(
                items=items,
                total=len(items)
            )
    
    async def revoke_api_key(self, user_id: int, key_id: int) -> bool:
        """Отозвать API ключ"""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE api_keys 
                SET is_active = FALSE 
                WHERE id = $1 AND user_id = $2
            """, key_id, user_id)
            
            if "UPDATE 0" in result:
                return False
            
            await self._log_audit(conn, user_id, 'api_key_revoked', 'api_key', key_id)
        
        logger.info(f"API ключ {key_id} отозван")
        
        return True
    
    async def verify_api_key(self, api_key: str) -> Optional[Tuple[int, List[str]]]:
        """
        Проверить API ключ.
        
        Args:
            api_key: API ключ
        
        Returns:
            (user_id, permissions) или None
        """
        key_hash = hash_api_key(api_key)
        
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    user_id, permissions, expires_at, ip_whitelist
                FROM api_keys
                WHERE key_hash = $1 AND is_active = TRUE
            """, key_hash)
            
            if not row:
                return None
            
            # Проверяем срок действия
            if row['expires_at'] and row['expires_at'] < datetime.utcnow():
                return None
            
            # Обновляем last_used_at
            await conn.execute("""
                UPDATE api_keys SET last_used_at = NOW() WHERE key_hash = $1
            """, key_hash)
            
            permissions = json.loads(row['permissions']) if row['permissions'] else []
            
            return row['user_id'], permissions
    
    # =============================================
    # Сессии
    # =============================================
    async def list_sessions(self, user_id: int) -> SessionsListResponse:
        """Получить список активных сессий пользователя"""
        sessions = []
        pattern = f"session:{user_id}:*"
        
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            
            for key in keys:
                data = await self.redis.get(key)
                if data:
                    session = json.loads(data)
                    sessions.append(SessionInfo(
                        session_id=session['session_id'],
                        ip_address=session.get('ip_address'),
                        user_agent=session.get('user_agent'),
                        created_at=datetime.fromisoformat(session['created_at']),
                        last_activity=datetime.fromisoformat(session.get('last_activity', session['created_at'])),
                        is_current=False
                    ))
            
            if cursor == 0:
                break
        
        # Сортируем по последней активности
        sessions.sort(key=lambda s: s.last_activity, reverse=True)
        
        return SessionsListResponse(
            sessions=sessions,
            total=len(sessions)
        )
    
    async def revoke_session(self, user_id: int, session_id: str) -> bool:
        """Отозвать сессию"""
        key = f"session:{user_id}:{session_id}"
        deleted = await self.redis.delete(key)
        return deleted > 0
    
    async def _create_session(
        self,
        user_id: int,
        ip_address: Optional[str],
        user_agent: Optional[str],
        remember_me: bool
    ) -> str:
        """Создать новую сессию"""
        session_id = secrets.token_urlsafe(32)
        
        session_data = {
            'session_id': session_id,
            'user_id': user_id,
            'ip_address': ip_address,
            'user_agent': user_agent,
            'created_at': datetime.utcnow().isoformat(),
            'last_activity': datetime.utcnow().isoformat(),
            'remember_me': remember_me
        }
        
        ttl = 30 * 24 * 3600 if remember_me else 24 * 3600
        await self.redis.setex(
            f"session:{user_id}:{session_id}",
            ttl,
            json.dumps(session_data)
        )
        
        active_sessions_gauge.inc()
        
        return session_id
    
    async def _get_user_permissions(
        self,
        conn,
        user_id: int,
        role: str
    ) -> List[Permission]:
        """Получить все разрешения пользователя"""
        base_permissions = ROLE_PERMISSIONS.get(UserRole(role), [])
        
        custom_rows = await conn.fetch("""
            SELECT permission FROM user_permissions WHERE user_id = $1
        """, user_id)
        custom_permissions = [Permission(row['permission']) for row in custom_rows]
        
        all_permissions = set(base_permissions) | set(custom_permissions)
        
        return list(all_permissions)
    
    async def _log_audit(
        self,
        conn,
        user_id: Optional[int],
        action: str,
        entity_type: str,
        entity_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Записать аудит"""
        await conn.execute("""
            INSERT INTO audit_log (user_id, action, entity_type, entity_id, details)
            VALUES ($1, $2, $3, $4, $5)
        """, user_id, action, entity_type, entity_id, json.dumps(details) if details else None)
    
    # =============================================
    # Health check
    # =============================================
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        logger.info("AuthService остановлен")


# =============================================
# Глобальные экземпляры
# =============================================
_user_service: Optional[UserService] = None
_auth_service: Optional[AuthService] = None


def get_user_service() -> UserService:
    """Получить глобальный экземпляр UserService"""
    global _user_service
    if _user_service is None:
        raise RuntimeError("UserService не инициализирован")
    return _user_service


def get_auth_service() -> AuthService:
    """Получить глобальный экземпляр AuthService"""
    global _auth_service
    if _auth_service is None:
        raise RuntimeError("AuthService не инициализирован")
    return _auth_service


def set_user_service(service: UserService) -> None:
    """Установить глобальный экземпляр UserService"""
    global _user_service
    _user_service = service


def set_auth_service(service: AuthService) -> None:
    """Установить глобальный экземпляр AuthService"""
    global _auth_service
    _auth_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "UserService",
    "AuthService",
    "UserError",
    "UserNotFoundError",
    "UserAlreadyExistsError",
    "InvalidCredentialsError",
    "AccountDisabledError",
    "AccountLockedError",
    "InvalidTokenError",
    "TokenExpiredError",
    "TOTPError",
    "get_user_service",
    "get_auth_service",
    "set_user_service",
    "set_auth_service",
]
