#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления чёрным списком
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Добавления/удаления номеров из чёрного списка
- Проверки номеров
- Массового импорта/экспорта
- Автоматического добавления после неудачных звонков
- Статистики чёрного списка
"""

import re
import json
import csv
import io
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS
from app.models.blacklist import (
    BlacklistSource, BlacklistReason, BlacklistStatus,
    BlacklistAddRequest, BlacklistBulkAddRequest, BlacklistRemoveRequest,
    BlacklistResponse, BlacklistDetailResponse, BlacklistListResponse,
    BlacklistCheckResponse, BlacklistBulkCheckResponse,
    BlacklistBulkAddResponse, BlacklistRemoveResponse, BlacklistBulkRemoveResponse,
    BlacklistStatsResponse, BlacklistFilterRequest,
    normalize_phone
)
from app.utils.phone import format_phone_display as _format_phone_display_shared
from prometheus_client import Counter, Gauge


# =============================================
# Метрики
# =============================================
blacklist_added_counter = Counter(
    'autodialer_blacklist_added_total',
    'Total numbers added to blacklist',
    ['source', 'reason']
)
blacklist_removed_counter = Counter(
    'autodialer_blacklist_removed_total',
    'Total numbers removed from blacklist'
)
blacklist_checked_counter = Counter(
    'autodialer_blacklist_checked_total',
    'Total blacklist checks'
)
blacklist_size_gauge = Gauge(
    'autodialer_blacklist_size',
    'Current blacklist size'
)


# =============================================
# Исключения
# =============================================
class BlacklistError(Exception):
    """Базовое исключение сервиса чёрного списка"""
    pass


class BlacklistNotFoundError(BlacklistError):
    """Запись не найдена"""
    pass


class BlacklistAlreadyExistsError(BlacklistError):
    """Номер уже в чёрном списке"""
    pass


class BlacklistValidationError(BlacklistError):
    """Ошибка валидации"""
    pass


# =============================================
# Сервис чёрного списка
# =============================================
class BlacklistService:
    """
    Сервис управления чёрным списком.
    
    Отвечает за:
    - Добавление/удаление номеров
    - Проверку номеров
    - Массовые операции
    - Автоматическое добавление
    - Статистику
    """
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        
        # Настройки авто-блокировки
        self.auto_block_after_failures = 5
        self.auto_block_window_days = 7
        
        logger.info("BlacklistService инициализирован")
    
    # =============================================
    # Базовые операции
    # =============================================
    async def add_to_blacklist(
        self,
        request: BlacklistAddRequest,
        user_id: Optional[int] = None
    ) -> BlacklistResponse:
        """
        Добавить номер в чёрный список.
        
        Args:
            request: Данные для добавления
            user_id: ID пользователя
        
        Returns:
            Созданная запись
        """
        phone = normalize_phone(request.phone)
        if not phone:
            raise BlacklistValidationError(f"Неверный формат номера: {request.phone}")
        
        async with self.db_pool.acquire() as conn:
            # Проверяем существование
            existing = await conn.fetchrow("""
                SELECT id, status FROM blacklist WHERE phone = $1
            """, phone)
            
            if existing:
                if existing['status'] == BlacklistStatus.ACTIVE.value:
                    raise BlacklistAlreadyExistsError(f"Номер {phone} уже в чёрном списке")
                else:
                    # Реактивируем существующую запись
                    await conn.execute("""
                        UPDATE blacklist 
                        SET status = $1, 
                            reason = $2, 
                            reason_details = $3,
                            expires_at = $4,
                            source = $5,
                            notes = $6,
                            updated_at = NOW(),
                            removed_at = NULL,
                            removed_by = NULL,
                            removed_reason = NULL
                        WHERE id = $7
                    """,
                        BlacklistStatus.ACTIVE.value,
                        request.reason.value,
                        request.reason_details,
                        request.expires_at,
                        request.source.value,
                        request.notes,
                        existing['id']
                    )
                    blacklist_id = existing['id']
            else:
                # Создаём новую запись
                blacklist_id = await conn.fetchval("""
                    INSERT INTO blacklist (
                        phone, reason, reason_details,
                        expires_at, source, notes,
                        status, created_by, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
                    RETURNING id
                """,
                    phone,
                    request.reason.value,
                    request.reason_details,
                    request.expires_at,
                    request.source.value,
                    request.notes,
                    BlacklistStatus.ACTIVE.value,
                    user_id
                )
            
            # Добавляем теги
            if request.tags:
                await self._add_blacklist_tags(conn, blacklist_id, request.tags)
            
            # Обновляем контакт если есть
            await conn.execute("""
                UPDATE contacts 
                SET blacklisted = TRUE, 
                    blacklist_reason = $1,
                    updated_at = NOW()
                WHERE phone = $2
            """, request.reason.value, phone)
            
            # Добавляем в Redis
            await self.redis.add_to_blacklist(phone)
            
            # Логируем
            await self._log_audit(conn, user_id, 'blacklist_added', 'blacklist', blacklist_id, {
                'phone': phone,
                'reason': request.reason.value
            })
            
            # Получаем созданную запись
            entry = await self._get_blacklist_by_id(conn, blacklist_id)
        
        blacklist_added_counter.labels(
            source=request.source.value,
            reason=request.reason.value
        ).inc()
        blacklist_size_gauge.inc()
        
        logger.info(f"Номер добавлен в чёрный список: {phone} (причина: {request.reason.value})")
        
        return entry
    
    async def remove_from_blacklist(
        self,
        blacklist_id: int,
        user_id: Optional[int] = None,
        reason: Optional[str] = None
    ) -> BlacklistRemoveResponse:
        """
        Удалить номер из чёрного списка.
        
        Args:
            blacklist_id: ID записи
            user_id: ID пользователя
            reason: Причина удаления
        
        Returns:
            Результат удаления
        """
        async with self.db_pool.acquire() as conn:
            entry = await conn.fetchrow("""
                SELECT id, phone, status FROM blacklist WHERE id = $1
            """, blacklist_id)
            
            if not entry:
                raise BlacklistNotFoundError(f"Запись {blacklist_id} не найдена")
            
            if entry['status'] == BlacklistStatus.REMOVED.value:
                return BlacklistRemoveResponse(
                    success=False,
                    message="Запись уже удалена",
                    phone=entry['phone'],
                    removed=False
                )
            
            # Мягкое удаление
            await conn.execute("""
                UPDATE blacklist 
                SET status = $1,
                    removed_at = NOW(),
                    removed_by = $2,
                    removed_reason = $3,
                    updated_at = NOW()
                WHERE id = $4
            """, BlacklistStatus.REMOVED.value, user_id, reason, blacklist_id)
            
            # Обновляем контакт
            await conn.execute("""
                UPDATE contacts 
                SET blacklisted = FALSE, 
                    blacklist_reason = NULL,
                    updated_at = NOW()
                WHERE phone = $1
            """, entry['phone'])
            
            # Удаляем из Redis
            await self.redis.remove_from_blacklist(entry['phone'])
            
            # Логируем
            await self._log_audit(conn, user_id, 'blacklist_removed', 'blacklist', blacklist_id, {
                'phone': entry['phone'],
                'reason': reason
            })
        
        blacklist_removed_counter.inc()
        blacklist_size_gauge.dec()
        
        logger.info(f"Номер удалён из чёрного списка: {entry['phone']}")
        
        return BlacklistRemoveResponse(
            success=True,
            message="Номер удалён из чёрного списка",
            phone=entry['phone'],
            removed=True
        )
    
    async def remove_phone_from_blacklist(
        self,
        phone: str,
        user_id: Optional[int] = None,
        reason: Optional[str] = None
    ) -> BlacklistRemoveResponse:
        """
        Удалить номер из чёрного списка по номеру телефона.
        
        Args:
            phone: Номер телефона
            user_id: ID пользователя
            reason: Причина удаления
        
        Returns:
            Результат удаления
        """
        phone = normalize_phone(phone)
        if not phone:
            raise BlacklistValidationError(f"Неверный формат номера: {phone}")
        
        async with self.db_pool.acquire() as conn:
            entry = await conn.fetchrow("""
                SELECT id FROM blacklist WHERE phone = $1 AND status = 'active'
            """, phone)
            
            if not entry:
                return BlacklistRemoveResponse(
                    success=False,
                    message="Номер не найден в чёрном списке",
                    phone=phone,
                    removed=False
                )
            
            return await self.remove_from_blacklist(entry['id'], user_id, reason)
    
    async def check_phone(self, phone: str) -> BlacklistCheckResponse:
        """
        Проверить номер в чёрном списке.
        
        Args:
            phone: Номер телефона
        
        Returns:
            Результат проверки
        """
        phone = normalize_phone(phone)
        if not phone:
            return BlacklistCheckResponse(
                phone=phone,
                is_blacklisted=False,
                record=None
            )
        
        blacklist_checked_counter.inc()
        
        # Проверяем Redis сначала
        is_blacklisted = await self.redis.is_blacklisted(phone)
        
        if not is_blacklisted:
            return BlacklistCheckResponse(
                phone=phone,
                is_blacklisted=False,
                record=None
            )
        
        # Получаем полную информацию
        async with self.db_pool.acquire() as conn:
            entry = await self._get_blacklist_by_phone(conn, phone)
            
            return BlacklistCheckResponse(
                phone=phone,
                is_blacklisted=entry is not None and entry.status == BlacklistStatus.ACTIVE,
                record=entry
            )
    
    async def check_phones(self, phones: List[str]) -> BlacklistBulkCheckResponse:
        """
        Проверить несколько номеров.
        
        Args:
            phones: Список номеров
        
        Returns:
            Результаты проверки
        """
        results = []
        blacklisted_count = 0
        
        for phone in phones:
            result = await self.check_phone(phone)
            results.append(result)
            if result.is_blacklisted:
                blacklisted_count += 1
        
        return BlacklistBulkCheckResponse(
            results=results,
            total=len(phones),
            blacklisted=blacklisted_count,
            clean=len(phones) - blacklisted_count
        )
    
    # =============================================
    # Массовые операции
    # =============================================
    async def bulk_add_to_blacklist(
        self,
        request: BlacklistBulkAddRequest,
        user_id: Optional[int] = None
    ) -> BlacklistBulkAddResponse:
        """
        Массовое добавление в чёрный список.
        
        Args:
            request: Данные для добавления
            user_id: ID пользователя
        
        Returns:
            Результат операции
        """
        result = BlacklistBulkAddResponse(
            total=len(request.phones),
            added=0,
            skipped=0,
            invalid=0,
            errors=[]
        )
        
        async with self.db_pool.acquire() as conn:
            for phone in request.phones:
                try:
                    normalized = normalize_phone(phone)
                    if not normalized:
                        if request.skip_invalid:
                            result.invalid += 1
                            continue
                        else:
                            result.errors.append({'phone': phone, 'error': 'Invalid phone number'})
                            continue
                    
                    # Проверяем существование
                    existing = await conn.fetchrow("""
                        SELECT id FROM blacklist WHERE phone = $1 AND status = 'active'
                    """, normalized)
                    
                    if existing:
                        if request.skip_existing:
                            result.skipped += 1
                            continue
                        else:
                            result.skipped += 1
                            continue
                    
                    # Добавляем
                    add_request = BlacklistAddRequest(
                        phone=normalized,
                        reason=request.reason,
                        reason_details=request.reason_details,
                        expires_at=request.expires_at,
                        source=request.source,
                        tags=request.tags
                    )
                    
                    await self._add_to_blacklist_internal(conn, add_request, user_id)
                    result.added += 1
                    
                except Exception as e:
                    logger.error(f"Ошибка добавления {phone}: {e}")
                    result.errors.append({'phone': phone, 'error': str(e)})
        
        blacklist_added_counter.labels(
            source=request.source.value,
            reason=request.reason.value
        ).inc(result.added)
        blacklist_size_gauge.set(await self.get_active_count())
        
        logger.info(f"Массовое добавление в ЧС: {result.added} добавлено, {result.skipped} пропущено")
        
        return result
    
    async def bulk_remove_from_blacklist(
        self,
        phones: List[str],
        user_id: Optional[int] = None,
        reason: Optional[str] = None
    ) -> BlacklistBulkRemoveResponse:
        """
        Массовое удаление из чёрного списка.
        
        Args:
            phones: Список номеров
            user_id: ID пользователя
            reason: Причина удаления
        
        Returns:
            Результат операции
        """
        result = BlacklistBulkRemoveResponse(
            total=len(phones),
            removed=0,
            not_found=0,
            errors=[]
        )
        
        for phone in phones:
            try:
                response = await self.remove_phone_from_blacklist(phone, user_id, reason)
                if response.removed:
                    result.removed += 1
                else:
                    result.not_found += 1
            except Exception as e:
                result.errors.append({'phone': phone, 'error': str(e)})
        
        blacklist_removed_counter.inc(result.removed)
        blacklist_size_gauge.set(await self.get_active_count())
        
        logger.info(f"Массовое удаление из ЧС: {result.removed} удалено")
        
        return result
    
    # =============================================
    # Получение данных
    # =============================================
    async def get_blacklist_entry(self, blacklist_id: int) -> Optional[BlacklistDetailResponse]:
        """Получить запись по ID"""
        async with self.db_pool.acquire() as conn:
            entry = await self._get_blacklist_by_id(conn, blacklist_id)
            if not entry:
                return None
            
            # Получаем историю
            history = await self._get_entry_history(conn, blacklist_id)
            
            # Получаем связанные контакты
            contacts = await self._get_related_contacts(conn, entry.phone)
            
            # Получаем звонки до блокировки
            calls_before = await self._get_calls_before_block(conn, entry.phone, entry.created_at)
            
            return BlacklistDetailResponse(
                **entry.model_dump(),
                history=history,
                contacts=contacts,
                calls_before=calls_before
            )
    
    async def get_blacklist_by_phone(self, phone: str) -> Optional[BlacklistResponse]:
        """Получить запись по номеру телефона"""
        phone = normalize_phone(phone)
        if not phone:
            return None
        
        async with self.db_pool.acquire() as conn:
            return await self._get_blacklist_by_phone(conn, phone)
    
    async def list_blacklist(
        self,
        page: int = 1,
        page_size: int = 20,
        filter_params: Optional[BlacklistFilterRequest] = None
    ) -> BlacklistListResponse:
        """
        Получить список записей чёрного списка.
        
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
            
            if not filter_params or not filter_params.include_removed:
                where_conditions.append("b.status != 'removed'")
            
            if filter_params:
                if filter_params.search:
                    where_conditions.append(f"b.phone LIKE ${param_idx}")
                    params.append(f"%{filter_params.search}%")
                    param_idx += 1
                
                if filter_params.reason:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.reason))])
                    where_conditions.append(f"b.reason IN ({placeholders})")
                    params.extend([r.value for r in filter_params.reason])
                    param_idx += len(filter_params.reason)
                
                if filter_params.status:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.status))])
                    where_conditions.append(f"b.status IN ({placeholders})")
                    params.extend([s.value for s in filter_params.status])
                    param_idx += len(filter_params.status)
                
                if filter_params.source:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.source))])
                    where_conditions.append(f"b.source IN ({placeholders})")
                    params.extend([s.value for s in filter_params.source])
                    param_idx += len(filter_params.source)
                
                if filter_params.tags:
                    where_conditions.append(f"""
                        b.id IN (
                            SELECT blacklist_id FROM blacklist_tags 
                            WHERE tag = ANY(${param_idx})
                        )
                    """)
                    params.append(filter_params.tags)
                    param_idx += 1
                
                if filter_params.created_by:
                    where_conditions.append(f"b.created_by = ${param_idx}")
                    params.append(filter_params.created_by)
                    param_idx += 1
                
                if filter_params.created_after:
                    where_conditions.append(f"b.created_at >= ${param_idx}")
                    params.append(filter_params.created_after)
                    param_idx += 1
                
                if filter_params.created_before:
                    where_conditions.append(f"b.created_at <= ${param_idx}")
                    params.append(filter_params.created_before)
                    param_idx += 1
                
                if filter_params.expires_before:
                    where_conditions.append(f"b.expires_at <= ${param_idx}")
                    params.append(filter_params.expires_before)
                    param_idx += 1
                
                if filter_params.expires_after:
                    where_conditions.append(f"b.expires_at >= ${param_idx}")
                    params.append(filter_params.expires_after)
                    param_idx += 1
                
                if not filter_params.include_expired:
                    where_conditions.append("(b.expires_at IS NULL OR b.expires_at > NOW())")
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            # Общее количество
            count_query = f"""
                SELECT COUNT(*) FROM blacklist b
                {where_clause}
            """
            total = await conn.fetchval(count_query, *params)
            
            # Статистика
            active_count = await conn.fetchval(f"""
                SELECT COUNT(*) FROM blacklist b
                {where_clause} AND b.status = 'active'
            """, *params)
            
            expired_count = await conn.fetchval(f"""
                SELECT COUNT(*) FROM blacklist b
                {where_clause} AND b.status = 'expired'
            """, *params)
            
            removed_count = await conn.fetchval(f"""
                SELECT COUNT(*) FROM blacklist b
                {where_clause} AND b.status = 'removed'
            """, *params)
            
            # Сортировка
            sort_by = filter_params.sort_by if filter_params else "created_at"
            sort_order = filter_params.sort_order if filter_params else "DESC"
            
            # Получаем данные
            query = f"""
                SELECT 
                    b.*,
                    u.username as created_by_name
                FROM blacklist b
                LEFT JOIN users u ON b.created_by = u.id
                {where_clause}
                ORDER BY b.{sort_by} {sort_order}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([page_size, offset])
            
            rows = await conn.fetch(query, *params)
            
            items = []
            for row in rows:
                tags = await self._get_blacklist_tags(conn, row['id'])
                
                items.append(BlacklistResponse(
                    id=row['id'],
                    phone=row['phone'],
                    phone_display=self._format_phone_display(row['phone']),
                    reason=BlacklistReason(row['reason']),
                    reason_details=row['reason_details'],
                    status=BlacklistStatus(row['status']),
                    expires_at=row['expires_at'],
                    is_expired=row['expires_at'] and row['expires_at'] < datetime.utcnow(),
                    source=BlacklistSource(row['source']) if row['source'] else BlacklistSource.MANUAL,
                    notes=row['notes'],
                    tags=tags,
                    created_by=row['created_by'],
                    created_by_name=row['created_by_name'],
                    removed_at=row['removed_at'],
                    removed_by=row['removed_by'],
                    removed_reason=row['removed_reason'],
                    times_called_before=row['times_called_before'] or 0,
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                ))
            
            return BlacklistListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=(total + page_size - 1) // page_size,
                active_count=active_count,
                expired_count=expired_count,
                removed_count=removed_count
            )
    
    # =============================================
    # Автоматические операции
    # =============================================
    async def auto_block_after_failures(
        self,
        phone: str,
        campaign_id: Optional[int] = None
    ) -> Optional[BlacklistResponse]:
        """
        Автоматически заблокировать номер после множества неудачных звонков.
        
        Args:
            phone: Номер телефона
            campaign_id: ID кампании
        
        Returns:
            Созданная запись или None
        """
        phone = normalize_phone(phone)
        if not phone:
            return None
        
        async with self.db_pool.acquire() as conn:
            # Проверяем, не заблокирован ли уже
            existing = await conn.fetchrow("""
                SELECT id FROM blacklist WHERE phone = $1 AND status = 'active'
            """, phone)
            
            if existing:
                return None
            
            # Считаем количество неудачных звонков
            failed_calls = await conn.fetchval("""
                SELECT COUNT(*) FROM call_results
                WHERE phone = $1 
                AND status IN ('failed', 'noanswer', 'busy', 'timeout')
                AND created_at > NOW() - INTERVAL '1 day' * $2
            """, phone, self.auto_block_window_days)
            
            if failed_calls >= self.auto_block_after_failures:
                # Автоматически блокируем
                request = BlacklistAddRequest(
                    phone=phone,
                    reason=BlacklistReason.OTHER,
                    reason_details=f"Автоматическая блокировка после {failed_calls} неудачных звонков",
                    source=BlacklistSource.AUTO
                )
                
                return await self.add_to_blacklist(request)
        
        return None
    
    async def cleanup_expired(self) -> int:
        """
        Очистить истекшие записи.
        
        Returns:
            Количество очищенных записей
        """
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE blacklist 
                SET status = 'expired', updated_at = NOW()
                WHERE status = 'active' 
                AND expires_at IS NOT NULL 
                AND expires_at < NOW()
            """)
            
            # Парсим количество
            import re
            match = re.search(r'UPDATE (\d+)', result)
            cleaned = int(match.group(1)) if match else 0
            
            if cleaned > 0:
                logger.info(f"Очищено {cleaned} истекших записей чёрного списка")
                blacklist_size_gauge.set(await self.get_active_count())
            
            return cleaned
    
    async def get_active_count(self) -> int:
        """Получить количество активных записей"""
        async with self.db_pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT COUNT(*) FROM blacklist 
                WHERE status = 'active' 
                AND (expires_at IS NULL OR expires_at > NOW())
            """)
    
    # =============================================
    # Статистика
    # =============================================
    async def get_stats(self) -> BlacklistStatsResponse:
        """Получить статистику чёрного списка"""
        async with self.db_pool.acquire() as conn:
            # Общая статистика
            totals = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                    COUNT(CASE WHEN status = 'expired' THEN 1 END) as expired,
                    COUNT(CASE WHEN status = 'removed' THEN 1 END) as removed,
                    COUNT(CASE WHEN created_at::date = CURRENT_DATE THEN 1 END) as added_today,
                    COUNT(CASE WHEN created_at >= DATE_TRUNC('week', CURRENT_DATE) THEN 1 END) as added_this_week,
                    COUNT(CASE WHEN created_at >= DATE_TRUNC('month', CURRENT_DATE) THEN 1 END) as added_this_month,
                    COUNT(CASE WHEN removed_at::date = CURRENT_DATE THEN 1 END) as removed_today
                FROM blacklist
            """)
            
            # По причинам
            by_reason_rows = await conn.fetch("""
                SELECT reason, COUNT(*) as count
                FROM blacklist
                WHERE status = 'active'
                GROUP BY reason
                ORDER BY count DESC
            """)
            by_reason = {row['reason']: row['count'] for row in by_reason_rows}
            
            # По источникам
            by_source_rows = await conn.fetch("""
                SELECT source, COUNT(*) as count
                FROM blacklist
                WHERE status = 'active'
                GROUP BY source
                ORDER BY count DESC
            """)
            by_source = {row['source']: row['count'] for row in by_source_rows}
            
            # Топ причин
            top_reasons = [
                {"reason": row['reason'], "count": row['count']}
                for row in by_reason_rows[:5]
            ]
            
            return BlacklistStatsResponse(
                total_records=totals['total'] or 0,
                active_records=totals['active'] or 0,
                expired_records=totals['expired'] or 0,
                removed_records=totals['removed'] or 0,
                by_reason=by_reason,
                by_source=by_source,
                added_today=totals['added_today'] or 0,
                added_this_week=totals['added_this_week'] or 0,
                added_this_month=totals['added_this_month'] or 0,
                removed_today=totals['removed_today'] or 0,
                top_reasons=top_reasons
            )
    
    # =============================================
    # Экспорт/Импорт
    # =============================================
    async def export_to_csv(
        self,
        filter_params: Optional[BlacklistFilterRequest] = None
    ) -> bytes:
        """Экспорт в CSV"""
        response = await self.list_blacklist(
            page=1,
            page_size=100000,
            filter_params=filter_params
        )
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow([
            'phone', 'reason', 'reason_details', 'status',
            'source', 'notes', 'created_at', 'expires_at'
        ])
        
        for item in response.items:
            writer.writerow([
                item.phone,
                item.reason.value,
                item.reason_details or '',
                item.status.value,
                item.source.value,
                item.notes or '',
                item.created_at.isoformat() if item.created_at else '',
                item.expires_at.isoformat() if item.expires_at else ''
            ])
        
        return output.getvalue().encode('utf-8-sig')
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    async def _add_to_blacklist_internal(
        self,
        conn,
        request: BlacklistAddRequest,
        user_id: Optional[int] = None
    ) -> int:
        """Внутренний метод добавления (в транзакции)"""
        blacklist_id = await conn.fetchval("""
            INSERT INTO blacklist (
                phone, reason, reason_details,
                expires_at, source, notes,
                status, created_by, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
            ON CONFLICT (phone) DO UPDATE SET
                status = 'active',
                reason = EXCLUDED.reason,
                reason_details = EXCLUDED.reason_details,
                expires_at = EXCLUDED.expires_at,
                source = EXCLUDED.source,
                notes = EXCLUDED.notes,
                updated_at = NOW(),
                removed_at = NULL,
                removed_by = NULL,
                removed_reason = NULL
            RETURNING id
        """,
            request.phone,
            request.reason.value,
            request.reason_details,
            request.expires_at,
            request.source.value,
            request.notes,
            BlacklistStatus.ACTIVE.value,
            user_id
        )
        
        # Обновляем контакт
        await conn.execute("""
            UPDATE contacts 
            SET blacklisted = TRUE, 
                blacklist_reason = $1,
                updated_at = NOW()
            WHERE phone = $2
        """, request.reason.value, request.phone)
        
        # Добавляем в Redis
        await self.redis.add_to_blacklist(request.phone)
        
        return blacklist_id
    
    async def _get_blacklist_by_id(self, conn, blacklist_id: int) -> Optional[BlacklistResponse]:
        """Получить запись по ID"""
        row = await conn.fetchrow("""
            SELECT 
                b.*,
                u.username as created_by_name
            FROM blacklist b
            LEFT JOIN users u ON b.created_by = u.id
            WHERE b.id = $1
        """, blacklist_id)
        
        if not row:
            return None
        
        tags = await self._get_blacklist_tags(conn, blacklist_id)
        
        return BlacklistResponse(
            id=row['id'],
            phone=row['phone'],
            phone_display=self._format_phone_display(row['phone']),
            reason=BlacklistReason(row['reason']),
            reason_details=row['reason_details'],
            status=BlacklistStatus(row['status']),
            expires_at=row['expires_at'],
            is_expired=row['expires_at'] and row['expires_at'] < datetime.utcnow(),
            source=BlacklistSource(row['source']) if row['source'] else BlacklistSource.MANUAL,
            notes=row['notes'],
            tags=tags,
            created_by=row['created_by'],
            created_by_name=row['created_by_name'],
            removed_at=row['removed_at'],
            removed_by=row['removed_by'],
            removed_reason=row['removed_reason'],
            times_called_before=row['times_called_before'] or 0,
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
    
    async def _get_blacklist_by_phone(self, conn, phone: str) -> Optional[BlacklistResponse]:
        """Получить запись по номеру"""
        row = await conn.fetchrow("""
            SELECT id FROM blacklist WHERE phone = $1 AND status = 'active'
        """, phone)
        
        if not row:
            return None
        
        return await self._get_blacklist_by_id(conn, row['id'])
    
    async def _get_blacklist_tags(self, conn, blacklist_id: int) -> List[str]:
        rows = await conn.fetch(
            "SELECT tag FROM blacklist_tags WHERE blacklist_id = $1",
            blacklist_id
        )
        return [row['tag'] for row in rows]
    
    async def _add_blacklist_tags(self, conn, blacklist_id: int, tags: List[str]) -> None:
        for tag in tags:
            await conn.execute("""
                INSERT INTO blacklist_tags (blacklist_id, tag)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, blacklist_id, tag)
    
    async def _get_entry_history(self, conn, blacklist_id: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT * FROM blacklist_history
            WHERE blacklist_id = $1
            ORDER BY created_at DESC
        """, blacklist_id)
        return [dict(row) for row in rows]
    
    async def _get_related_contacts(self, conn, phone: str) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT id, name, email, company
            FROM contacts
            WHERE phone = $1
        """, phone)
        return [dict(row) for row in rows]
    
    async def _get_calls_before_block(self, conn, phone: str, blocked_at: datetime) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT id, status, duration, created_at
            FROM call_results
            WHERE phone = $1 AND created_at < $2
            ORDER BY created_at DESC
        """, phone, blocked_at)
        return [dict(row) for row in rows]
    
    def _format_phone_display(self, phone: str) -> str:
        """Форматирование номера для отображения (см. app.utils.phone)"""
        return _format_phone_display_shared(phone)
    
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
            
            return {
                "status": "healthy",
                "active_count": await self.get_active_count()
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        logger.info("BlacklistService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_blacklist_service: Optional[BlacklistService] = None


def get_blacklist_service() -> BlacklistService:
    """Получить глобальный экземпляр BlacklistService"""
    global _blacklist_service
    if _blacklist_service is None:
        raise RuntimeError("BlacklistService не инициализирован")
    return _blacklist_service


def set_blacklist_service(service: BlacklistService) -> None:
    """Установить глобальный экземпляр BlacklistService"""
    global _blacklist_service
    _blacklist_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "BlacklistService",
    "BlacklistError",
    "BlacklistNotFoundError",
    "BlacklistAlreadyExistsError",
    "BlacklistValidationError",
    "get_blacklist_service",
    "set_blacklist_service",
]
