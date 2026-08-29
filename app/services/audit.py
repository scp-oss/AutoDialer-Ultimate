#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис аудита
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Записи аудит-событий
- Получения и фильтрации аудит-логов
- Экспорта аудит-логов
- Статистики аудита
- Очистки старых записей
"""

import json
import csv
import io
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any, Tuple

from app.core.config import settings
from app.core.logger import logger, AuditLogger as CoreAuditLogger
from app.core.database import ConnectionPool
from app.models.audit import (
    AuditAction, AuditEntityType, AuditSeverity,
    AuditLogResponse, AuditLogDetailResponse, AuditLogListResponse,
    AuditLogFilter, AuditStatsResponse, AuditUserStatsResponse,
    AuditEntityStatsResponse, AuditExportRequest, AuditExportResponse,
    AuditExportStatusResponse, AuditCleanupRequest, AuditCleanupResponse
)
from prometheus_client import Counter, Gauge, Histogram


# =============================================
# Метрики
# =============================================
audit_events_counter = Counter(
    'autodialer_audit_events_total',
    'Total audit events',
    ['action', 'severity', 'status']
)
audit_export_counter = Counter(
    'autodialer_audit_exports_total',
    'Total audit exports',
    ['format']
)
audit_cleanup_counter = Counter(
    'autodialer_audit_cleanup_total',
    'Total audit records cleaned up'
)
audit_records_gauge = Gauge(
    'autodialer_audit_records',
    'Current audit records count'
)


# =============================================
# Исключения
# =============================================
class AuditError(Exception):
    """Базовое исключение сервиса аудита"""
    pass


class AuditLogNotFoundError(AuditError):
    """Запись аудита не найдена"""
    pass


# =============================================
# Сервис аудита
# =============================================
class AuditService:
    """
    Сервис аудита.
    
    Отвечает за:
    - Запись аудит-событий
    - Получение и фильтрацию логов
    - Экспорт
    - Статистику
    - Очистку старых записей
    """
    
    # entity_name в audit_log - как и username - не заполняется ни одним
    # из _log_audit(): все они пишут только entity_id. Без этого UI мог
    # показать в лучшем случае "Обзвон №12", никогда настоящее имя -
    # резолвим его по entity_type на чтении, тем же способом, что и
    # username выше. Покрывает самые частые типы сущностей в журнале;
    # для остальных (setting, api_key, system и т.п.) entity_id либо не
    # имеет смысла, либо в details и так достаточно контекста.
    # Без префикса audit_log./алиаса нарочно: entity_id внутри подзапросов
    # ни одна из campaigns/contacts/users/blacklist не содержит сама по
    # себе, так что Postgres однозначно резолвит его как коррелированную
    # ссылку на внешний запрос - работает что с "FROM audit_log", что с
    # "FROM audit_log a" без переписывания под конкретный алиас.
    _ENTITY_NAME_SQL = """
        COALESCE(
            entity_name,
            CASE entity_type
                WHEN 'campaign' THEN (SELECT name FROM campaigns WHERE id = entity_id)
                WHEN 'contact' THEN (SELECT phone FROM contacts WHERE id = entity_id)
                WHEN 'user' THEN (SELECT username FROM users WHERE id = entity_id)
                WHEN 'blacklist' THEN (SELECT phone FROM blacklist WHERE id = entity_id)
            END
        )
    """

    def __init__(self, db_pool: ConnectionPool):
        self.db_pool = db_pool
        self.core_logger = CoreAuditLogger()

        logger.info("AuditService инициализирован")
    
    # =============================================
    # Запись событий
    # =============================================
    async def log(
        self,
        action: AuditAction,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        user_role: Optional[str] = None,
        entity_type: Optional[AuditEntityType] = None,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        changes: Optional[Dict[str, Any]] = None,
        severity: AuditSeverity = AuditSeverity.INFO,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_method: Optional[str] = None,
        request_path: Optional[str] = None,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Записать аудит-событие.
        
        Args:
            action: Действие
            user_id: ID пользователя
            username: Имя пользователя
            user_role: Роль пользователя
            entity_type: Тип сущности
            entity_id: ID сущности
            entity_name: Имя сущности
            details: Детали
            changes: Изменения (было/стало)
            severity: Важность
            ip_address: IP адрес
            user_agent: User Agent
            request_method: HTTP метод
            request_path: Путь запроса
            correlation_id: Correlation ID
            request_id: Request ID
            session_id: Session ID
            status: Статус (success/failed)
            error_message: Сообщение об ошибке
            metadata: Метаданные
        
        Returns:
            ID созданной записи
        """
        # Определяем важность для критических действий
        if severity == AuditSeverity.INFO:
            if action in [
                AuditAction.SYSTEM_DISABLED,
                AuditAction.USER_DELETED,
                AuditAction.CAMPAIGN_DELETED
            ]:
                severity = AuditSeverity.WARNING
            elif action in [
                AuditAction.SYSTEM_CONFIG_CHANGED,
                AuditAction.ROLE_CHANGED
            ]:
                severity = AuditSeverity.CRITICAL
        
        async with self.db_pool.acquire() as conn:
            log_id = await conn.fetchval("""
                INSERT INTO audit_log (
                    user_id, username, user_role,
                    action, severity,
                    entity_type, entity_id, entity_name,
                    details, changes,
                    ip_address, user_agent,
                    request_method, request_path,
                    correlation_id, request_id, session_id,
                    status, error_message,
                    metadata, created_at
                ) VALUES (
                    $1, $2, $3,
                    $4, $5,
                    $6, $7, $8,
                    $9, $10,
                    $11, $12,
                    $13, $14,
                    $15, $16, $17,
                    $18, $19,
                    $20, NOW()
                )
                RETURNING id
            """,
                user_id,
                username,
                user_role,
                action.value if action else None,
                severity.value,
                entity_type.value if entity_type else None,
                entity_id,
                entity_name,
                json.dumps(details) if details else None,
                json.dumps(changes) if changes else None,
                ip_address,
                user_agent,
                request_method,
                request_path,
                correlation_id,
                request_id,
                session_id,
                status,
                error_message,
                json.dumps(metadata) if metadata else None
            )
        
        # Метрики
        audit_events_counter.labels(
            action=action.value if action else "unknown",
            severity=severity.value,
            status=status
        ).inc()
        
        # Логируем через core logger
        self.core_logger.log(
            action=action.value if action else "unknown",
            user_id=user_id,
            username=username,
            entity_type=entity_type.value if entity_type else None,
            entity_id=entity_id,
            details=details
        )
        
        return log_id
    
    async def log_batch(
        self,
        events: List[Dict[str, Any]]
    ) -> int:
        """
        Записать несколько событий аудита.
        
        Args:
            events: Список событий
        
        Returns:
            Количество записанных событий
        """
        if not events:
            return 0
        
        async with self.db_pool.acquire() as conn:
            count = 0
            for event in events:
                try:
                    await conn.execute("""
                        INSERT INTO audit_log (
                            user_id, username, user_role,
                            action, severity,
                            entity_type, entity_id, entity_name,
                            details, changes,
                            ip_address, user_agent,
                            request_method, request_path,
                            correlation_id, request_id, session_id,
                            status, error_message,
                            metadata, created_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, NOW()
                        )
                    """,
                        event.get('user_id'),
                        event.get('username'),
                        event.get('user_role'),
                        event.get('action'),
                        event.get('severity', 'info'),
                        event.get('entity_type'),
                        event.get('entity_id'),
                        event.get('entity_name'),
                        json.dumps(event.get('details')) if event.get('details') else None,
                        json.dumps(event.get('changes')) if event.get('changes') else None,
                        event.get('ip_address'),
                        event.get('user_agent'),
                        event.get('request_method'),
                        event.get('request_path'),
                        event.get('correlation_id'),
                        event.get('request_id'),
                        event.get('session_id'),
                        event.get('status', 'success'),
                        event.get('error_message'),
                        json.dumps(event.get('metadata')) if event.get('metadata') else None
                    )
                    count += 1
                except Exception as e:
                    logger.error(f"Ошибка записи batch аудита: {e}")
            
            return count
    
    # =============================================
    # Получение данных
    # =============================================
    async def get_audit_log(self, log_id: int) -> Optional[AuditLogDetailResponse]:
        """Получить запись аудита по ID"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT
                    a.id, a.user_id,
                    COALESCE(a.username, u.username) as username,
                    COALESCE(a.user_role, u.role) as user_role,
                    a.action, a.severity, a.entity_type, a.entity_id,
                    {self._ENTITY_NAME_SQL} as entity_name,
                    a.details, a.changes, a.ip_address, a.user_agent,
                    a.request_method, a.request_path,
                    a.correlation_id, a.request_id, a.session_id,
                    a.status, a.error_message, a.metadata, a.created_at,
                    u.email as user_email,
                    u.full_name as user_full_name
                FROM audit_log a
                LEFT JOIN users u ON a.user_id = u.id
                WHERE a.id = $1
            """, log_id)

            if not row:
                return None

            # Получаем связанные события. Та же проблема с username, что и
            # в основном запросе выше (см. list_audit_logs()) - подтягиваем
            # его тем же способом через подзапрос, раз тут нет JOIN.
            related_events = []
            if row['correlation_id']:
                related_rows = await conn.fetch(f"""
                    SELECT
                        id, user_id,
                        COALESCE(username, (SELECT username FROM users WHERE users.id = audit_log.user_id)) as username,
                        COALESCE(user_role, (SELECT role FROM users WHERE users.id = audit_log.user_id)) as user_role,
                        action, severity, entity_type, entity_id,
                        {self._ENTITY_NAME_SQL} as entity_name,
                        details, changes, ip_address, user_agent,
                        request_method, request_path,
                        correlation_id, request_id, session_id,
                        status, error_message, metadata, created_at
                    FROM audit_log
                    WHERE correlation_id = $1 AND id != $2
                    ORDER BY created_at
                    LIMIT 10
                """, row['correlation_id'], log_id)
                
                for rel_row in related_rows:
                    related_events.append(self._row_to_response(rel_row))
            
            return AuditLogDetailResponse(
                id=row['id'],
                user_id=row['user_id'],
                username=row['username'],
                user_role=row['user_role'],
                action=self._safe_enum(AuditAction, row['action'], AuditAction.OTHER),
                severity=self._safe_enum(AuditSeverity, row['severity'], AuditSeverity.INFO),
                entity_type=self._safe_enum(AuditEntityType, row['entity_type']),
                entity_id=row['entity_id'],
                entity_name=row['entity_name'],
                details=json.loads(row['details']) if row['details'] else None,
                changes=json.loads(row['changes']) if row['changes'] else None,
                ip_address=str(row['ip_address']) if row['ip_address'] else None,
                user_agent=row['user_agent'],
                request_method=row['request_method'],
                request_path=row['request_path'],
                correlation_id=row['correlation_id'],
                request_id=row['request_id'],
                session_id=row['session_id'],
                status=row['status'] or "success",
                error_message=row['error_message'],
                metadata=json.loads(row['metadata']) if row['metadata'] else {},
                created_at=row['created_at'],
                user_email=row['user_email'],
                user_full_name=row['user_full_name'],
                related_events=related_events
            )
    
    async def list_audit_logs(
        self,
        page: int = 1,
        page_size: int = 50,
        filter_params: Optional[AuditLogFilter] = None
    ) -> AuditLogListResponse:
        """
        Получить список записей аудита с фильтрацией.
        
        Args:
            page: Номер страницы
            page_size: Размер страницы
            filter_params: Параметры фильтрации
        
        Returns:
            Список записей
        """
        offset = (page - 1) * page_size
        
        async with self.db_pool.acquire() as conn:
            where_conditions = []
            params = []
            param_idx = 1
            
            if filter_params:
                if filter_params.user_id is not None:
                    where_conditions.append(f"user_id = ${param_idx}")
                    params.append(filter_params.user_id)
                    param_idx += 1
                
                if filter_params.username:
                    # Каждый из ~8 отдельных _log_audit() по сервисам
                    # (campaign.py, system.py, settings.py, contact.py,
                    # blacklist.py, call_result.py, incoming.py, user.py)
                    # пишет в audit_log только user_id - username там
                    # ВСЕГДА NULL, ни один из них не заполняет эту колонку.
                    # Фильтр по чистому audit_log.username поэтому не находил
                    # вообще ничего, ни для одной существующей записи -
                    # подтянуть реальный логин можно только через сам
                    # user_id, отдельным подзапросом к users.
                    where_conditions.append(f"""
                        COALESCE(username, (SELECT username FROM users WHERE users.id = audit_log.user_id))
                        ILIKE ${param_idx}
                    """)
                    params.append(f"%{filter_params.username}%")
                    param_idx += 1

                if filter_params.user_role:
                    where_conditions.append(f"""
                        COALESCE(user_role, (SELECT role FROM users WHERE users.id = audit_log.user_id))
                        = ${param_idx}
                    """)
                    params.append(filter_params.user_role)
                    param_idx += 1

                if filter_params.user_actions_only:
                    where_conditions.append("user_id IS NOT NULL")

                if filter_params.action:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.action))])
                    where_conditions.append(f"action IN ({placeholders})")
                    params.extend(list(filter_params.action))
                    param_idx += len(filter_params.action)

                if filter_params.severity:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.severity))])
                    where_conditions.append(f"severity IN ({placeholders})")
                    params.extend(list(filter_params.severity))
                    param_idx += len(filter_params.severity)

                if filter_params.entity_type:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.entity_type))])
                    where_conditions.append(f"entity_type IN ({placeholders})")
                    params.extend(list(filter_params.entity_type))
                    param_idx += len(filter_params.entity_type)
                
                if filter_params.entity_id is not None:
                    where_conditions.append(f"entity_id = ${param_idx}")
                    params.append(filter_params.entity_id)
                    param_idx += 1
                
                if filter_params.status:
                    where_conditions.append(f"status = ${param_idx}")
                    params.append(filter_params.status)
                    param_idx += 1
                
                if filter_params.ip_address:
                    where_conditions.append(f"ip_address = ${param_idx}")
                    params.append(filter_params.ip_address)
                    param_idx += 1
                
                if filter_params.correlation_id:
                    where_conditions.append(f"correlation_id = ${param_idx}")
                    params.append(filter_params.correlation_id)
                    param_idx += 1
                
                if filter_params.from_date:
                    where_conditions.append(f"created_at::date >= ${param_idx}")
                    params.append(filter_params.from_date)
                    param_idx += 1
                
                if filter_params.to_date:
                    where_conditions.append(f"created_at::date <= ${param_idx}")
                    params.append(filter_params.to_date)
                    param_idx += 1
                
                if filter_params.search:
                    where_conditions.append(f"""
                        (details::text ILIKE ${param_idx} 
                         OR changes::text ILIKE ${param_idx}
                         OR entity_name ILIKE ${param_idx})
                    """)
                    params.append(f"%{filter_params.search}%")
                    param_idx += 1
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            # Общее количество
            count_query = f"SELECT COUNT(*) FROM audit_log {where_clause}"
            total = await conn.fetchval(count_query, *params)
            
            # Сводка
            summary = await self._get_summary(conn, where_clause, params)
            
            # Сортировка
            sort_by = filter_params.sort_by if filter_params else "created_at"
            sort_order = filter_params.sort_order if filter_params else "DESC"
            
            # Получаем данные. username/user_role явно перечислены с
            # COALESCE вместо простого "*" - см. комментарий выше про
            # _log_audit(): без этого КАЖДАЯ запись в журнале показывала бы
            # "system" в UI (App.audit.js делает log.username || 'system'),
            # даже когда это совершенно реальное действие живого админа с
            # заполненным user_id - подтверждено живьём на скриншоте
            # пользователя ("Запуск обзвона"/"Изменение настройки" от
            # username=system, ID: 1 - хотя это тот же самый залогиненный
            # админ).
            query = f"""
                SELECT
                    id, user_id,
                    COALESCE(username, (SELECT username FROM users WHERE users.id = audit_log.user_id)) as username,
                    COALESCE(user_role, (SELECT role FROM users WHERE users.id = audit_log.user_id)) as user_role,
                    action, severity, entity_type, entity_id,
                    {self._ENTITY_NAME_SQL} as entity_name,
                    details, changes, ip_address, user_agent,
                    request_method, request_path,
                    correlation_id, request_id, session_id,
                    status, error_message, metadata, created_at
                FROM audit_log
                {where_clause}
                ORDER BY {sort_by} {sort_order}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([page_size, offset])
            
            rows = await conn.fetch(query, *params)
            
            items = [self._row_to_response(row) for row in rows]
            
            return AuditLogListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=(total + page_size - 1) // page_size,
                summary=summary
            )
    
    async def get_audit_by_entity(
        self,
        entity_type: AuditEntityType,
        entity_id: int,
        limit: int = 100
    ) -> List[AuditLogResponse]:
        """
        Получить аудит по сущности.
        
        Args:
            entity_type: Тип сущности
            entity_id: ID сущности
            limit: Максимум записей
        
        Returns:
            Список записей
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM audit_log
                WHERE entity_type = $1 AND entity_id = $2
                ORDER BY created_at DESC
                LIMIT $3
            """, entity_type.value, entity_id, limit)
            
            return [self._row_to_response(row) for row in rows]
    
    async def get_audit_by_user(
        self,
        user_id: int,
        limit: int = 100
    ) -> List[AuditLogResponse]:
        """
        Получить аудит по пользователю.
        
        Args:
            user_id: ID пользователя
            limit: Максимум записей
        
        Returns:
            Список записей
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM audit_log
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, user_id, limit)
            
            return [self._row_to_response(row) for row in rows]
    
    # =============================================
    # Статистика
    # =============================================
    async def get_stats(self, days: int = 30) -> AuditStatsResponse:
        """
        Получить статистику аудита.
        
        Args:
            days: Период в днях
        
        Returns:
            Статистика
        """
        async with self.db_pool.acquire() as conn:
            from_date = date.today() - timedelta(days=days)
            to_date = date.today()
            
            # Общая статистика
            totals = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'success' THEN 1 END) as success,
                    COUNT(CASE WHEN status != 'success' THEN 1 END) as failed
                FROM audit_log
                WHERE created_at::date >= $1 AND created_at::date <= $2
            """, from_date, to_date)
            
            # По важности
            severity_rows = await conn.fetch("""
                SELECT severity, COUNT(*) as count
                FROM audit_log
                WHERE created_at::date >= $1 AND created_at::date <= $2
                GROUP BY severity
            """, from_date, to_date)
            by_severity = {row['severity']: row['count'] for row in severity_rows}
            
            # Топ действий
            top_actions = await self._get_top_actions(conn, from_date, to_date)
            
            # Топ пользователей
            top_users = await self._get_top_users(conn, from_date, to_date)
            
            # По типам сущностей
            entity_rows = await conn.fetch("""
                SELECT entity_type, COUNT(*) as count
                FROM audit_log
                WHERE created_at::date >= $1 AND created_at::date <= $2
                AND entity_type IS NOT NULL
                GROUP BY entity_type
            """, from_date, to_date)
            by_entity_type = {row['entity_type']: row['count'] for row in entity_rows}
            
            # Топ IP
            top_ips = await self._get_top_ips(conn, from_date, to_date)
            
            # По дням
            daily_events = await self._get_daily_events(conn, from_date, to_date)
            
            # По часам
            hourly_events = await self._get_hourly_events(conn, from_date, to_date)
            
            return AuditStatsResponse(
                period_days=days,
                from_date=from_date,
                to_date=to_date,
                total_events=totals['total'] or 0,
                success_events=totals['success'] or 0,
                failed_events=totals['failed'] or 0,
                by_severity=by_severity,
                top_actions=top_actions,
                top_users=top_users,
                by_entity_type=by_entity_type,
                top_ips=top_ips,
                daily_events=daily_events,
                hourly_events=hourly_events
            )
    
    async def get_user_stats(
        self,
        user_id: int,
        days: int = 30
    ) -> Optional[AuditUserStatsResponse]:
        """
        Получить статистику аудита по пользователю.
        
        Args:
            user_id: ID пользователя
            days: Период в днях
        
        Returns:
            Статистика пользователя
        """
        async with self.db_pool.acquire() as conn:
            # Проверяем существование пользователя
            user = await conn.fetchrow("""
                SELECT username, full_name, role FROM users WHERE id = $1
            """, user_id)
            
            if not user:
                return None
            
            from_date = date.today() - timedelta(days=days)
            
            totals = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    MIN(created_at) as first_action,
                    MAX(created_at) as last_action
                FROM audit_log
                WHERE user_id = $1 AND created_at::date >= $2
            """, user_id, from_date)
            
            if not totals or totals['total'] == 0:
                return AuditUserStatsResponse(
                    user_id=user_id,
                    username=user['username'],
                    full_name=user['full_name'],
                    role=user['role'],
                    total_actions=0
                )
            
            # По действиям
            action_rows = await conn.fetch("""
                SELECT action, COUNT(*) as count
                FROM audit_log
                WHERE user_id = $1 AND created_at::date >= $2
                GROUP BY action
                ORDER BY count DESC
            """, user_id, from_date)
            actions_breakdown = {row['action']: row['count'] for row in action_rows}
            
            # Сессии
            session_stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_sessions,
                    AVG(session_duration) as avg_duration
                FROM (
                    SELECT
                        EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at)))/60 as session_duration
                    FROM audit_log
                    WHERE user_id = $1 AND created_at::date >= $2 AND session_id IS NOT NULL
                    GROUP BY session_id
                ) sessions
            """, user_id, from_date)
            
            # Уникальные IP
            ip_count = await conn.fetchval("""
                SELECT COUNT(DISTINCT ip_address) FROM audit_log
                WHERE user_id = $1 AND created_at::date >= $2 AND ip_address IS NOT NULL
            """, user_id, from_date)
            
            # Топ IP
            top_ips = await self._get_top_ips_for_user(conn, user_id, from_date)
            
            # Устройства
            devices = await self._get_user_devices(conn, user_id, from_date)
            
            return AuditUserStatsResponse(
                user_id=user_id,
                username=user['username'],
                full_name=user['full_name'],
                role=user['role'],
                total_actions=totals['total'],
                first_action=totals['first_action'],
                last_action=totals['last_action'],
                actions_breakdown=actions_breakdown,
                total_sessions=session_stats['total_sessions'] if session_stats else 0,
                avg_session_duration=round(session_stats['avg_duration'], 2) if session_stats and session_stats['avg_duration'] else None,
                unique_ips=ip_count or 0,
                top_ips=top_ips,
                devices=devices
            )
    
    async def get_entity_stats(
        self,
        entity_type: AuditEntityType,
        entity_id: int
    ) -> Optional[AuditEntityStatsResponse]:
        """
        Получить статистику аудита по сущности.
        
        Args:
            entity_type: Тип сущности
            entity_id: ID сущности
        
        Returns:
            Статистика сущности
        """
        async with self.db_pool.acquire() as conn:
            totals = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    entity_name
                FROM audit_log
                WHERE entity_type = $1 AND entity_id = $2
                GROUP BY entity_name
            """, entity_type.value, entity_id)
            
            if not totals:
                return None
            
            # По действиям
            action_rows = await conn.fetch("""
                SELECT action, COUNT(*) as count
                FROM audit_log
                WHERE entity_type = $1 AND entity_id = $2
                GROUP BY action
                ORDER BY count DESC
            """, entity_type.value, entity_id)
            actions_breakdown = {row['action']: row['count'] for row in action_rows}
            
            # Пользователи
            user_rows = await conn.fetch("""
                SELECT user_id, username, COUNT(*) as count
                FROM audit_log
                WHERE entity_type = $1 AND entity_id = $2 AND user_id IS NOT NULL
                GROUP BY user_id, username
                ORDER BY count DESC
            """, entity_type.value, entity_id)
            users_involved = [dict(row) for row in user_rows]
            
            # Временная шкала
            timeline = await self._get_entity_timeline(conn, entity_type, entity_id)
            
            return AuditEntityStatsResponse(
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=totals['entity_name'],
                total_events=totals['total'],
                actions_breakdown=actions_breakdown,
                users_involved=users_involved,
                timeline=timeline,
                related_entities=[]
            )
    
    # =============================================
    # Экспорт
    # =============================================
    async def export_audit(
        self,
        request: AuditExportRequest,
        user_id: Optional[int] = None
    ) -> AuditExportResponse:
        """
        Запустить экспорт аудита.
        
        Args:
            request: Параметры экспорта
            user_id: ID пользователя
        
        Returns:
            Информация о задаче экспорта
        """
        import uuid
        from datetime import datetime, timedelta
        
        task_id = str(uuid.uuid4())
        
        # Сохраняем задачу в Redis (или БД)
        # TODO: Реализовать фоновый экспорт через очередь
        
        audit_export_counter.labels(format=request.format).inc()
        
        logger.info(f"Запущен экспорт аудита: {task_id}")
        
        return AuditExportResponse(
            task_id=task_id,
            status="pending",
            estimated_records=request.max_records,
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
    
    async def export_to_csv(
        self,
        filter_params: Optional[AuditLogFilter] = None,
        max_records: int = 10000
    ) -> bytes:
        """
        Экспортировать в CSV.
        
        Args:
            filter_params: Фильтр
            max_records: Максимум записей
        
        Returns:
            CSV данные
        """
        response = await self.list_audit_logs(
            page=1,
            page_size=max_records,
            filter_params=filter_params
        )
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow([
            'id', 'created_at', 'user_id', 'username', 'user_role',
            'action', 'severity', 'status',
            'entity_type', 'entity_id', 'entity_name',
            'ip_address', 'user_agent', 'request_method', 'request_path',
            'correlation_id', 'details', 'changes'
        ])
        
        for item in response.items:
            writer.writerow([
                item.id,
                item.created_at.isoformat() if item.created_at else '',
                item.user_id or '',
                item.username or '',
                item.user_role or '',
                item.action if item.action else '',
                item.severity if item.severity else '',
                item.status,
                item.entity_type if item.entity_type else '',
                item.entity_id or '',
                item.entity_name or '',
                item.ip_address or '',
                item.user_agent or '',
                item.request_method or '',
                item.request_path or '',
                item.correlation_id or '',
                json.dumps(item.details, ensure_ascii=False) if item.details else '',
                json.dumps(item.changes, ensure_ascii=False) if item.changes else ''
            ])
        
        return output.getvalue().encode('utf-8-sig')
    
    async def export_to_json(
        self,
        filter_params: Optional[AuditLogFilter] = None,
        max_records: int = 10000
    ) -> bytes:
        """
        Экспортировать в JSON.
        
        Args:
            filter_params: Фильтр
            max_records: Максимум записей
        
        Returns:
            JSON данные
        """
        response = await self.list_audit_logs(
            page=1,
            page_size=max_records,
            filter_params=filter_params
        )
        
        data = {
            "exported_at": datetime.utcnow().isoformat(),
            "total": response.total,
            "items": [
                {
                    "id": item.id,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "user_id": item.user_id,
                    "username": item.username,
                    "user_role": item.user_role,
                    "action": item.action if item.action else None,
                    "severity": item.severity if item.severity else None,
                    "status": item.status,
                    "entity_type": item.entity_type if item.entity_type else None,
                    "entity_id": item.entity_id,
                    "entity_name": item.entity_name,
                    "ip_address": item.ip_address,
                    "user_agent": item.user_agent,
                    "request_method": item.request_method,
                    "request_path": item.request_path,
                    "correlation_id": item.correlation_id,
                    "request_id": item.request_id,
                    "session_id": item.session_id,
                    "details": item.details,
                    "changes": item.changes,
                    "error_message": item.error_message
                }
                for item in response.items
            ]
        }
        
        return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    
    # =============================================
    # Очистка
    # =============================================
    async def cleanup_old_logs(
        self,
        older_than_days: int,
        dry_run: bool = True,
        user_id: Optional[int] = None
    ) -> AuditCleanupResponse:
        """
        Очистить старые аудит-логи.
        
        Args:
            older_than_days: Старше N дней
            dry_run: Только подсчёт
            user_id: ID пользователя
        
        Returns:
            Результат очистки
        """
        async with self.db_pool.acquire() as conn:
            # Подсчитываем количество
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM audit_log
                WHERE created_at < NOW() - INTERVAL '1 day' * $1
            """, older_than_days)
            
            if dry_run:
                return AuditCleanupResponse(
                    records_to_delete=count or 0,
                    deleted=0,
                    dry_run=True,
                    message=f"Найдено {count} записей для удаления"
                )
            
            # Удаляем
            if count > 0:
                # Удаляем батчами
                batch_size = 10000
                deleted = 0
                
                while True:
                    result = await conn.execute("""
                        DELETE FROM audit_log
                        WHERE id IN (
                            SELECT id FROM audit_log
                            WHERE created_at < NOW() - INTERVAL '1 day' * $1
                            LIMIT $2
                        )
                    """, older_than_days, batch_size)
                    
                    import re
                    match = re.search(r'DELETE (\d+)', result)
                    batch_deleted = int(match.group(1)) if match else 0
                    deleted += batch_deleted
                    
                    if batch_deleted < batch_size:
                        break
                
                audit_cleanup_counter.inc(deleted)
                
                # Логируем
                await self.log(
                    action=AuditAction.OTHER,
                    user_id=user_id,
                    entity_type=AuditEntityType.SYSTEM,
                    details={"cleaned": deleted, "older_than_days": older_than_days},
                    severity=AuditSeverity.INFO
                )
                
                logger.info(f"Очищено {deleted} старых аудит-логов")
                
                return AuditCleanupResponse(
                    records_to_delete=count,
                    deleted=deleted,
                    dry_run=False,
                    message=f"Удалено {deleted} записей"
                )
            
            return AuditCleanupResponse(
                records_to_delete=0,
                deleted=0,
                dry_run=False,
                message="Нет записей для удаления"
            )
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    @staticmethod
    def _safe_enum(enum_cls, value, default=None):
        """
        Безопасно привести строку из БД к enum-значению.

        action/entity_type в audit_log - обычные VARCHAR без FK/enum-
        ограничения в БД (severity хотя бы прикрыт CHECK-констрейнтом),
        так что ничто не мешает какому-нибудь вызову self._log_audit(...)
        записать строку, которую забыли добавить в AuditAction/
        AuditEntityType - что и произошло: 11 реальных action'ов
        (contacts_merged, incoming_call_updated, recording_deleted и
        т.д. - обычные повседневные операции, не редкий край) писались в
        БД, но отсутствовали в enum. Один такой рядок делал
        AuditAction(row['action']) необработанным ValueError - и это
        валило ВЕСЬ список аудита для всех страниц и всех фильтров сразу
        (не только эту одну запись), подтверждено воспроизведением на
        реальной схеме. Недостающие значения добавлены в enum, но это
        по-прежнему единственная линия обороны от следующего такого же
        рассинхрона - падать из-за одной строки чтения умолчания
        недопустимо для журнала аудита, поэтому теперь неизвестное
        значение просто получает запасной ярлык вместо краха.
        """
        if not value:
            return default
        try:
            return enum_cls(value)
        except ValueError:
            logger.warning(f"Неизвестное значение {value!r} для {enum_cls.__name__} в audit_log")
            return default

    def _row_to_response(self, row) -> AuditLogResponse:
        """Преобразовать строку БД в ответ"""
        return AuditLogResponse(
            id=row['id'],
            user_id=row['user_id'],
            username=row['username'],
            user_role=row['user_role'],
            action=self._safe_enum(AuditAction, row['action'], AuditAction.OTHER),
            severity=self._safe_enum(AuditSeverity, row['severity'], AuditSeverity.INFO),
            entity_type=self._safe_enum(AuditEntityType, row['entity_type']),
            entity_id=row['entity_id'],
            entity_name=row['entity_name'],
            details=json.loads(row['details']) if row['details'] else None,
            changes=json.loads(row['changes']) if row['changes'] else None,
            ip_address=str(row['ip_address']) if row['ip_address'] else None,
            user_agent=row['user_agent'],
            request_method=row['request_method'],
            request_path=row['request_path'],
            correlation_id=row['correlation_id'],
            request_id=row['request_id'],
            session_id=row['session_id'],
            status=row['status'] or "success",
            error_message=row['error_message'],
            metadata=json.loads(row['metadata']) if row['metadata'] else {},
            created_at=row['created_at']
        )
    
    async def _get_summary(
        self,
        conn,
        where_clause: str,
        params: List
    ) -> Dict[str, Any]:
        """Получить сводку по запросу"""
        summary = {}
        
        # По действиям
        action_rows = await conn.fetch(f"""
            SELECT action, COUNT(*) as count
            FROM audit_log
            {where_clause}
            GROUP BY action
            ORDER BY count DESC
            LIMIT 10
        """, *params)
        summary['top_actions'] = [{'action': row['action'], 'count': row['count']} for row in action_rows]
        
        # По статусам
        status_rows = await conn.fetch(f"""
            SELECT status, COUNT(*) as count
            FROM audit_log
            {where_clause}
            GROUP BY status
        """, *params)
        summary['by_status'] = {row['status']: row['count'] for row in status_rows}
        
        return summary
    
    async def _get_top_actions(
        self,
        conn,
        from_date: date,
        to_date: date,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT action, COUNT(*) as count
            FROM audit_log
            WHERE created_at::date >= $1 AND created_at::date <= $2
            GROUP BY action
            ORDER BY count DESC
            LIMIT $3
        """, from_date, to_date, limit)
        return [{'action': row['action'], 'count': row['count']} for row in rows]
    
    async def _get_top_users(
        self,
        conn,
        from_date: date,
        to_date: date,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT user_id, username, COUNT(*) as count
            FROM audit_log
            WHERE created_at::date >= $1 AND created_at::date <= $2
            AND user_id IS NOT NULL
            GROUP BY user_id, username
            ORDER BY count DESC
            LIMIT $3
        """, from_date, to_date, limit)
        return [dict(row) for row in rows]
    
    async def _get_top_ips(
        self,
        conn,
        from_date: date,
        to_date: date,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT ip_address, COUNT(*) as count
            FROM audit_log
            WHERE created_at::date >= $1 AND created_at::date <= $2
            AND ip_address IS NOT NULL
            GROUP BY ip_address
            ORDER BY count DESC
            LIMIT $3
        """, from_date, to_date, limit)
        return [dict(row) for row in rows]
    
    async def _get_daily_events(
        self,
        conn,
        from_date: date,
        to_date: date
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT 
                created_at::date as date,
                COUNT(*) as count,
                COUNT(CASE WHEN status = 'success' THEN 1 END) as success,
                COUNT(CASE WHEN status != 'success' THEN 1 END) as failed
            FROM audit_log
            WHERE created_at::date >= $1 AND created_at::date <= $2
            GROUP BY created_at::date
            ORDER BY date DESC
        """, from_date, to_date)
        return [dict(row) for row in rows]
    
    async def _get_hourly_events(
        self,
        conn,
        from_date: date,
        to_date: date
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT 
                EXTRACT(HOUR FROM created_at) as hour,
                COUNT(*) as count
            FROM audit_log
            WHERE created_at::date >= $1 AND created_at::date <= $2
            GROUP BY hour
            ORDER BY hour
        """, from_date, to_date)
        return [{'hour': int(row['hour']), 'count': row['count']} for row in rows]
    
    async def _get_top_ips_for_user(
        self,
        conn,
        user_id: int,
        from_date: date,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT ip_address, COUNT(*) as count
            FROM audit_log
            WHERE user_id = $1 AND created_at::date >= $2 AND ip_address IS NOT NULL
            GROUP BY ip_address
            ORDER BY count DESC
            LIMIT $3
        """, user_id, from_date, limit)
        return [dict(row) for row in rows]
    
    async def _get_user_devices(
        self,
        conn,
        user_id: int,
        from_date: date
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT 
                user_agent,
                COUNT(*) as count,
                MAX(created_at) as last_used
            FROM audit_log
            WHERE user_id = $1 AND created_at::date >= $2 AND user_agent IS NOT NULL
            GROUP BY user_agent
            ORDER BY last_used DESC
        """, user_id, from_date)
        return [dict(row) for row in rows]
    
    async def _get_entity_timeline(
        self,
        conn,
        entity_type: AuditEntityType,
        entity_id: int,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT 
                action,
                username,
                details,
                changes,
                created_at
            FROM audit_log
            WHERE entity_type = $1 AND entity_id = $2
            ORDER BY created_at DESC
            LIMIT $3
        """, entity_type.value, entity_id, limit)
        return [dict(row) for row in rows]
    
    # =============================================
    # Health check
    # =============================================
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            # Получаем примерное количество записей
            count = await self.db_pool.fetchval("SELECT COUNT(*) FROM audit_log")
            audit_records_gauge.set(count or 0)
            
            return {
                "status": "healthy",
                "records_count": count or 0
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        logger.info("AuditService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_audit_service: Optional[AuditService] = None


def get_audit_service() -> AuditService:
    """Получить глобальный экземпляр AuditService"""
    global _audit_service
    if _audit_service is None:
        raise RuntimeError("AuditService не инициализирован")
    return _audit_service


def set_audit_service(service: AuditService) -> None:
    """Установить глобальный экземпляр AuditService"""
    global _audit_service
    _audit_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "AuditService",
    "AuditError",
    "AuditLogNotFoundError",
    "get_audit_service",
    "set_audit_service",
]
