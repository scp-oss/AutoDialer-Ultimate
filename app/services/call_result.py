#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления результатами звонков
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Сохранения результатов звонков
- Получения истории звонков
- Управления записями звонков
- Статистики и аналитики звонков
"""

import json
import os
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS
from app.models.call import (
    CallResultStatus, CallDirection, HangupCause, DTMFResult,
    CallResultCreateRequest, CallHistoryFilterRequest,
    CallResultResponse, CallDetailResponse, CallListResponse,
    CallStatsResponse, DailyCallStatsResponse, HourlyCallStatsResponse,
    CallAnalyticsResponse, ActiveCallResponse, ActiveCallsResponse,
    CallEventResponse
)
from app.utils.phone import format_phone_display as _format_phone_display_shared
from app.models.common import PaginatedResponse
from prometheus_client import Counter, Histogram


# =============================================
# Метрики
# =============================================
call_result_counter = Counter(
    'autodialer_call_results_total',
    'Total call results',
    ['status', 'campaign_id']
)
call_duration_histogram = Histogram(
    'autodialer_call_result_duration_seconds',
    'Call duration in seconds (from persisted call results)',
    buckets=[10, 30, 60, 120, 180, 300, 600, 1200, 1800]
)
call_recording_deleted_counter = Counter(
    'autodialer_recordings_deleted_total',
    'Total recordings deleted'
)


# =============================================
# Исключения
# =============================================
class CallError(Exception):
    """Базовое исключение сервиса звонков"""
    pass


class CallNotFoundError(CallError):
    """Звонок не найден"""
    pass


class RecordingNotFoundError(CallError):
    """Запись звонка не найдена"""
    pass


class CallDeleteError(CallError):
    """Ошибка удаления звонка"""
    pass


# =============================================
# Сервис результатов звонков
# =============================================
class CallResultService:
    """
    Сервис управления результатами звонков.
    
    Отвечает за:
    - Сохранение результатов звонков
    - Получение истории звонков
    - Управление записями
    - Статистику и аналитику
    """
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        
        logger.info("CallResultService инициализирован")
    
    # =============================================
    # Сохранение результатов
    # =============================================
    async def save_call_result(
        self,
        request: CallResultCreateRequest
    ) -> CallResultResponse:
        """
        Сохранить результат звонка.
        
        Args:
            request: Данные результата звонка
        
        Returns:
            Сохранённый результат
        """
        async with self.db_pool.acquire() as conn:
            # Получаем или создаём контакт
            contact_id = request.contact_id
            if not contact_id and request.phone:
                # Атомарный upsert вместо SELECT-затем-INSERT: та же
                # dialer_bridge context выполняется дважды на звонок (по
                # разу на каждую половину Local-канала, из-за флага /n),
                # так что два UserEvent(DialerResult) для одного номера
                # могут прийти почти одновременно - SELECT-затем-INSERT
                # гарантированно ловит гонку (оба видят "контакта нет",
                # оба пытаются INSERT), падая с
                # `duplicate key value violates unique constraint
                # "idx_contacts_phone_active"` - подтверждено живьём.
                # Индекс частичный (`WHERE NOT blacklisted`), поэтому
                # предикат ON CONFLICT должен точно ему соответствовать,
                # иначе Postgres не примет его как arbiter вообще.
                contact_id = await conn.fetchval("""
                    INSERT INTO contacts (phone, source, status, created_at, updated_at)
                    VALUES ($1, 'incoming', 'active', NOW(), NOW())
                    ON CONFLICT (phone) WHERE NOT blacklisted
                    DO UPDATE SET updated_at = NOW()
                    RETURNING id
                """, request.phone)
            
            # Вставляем результат
            call_id = await conn.fetchval("""
                INSERT INTO call_results (
                    campaign_id, contact_id, phone,
                    status, direction, dtmf_result, dtmf_digits,
                    duration, billable_seconds,
                    hangup_cause, hangup_cause_code,
                    retry_count,
                    recording_path,
                    unique_id, linked_id, channel, caller_id,
                    wait_time, metadata, tags,
                    created_at
                ) VALUES (
                    $1, $2, $3,
                    $4, $5, $6, $7,
                    $8, $9,
                    $10, $11,
                    $12,
                    $13,
                    $14, $15, $16, $17,
                    $18, $19, $20,
                    NOW()
                )
                RETURNING id
            """,
                request.campaign_id,
                contact_id,
                request.phone,
                request.status,
                CallDirection.OUTBOUND.value,
                request.dtmf_result,
                None,
                request.duration,
                request.billable_seconds,
                request.hangup_cause,
                request.hangup_cause_code,
                request.retry_count,
                request.recording_path,
                request.unique_id,
                request.linked_id,
                request.channel,
                request.caller_id,
                None,  # wait_time
                json.dumps(request.metadata) if request.metadata else None,
                [],
            )
            
            # Обновляем статистику контакта
            if contact_id:
                await self._update_contact_stats(conn, contact_id, request.status, request.duration)

            # Обновляем прогресс кампании
            if request.campaign_id:
                await self._update_campaign_progress(
                    conn, request.campaign_id, request.status, request.duration
                )
            
            # Получаем полные данные
            result = await self._get_call_by_id(conn, call_id)
        
        # Метрики
        call_result_counter.labels(
            status=request.status,
            campaign_id=str(request.campaign_id or 'unknown')
        ).inc()

        if request.duration:
            call_duration_histogram.observe(request.duration)

        logger.info(f"Результат звонка сохранён: {request.phone} -> {request.status} (ID: {call_id})")
        
        return result
    
    async def save_bulk_call_results(
        self,
        requests: List[CallResultCreateRequest]
    ) -> List[CallResultResponse]:
        """Сохранить несколько результатов звонков"""
        results = []
        for request in requests:
            try:
                result = await self.save_call_result(request)
                results.append(result)
            except Exception as e:
                logger.error(f"Ошибка сохранения результата для {request.phone}: {e}")
        return results
    
    # =============================================
    # Получение данных
    # =============================================
    async def get_call(self, call_id: int) -> Optional[CallDetailResponse]:
        """Получить детальную информацию о звонке"""
        async with self.db_pool.acquire() as conn:
            call = await self._get_call_by_id(conn, call_id)
            if not call:
                return None
            
            # Получаем дополнительные данные
            events = await self._get_call_events(conn, call_id)
            related_calls = await self._get_related_calls(conn, call)
            transcription = await self._get_transcription(conn, call_id)
            
            # Информация об операторе (если был)
            operator_id = None
            operator_name = None
            
            # Информация о кампании
            campaign_status = None
            if call.campaign_id:
                campaign_status = await conn.fetchval(
                    "SELECT status FROM campaigns WHERE id = $1",
                    call.campaign_id
                )
            
            # Информация о контакте
            contact_email = None
            contact_company = None
            contact_tags = []
            if call.contact_id:
                contact_row = await conn.fetchrow(
                    "SELECT email, company FROM contacts WHERE id = $1",
                    call.contact_id
                )
                if contact_row:
                    contact_email = contact_row['email']
                    contact_company = contact_row['company']
                contact_tags = await self._get_contact_tags(conn, call.contact_id)
            
            return CallDetailResponse(
                **call.model_dump(),
                campaign_status=campaign_status,
                contact_email=contact_email,
                contact_company=contact_company,
                contact_tags=contact_tags,
                operator_id=operator_id,
                operator_name=operator_name,
                events=events,
                related_calls=related_calls,
                transcription=transcription,
                transcription_status='completed' if transcription else None
            )
    
    async def get_call_by_unique_id(self, unique_id: str) -> Optional[CallResultResponse]:
        """Получить звонок по Unique ID"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM call_results WHERE unique_id = $1",
                unique_id
            )
            if not row:
                return None
            return await self._get_call_by_id(conn, row['id'])
    
    async def list_calls(
        self,
        page: int = 1,
        page_size: int = 20,
        filter_params: Optional[CallHistoryFilterRequest] = None
    ) -> CallListResponse:
        """Получить список звонков с фильтрацией"""
        offset = (page - 1) * page_size
        
        async with self.db_pool.acquire() as conn:
            where_conditions = []
            params = []
            param_idx = 1
            
            if filter_params:
                if filter_params.campaign_id:
                    where_conditions.append(f"cr.campaign_id = ${param_idx}")
                    params.append(filter_params.campaign_id)
                    param_idx += 1
                
                if filter_params.contact_id:
                    where_conditions.append(f"cr.contact_id = ${param_idx}")
                    params.append(filter_params.contact_id)
                    param_idx += 1
                
                if filter_params.status:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.status))])
                    where_conditions.append(f"cr.status IN ({placeholders})")
                    params.extend(list(filter_params.status))
                    param_idx += len(filter_params.status)

                if filter_params.direction:
                    where_conditions.append(f"cr.direction = ${param_idx}")
                    params.append(filter_params.direction)
                    param_idx += 1
                
                if filter_params.phone:
                    where_conditions.append(f"cr.phone LIKE ${param_idx}")
                    params.append(f"%{filter_params.phone}%")
                    param_idx += 1
                
                if filter_params.from_date:
                    where_conditions.append(f"cr.created_at::date >= ${param_idx}")
                    params.append(filter_params.from_date)
                    param_idx += 1
                
                if filter_params.to_date:
                    where_conditions.append(f"cr.created_at::date <= ${param_idx}")
                    params.append(filter_params.to_date)
                    param_idx += 1
                
                if filter_params.min_duration:
                    where_conditions.append(f"cr.duration >= ${param_idx}")
                    params.append(filter_params.min_duration)
                    param_idx += 1
                
                if filter_params.max_duration:
                    where_conditions.append(f"cr.duration <= ${param_idx}")
                    params.append(filter_params.max_duration)
                    param_idx += 1
                
                if filter_params.has_recording is not None:
                    if filter_params.has_recording:
                        where_conditions.append("cr.recording_path IS NOT NULL")
                    else:
                        where_conditions.append("cr.recording_path IS NULL")
                
                if filter_params.dtmf_result:
                    where_conditions.append(f"cr.dtmf_result = ${param_idx}")
                    params.append(filter_params.dtmf_result)
                    param_idx += 1
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            # Общее количество
            count_query = f"""
                SELECT COUNT(*) FROM call_results cr
                {where_clause}
            """
            total = await conn.fetchval(count_query, *params)
            
            # Сводка по статусам
            summary_query = f"""
                SELECT cr.status, COUNT(*) as count
                FROM call_results cr
                {where_clause}
                GROUP BY cr.status
            """
            summary_rows = await conn.fetch(summary_query, *params)
            summary = {row['status']: row['count'] for row in summary_rows}
            
            # Сортировка
            sort_by = filter_params.sort_by if filter_params else "created_at"
            sort_order = filter_params.sort_order if filter_params else "DESC"
            
            # Получаем данные
            query = f"""
                SELECT 
                    cr.*,
                    c.name as campaign_name,
                    ct.name as contact_name
                FROM call_results cr
                LEFT JOIN campaigns c ON cr.campaign_id = c.id
                LEFT JOIN contacts ct ON cr.contact_id = ct.id
                {where_clause}
                ORDER BY cr.{sort_by} {sort_order}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([page_size, offset])
            
            rows = await conn.fetch(query, *params)
            
            items = []
            for row in rows:
                tags = await self._get_call_tags(conn, row['id'])
                metadata = json.loads(row['metadata']) if row['metadata'] else {}
                
                items.append(CallResultResponse(
                    id=row['id'],
                    campaign_id=row['campaign_id'],
                    campaign_name=row['campaign_name'],
                    contact_id=row['contact_id'],
                    contact_name=row['contact_name'],
                    phone=row['phone'],
                    phone_display=self._format_phone_display(row['phone']),
                    status=CallResultStatus(row['status']),
                    direction=CallDirection(row['direction']) if row['direction'] else CallDirection.OUTBOUND,
                    dtmf_result=row['dtmf_result'],
                    dtmf_digits=row['dtmf_digits'],
                    duration=row['duration'],
                    duration_formatted=self._format_duration(row['duration']),
                    billable_seconds=row['billable_seconds'],
                    hangup_cause=row['hangup_cause'],
                    hangup_cause_code=row['hangup_cause_code'],
                    retry_count=row['retry_count'] or 0,
                    recording_path=row['recording_path'],
                    recording_url=f"/api/calls/{row['id']}/recording" if row['recording_path'] else None,
                    recording_size=row['recording_size'],
                    unique_id=row['unique_id'],
                    linked_id=row['linked_id'],
                    channel=row['channel'],
                    caller_id=row['caller_id'],
                    wait_time=row['wait_time'],
                    metadata=metadata,
                    tags=tags,
                    notes=row['notes'],
                    created_at=row['created_at']
                ))
            
            return CallListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=(total + page_size - 1) // page_size,
                summary=summary
            )
    
    # =============================================
    # Управление записями
    # =============================================
    async def get_recording_path(self, call_id: int) -> Optional[str]:
        """Получить путь к записи звонка"""
        async with self.db_pool.acquire() as conn:
            path = await conn.fetchval(
                "SELECT recording_path FROM call_results WHERE id = $1",
                call_id
            )
            if not path:
                raise RecordingNotFoundError(f"Запись для звонка {call_id} не найдена")
            
            if not os.path.exists(path):
                logger.warning(f"Файл записи не найден: {path}")
                raise RecordingNotFoundError(f"Файл записи не найден: {path}")
            
            return path
    
    async def delete_recording(self, call_id: int, user_id: Optional[int] = None) -> bool:
        """Удалить запись звонка"""
        async with self.db_pool.acquire() as conn:
            path = await conn.fetchval(
                "SELECT recording_path FROM call_results WHERE id = $1",
                call_id
            )
            if not path:
                return False
            
            # Удаляем файл
            if os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"Файл записи удалён: {path}")
                except Exception as e:
                    logger.error(f"Ошибка удаления файла {path}: {e}")
                    raise CallDeleteError(f"Не удалось удалить файл записи: {e}")
            
            # Обновляем БД
            await conn.execute("""
                UPDATE call_results 
                SET recording_path = NULL, recording_size = NULL
                WHERE id = $1
            """, call_id)
            
            await self._log_audit(conn, user_id, 'recording_deleted', 'call', call_id)
        
        call_recording_deleted_counter.inc()
        logger.info(f"Запись звонка {call_id} удалена")
        
        return True
    
    async def delete_call(self, call_id: int, user_id: Optional[int] = None) -> bool:
        """Удалить звонок (и запись если есть)"""
        async with self.db_pool.acquire() as conn:
            call = await conn.fetchrow(
                "SELECT recording_path FROM call_results WHERE id = $1",
                call_id
            )
            if not call:
                raise CallNotFoundError(f"Звонок {call_id} не найден")
            
            # Удаляем запись если есть
            if call['recording_path'] and os.path.exists(call['recording_path']):
                try:
                    os.remove(call['recording_path'])
                except Exception as e:
                    logger.warning(f"Не удалось удалить файл записи: {e}")
            
            # Удаляем из БД
            await conn.execute("DELETE FROM call_results WHERE id = $1", call_id)
            await conn.execute("DELETE FROM call_events WHERE call_id = $1", call_id)
            await conn.execute("DELETE FROM call_tags WHERE call_id = $1", call_id)
            
            await self._log_audit(conn, user_id, 'call_deleted', 'call', call_id)
        
        logger.info(f"Звонок {call_id} удалён")
        return True
    
    async def delete_calls_bulk(
        self,
        call_ids: List[int],
        user_id: Optional[int] = None,
        delete_recordings: bool = True
    ) -> Tuple[int, List[str]]:
        """Массовое удаление звонков"""
        deleted = 0
        errors = []
        
        for call_id in call_ids:
            try:
                if delete_recordings:
                    try:
                        await self.delete_recording(call_id, user_id)
                    except RecordingNotFoundError:
                        pass
                await self.delete_call(call_id, user_id)
                deleted += 1
            except Exception as e:
                errors.append(f"Call {call_id}: {str(e)}")
        
        logger.info(f"Массовое удаление: {deleted} звонков удалено, {len(errors)} ошибок")
        return deleted, errors
    
    # =============================================
    # Статистика
    # =============================================
    async def get_call_stats(
        self,
        campaign_id: Optional[int] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> CallStatsResponse:
        """Получить статистику звонков"""
        async with self.db_pool.acquire() as conn:
            where_conditions = []
            params = []
            param_idx = 1
            
            if campaign_id:
                where_conditions.append(f"campaign_id = ${param_idx}")
                params.append(campaign_id)
                param_idx += 1
            
            if from_date:
                where_conditions.append(f"created_at::date >= ${param_idx}")
                params.append(from_date)
                param_idx += 1
            
            if to_date:
                where_conditions.append(f"created_at::date <= ${param_idx}")
                params.append(to_date)
                param_idx += 1
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            row = await conn.fetchrow(f"""
                SELECT 
                    COUNT(*) as total_calls,
                    COUNT(CASE WHEN status IN ('agreed', 'declined') THEN 1 END) as answered_calls,
                    COUNT(DISTINCT contact_id) as unique_contacts,
                    
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status = 'declined' THEN 1 END) as declined,
                    COUNT(CASE WHEN status = 'busy' THEN 1 END) as busy,
                    COUNT(CASE WHEN status = 'noanswer' THEN 1 END) as noanswer,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                    COUNT(CASE WHEN status = 'timeout' THEN 1 END) as timeout,
                    COUNT(CASE WHEN status = 'machine' THEN 1 END) as machine,
                    COUNT(CASE WHEN status = 'canceled' THEN 1 END) as canceled,
                    COUNT(CASE WHEN status = 'congestion' THEN 1 END) as congestion,
                    
                    AVG(duration) as avg_duration,
                    COALESCE(SUM(duration), 0) as total_duration,
                    AVG(wait_time) as avg_wait_time,
                    MAX(duration) as max_duration,
                    MIN(duration) as min_duration
                FROM call_results
                {where_clause}
            """, *params)
            
            if not row:
                return CallStatsResponse()
            
            total = row['total_calls'] or 0
            agreed = row['agreed'] or 0
            answered = row['answered_calls'] or 0
            
            # DTMF статистика
            dtmf_stats = await self._get_dtmf_stats(conn, where_clause, params)
            
            # По часам
            calls_by_hour = await self._get_calls_by_hour(conn, where_clause, params)
            
            # По дням недели
            calls_by_weekday = await self._get_calls_by_weekday(conn, where_clause, params)
            
            return CallStatsResponse(
                from_date=from_date,
                to_date=to_date,
                total_calls=total,
                answered_calls=answered,
                unique_contacts=row['unique_contacts'] or 0,
                agreed=agreed,
                declined=row['declined'] or 0,
                busy=row['busy'] or 0,
                noanswer=row['noanswer'] or 0,
                failed=row['failed'] or 0,
                timeout=row['timeout'] or 0,
                machine=row['machine'] or 0,
                canceled=row['canceled'] or 0,
                congestion=row['congestion'] or 0,
                conversion_rate=round(agreed / total * 100, 2) if total > 0 else 0.0,
                answer_rate=round(answered / total * 100, 2) if total > 0 else 0.0,
                avg_duration=round(row['avg_duration'] or 0, 2),
                total_duration=row['total_duration'] or 0,
                avg_wait_time=round(row['avg_wait_time'] or 0, 2),
                max_duration=row['max_duration'] or 0,
                min_duration=row['min_duration'] or 0,
                dtmf_stats=dtmf_stats,
                calls_by_hour=calls_by_hour,
                calls_by_weekday=calls_by_weekday
            )
    
    async def get_daily_stats(
        self,
        days: int = 30,
        campaign_id: Optional[int] = None
    ) -> List[DailyCallStatsResponse]:
        """Получить дневную статистику"""
        async with self.db_pool.acquire() as conn:
            where_conditions = [f"created_at >= CURRENT_DATE - INTERVAL '{days} days'"]
            params = []
            
            if campaign_id:
                where_conditions.append(f"campaign_id = ${len(params) + 1}")
                params.append(campaign_id)
            
            where_clause = "WHERE " + " AND ".join(where_conditions)
            
            rows = await conn.fetch(f"""
                SELECT 
                    created_at::date as date,
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status = 'declined' THEN 1 END) as declined,
                    COUNT(CASE WHEN status = 'busy' THEN 1 END) as busy,
                    COUNT(CASE WHEN status = 'noanswer' THEN 1 END) as noanswer,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                    AVG(duration) as avg_duration
                FROM call_results
                {where_clause}
                GROUP BY created_at::date
                ORDER BY date DESC
            """, *params)
            
            result = []
            for row in rows:
                total = row['total']
                agreed = row['agreed'] or 0
                result.append(DailyCallStatsResponse(
                    date=row['date'],
                    total=total,
                    agreed=agreed,
                    declined=row['declined'] or 0,
                    busy=row['busy'] or 0,
                    noanswer=row['noanswer'] or 0,
                    failed=row['failed'] or 0,
                    conversion_rate=round(agreed / total * 100, 2) if total > 0 else 0.0,
                    avg_duration=round(row['avg_duration'] or 0, 2)
                ))
            
            return result
    
    async def get_analytics(
        self,
        days: int = 30,
        campaign_id: Optional[int] = None
    ) -> CallAnalyticsResponse:
        """Получить расширенную аналитику"""
        daily_stats = await self.get_daily_stats(days, campaign_id)
        hourly_stats = await self._get_hourly_stats(days, campaign_id)
        
        async with self.db_pool.acquire() as conn:
            # Топ кампаний
            top_campaigns = await self._get_top_campaigns(conn, days)
            
            # Топ номеров
            top_phones = await self._get_top_phones(conn, days)
            
            # Причины завершения
            hangup_causes = await self._get_hangup_causes(conn, days, campaign_id)
            
            # Лучшие часы
            best_hours = await self._get_best_hours(conn, days)
            
            # Лучшие дни недели
            best_weekdays = await self._get_best_weekdays(conn, days)
            
            # Рекомендации
            recommendations = self._generate_recommendations(
                daily_stats, hourly_stats, hangup_causes
            )
            
            return CallAnalyticsResponse(
                period_days=days,
                daily_stats=daily_stats,
                hourly_stats=hourly_stats,
                top_campaigns=top_campaigns,
                top_contacts=[],
                top_phones=top_phones,
                hangup_causes=hangup_causes,
                best_hours=best_hours,
                best_weekdays=best_weekdays,
                recommendations=recommendations
            )
    
    # =============================================
    # Активные звонки
    # =============================================
    async def get_active_calls(self) -> ActiveCallsResponse:
        """Получить список активных звонков"""
        # Получаем из Redis
        active_channels = await self.redis.smembers(REDIS_KEYS.ACTIVE_CHANNELS)
        
        calls = []
        for channel_key in active_channels:
            # channel_key = "Local/79991234567@dialer_bridge:unique_id"
            parts = channel_key.split(':')
            if len(parts) >= 2:
                unique_id = parts[-1]
                channel = ':'.join(parts[:-1])
                
                # Извлекаем телефон из канала
                import re
                phone_match = re.search(r'/(\d+)@', channel)
                phone = phone_match.group(1) if phone_match else None
                
                calls.append(ActiveCallResponse(
                    unique_id=unique_id,
                    linked_id=None,
                    campaign_id=None,
                    campaign_name=None,
                    contact_id=None,
                    contact_name=None,
                    phone=phone or 'unknown',
                    status='active',
                    state='up',
                    channel=channel,
                    caller_id='',
                    started_at=datetime.utcnow(),
                    duration=0,
                    wait_time=0,
                    retry_count=0
                ))
        
        return ActiveCallsResponse(
            total=len(calls),
            calls=calls,
            max_calls=await self.redis.get(REDIS_KEYS.MAX_CALLS) or 50
        )
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    async def _get_call_by_id(self, conn, call_id: int) -> Optional[CallResultResponse]:
        """Получить звонок по ID (внутренний метод)"""
        row = await conn.fetchrow("""
            SELECT 
                cr.*,
                c.name as campaign_name,
                ct.name as contact_name
            FROM call_results cr
            LEFT JOIN campaigns c ON cr.campaign_id = c.id
            LEFT JOIN contacts ct ON cr.contact_id = ct.id
            WHERE cr.id = $1
        """, call_id)
        
        if not row:
            return None
        
        tags = await self._get_call_tags(conn, call_id)
        metadata = json.loads(row['metadata']) if row['metadata'] else {}
        
        return CallResultResponse(
            id=row['id'],
            campaign_id=row['campaign_id'],
            campaign_name=row['campaign_name'],
            contact_id=row['contact_id'],
            contact_name=row['contact_name'],
            phone=row['phone'],
            phone_display=self._format_phone_display(row['phone']),
            status=CallResultStatus(row['status']),
            direction=CallDirection(row['direction']) if row['direction'] else CallDirection.OUTBOUND,
            dtmf_result=row['dtmf_result'],
            dtmf_digits=row['dtmf_digits'],
            duration=row['duration'],
            duration_formatted=self._format_duration(row['duration']),
            billable_seconds=row['billable_seconds'],
            hangup_cause=row['hangup_cause'],
            hangup_cause_code=row['hangup_cause_code'],
            retry_count=row['retry_count'] or 0,
            recording_path=row['recording_path'],
            recording_url=f"/api/calls/{row['id']}/recording" if row['recording_path'] else None,
            recording_size=row['recording_size'],
            unique_id=row['unique_id'],
            linked_id=row['linked_id'],
            channel=row['channel'],
            caller_id=row['caller_id'],
            wait_time=row['wait_time'],
            metadata=metadata,
            tags=tags,
            notes=row['notes'],
            created_at=row['created_at']
        )
    
    async def _get_call_tags(self, conn, call_id: int) -> List[str]:
        rows = await conn.fetch(
            "SELECT tag FROM call_tags WHERE call_id = $1",
            call_id
        )
        return [row['tag'] for row in rows]
    
    async def _get_call_events(self, conn, call_id: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT * FROM call_events 
            WHERE call_id = $1 
            ORDER BY created_at
        """, call_id)
        return [dict(row) for row in rows]
    
    async def _get_related_calls(self, conn, call: CallResultResponse) -> List[CallResultResponse]:
        """Получить связанные звонки (повторы)"""
        if not call.contact_id or not call.campaign_id:
            return []
        
        rows = await conn.fetch("""
            SELECT id FROM call_results
            WHERE contact_id = $1 AND campaign_id = $2 AND id != $3
            ORDER BY created_at
        """, call.contact_id, call.campaign_id, call.id)
        
        related = []
        for row in rows:
            related_call = await self._get_call_by_id(conn, row['id'])
            if related_call:
                related.append(related_call)
        
        return related
    
    async def _get_transcription(self, conn, call_id: int) -> Optional[str]:
        return await conn.fetchval(
            "SELECT transcription FROM call_transcriptions WHERE call_id = $1",
            call_id
        )
    
    async def _get_contact_tags(self, conn, contact_id: int) -> List[str]:
        rows = await conn.fetch(
            "SELECT tag FROM contact_tags WHERE contact_id = $1",
            contact_id
        )
        return [row['tag'] for row in rows]
    
    async def _update_contact_stats(
        self,
        conn,
        contact_id: int,
        status: str,
        duration: Optional[int]
    ) -> None:
        """Обновить статистику контакта"""
        await conn.execute("""
            UPDATE contacts
            SET
                last_call_at = NOW(),
                last_call_status = $1,
                total_calls = total_calls + 1,
                successful_calls = successful_calls + CASE WHEN $1::VARCHAR IN ('agreed', 'declined') THEN 1 ELSE 0 END,
                updated_at = NOW()
            WHERE id = $2
        """, status, contact_id)
    
    async def _update_campaign_progress(
        self,
        conn,
        campaign_id: int,
        status: str,
        duration: Optional[int]
    ) -> None:
        """Обновить прогресс кампании"""
        # 'busy'/'noanswer'/'failed' здесь раньше ТОЖЕ помечались 'completed' -
        # но именно эти три статуса (см. app/services/dialer.py:
        # _schedule_retry(), strategies dict) имеют настроенную стратегию
        # повтора и получают next_retry_at сразу СЛЕДУЮЩИМ шагом в
        # _handle_user_event() (после этого самого вызова). process_retry_
        # queue() (app/workers/retry.py) забирает на повтор только строки
        # с status='pending' - если этот UPDATE уже поставил 'completed',
        # запланированный next_retry_at так никогда и не сработает: сам
        # повтор молча не происходит, при этом нигде не логируется ошибка.
        # Подтверждено живьём: кампания уходит в статус "Завершена" сразу
        # после первого же "занято", хотя retry_strategy требует ещё
        # 2 попытки. Единственные статусы, для которых повтора в принципе
        # не бывает (нет записи в strategies) - 'agreed'/'declined': они и
        # остаются терминальными здесь. Для busy/noanswer/failed контакт
        # теперь по-прежнему 'pending' - его окончательно закроет сама
        # _schedule_retry(), когда реально исчерпает лимит попыток.
        await conn.execute("""
            UPDATE campaign_contacts
            SET
                last_call_at = NOW(),
                last_call_status = $1,
                retry_count = retry_count + 1,
                status = CASE
                    WHEN $1::VARCHAR IN ('agreed', 'declined') THEN 'completed'
                    ELSE 'pending'
                END
            WHERE campaign_id = $2 AND contact_id = (
                SELECT contact_id FROM call_results 
                WHERE campaign_id = $2 
                ORDER BY created_at DESC 
                LIMIT 1
            )
        """, status, campaign_id)
    
    async def _get_dtmf_stats(self, conn, where_clause: str, params: List) -> Dict[str, int]:
        dtmf_condition = f"{where_clause} AND dtmf_result IS NOT NULL" if where_clause else "WHERE dtmf_result IS NOT NULL"
        rows = await conn.fetch(f"""
            SELECT dtmf_result, COUNT(*) as count
            FROM call_results
            {dtmf_condition}
            GROUP BY dtmf_result
        """, *params)
        return {row['dtmf_result']: row['count'] for row in rows}
    
    async def _get_calls_by_hour(self, conn, where_clause: str, params: List) -> Dict[int, int]:
        rows = await conn.fetch(f"""
            SELECT EXTRACT(HOUR FROM created_at) as hour, COUNT(*) as count
            FROM call_results
            {where_clause}
            GROUP BY hour
            ORDER BY hour
        """, *params)
        return {int(row['hour']): row['count'] for row in rows}
    
    async def _get_calls_by_weekday(self, conn, where_clause: str, params: List) -> Dict[int, int]:
        rows = await conn.fetch(f"""
            SELECT EXTRACT(DOW FROM created_at) as weekday, COUNT(*) as count
            FROM call_results
            {where_clause}
            GROUP BY weekday
            ORDER BY weekday
        """, *params)
        return {int(row['weekday']): row['count'] for row in rows}
    
    async def _get_hourly_stats(
        self,
        days: int,
        campaign_id: Optional[int]
    ) -> List[HourlyCallStatsResponse]:
        async with self.db_pool.acquire() as conn:
            where_conditions = [f"created_at >= CURRENT_DATE - INTERVAL '{days} days'"]
            params = []
            
            if campaign_id:
                where_conditions.append(f"campaign_id = ${len(params) + 1}")
                params.append(campaign_id)
            
            where_clause = "WHERE " + " AND ".join(where_conditions)
            
            rows = await conn.fetch(f"""
                SELECT 
                    EXTRACT(HOUR FROM created_at) as hour,
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status IN ('agreed', 'declined') THEN 1 END) as answered
                FROM call_results
                {where_clause}
                GROUP BY hour
                ORDER BY hour
            """, *params)
            
            result = []
            for row in rows:
                hour = int(row['hour'])
                total = row['total']
                answered = row['answered'] or 0
                result.append(HourlyCallStatsResponse(
                    hour=hour,
                    total=total,
                    agreed=row['agreed'] or 0,
                    answer_rate=round(answered / total * 100, 2) if total > 0 else 0.0
                ))
            
            return result
    
    async def _get_top_campaigns(self, conn, days: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch(f"""
            SELECT 
                cr.campaign_id,
                c.name as campaign_name,
                COUNT(*) as total_calls,
                COUNT(CASE WHEN cr.status = 'agreed' THEN 1 END) as agreed
            FROM call_results cr
            LEFT JOIN campaigns c ON cr.campaign_id = c.id
            WHERE cr.created_at >= CURRENT_DATE - INTERVAL '{days} days'
            GROUP BY cr.campaign_id, c.name
            ORDER BY total_calls DESC
            LIMIT 10
        """)
        return [dict(row) for row in rows]
    
    async def _get_top_phones(self, conn, days: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch(f"""
            SELECT 
                phone,
                COUNT(*) as total_calls,
                COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed
            FROM call_results
            WHERE created_at >= CURRENT_DATE - INTERVAL '{days} days'
            GROUP BY phone
            ORDER BY total_calls DESC
            LIMIT 20
        """)
        return [dict(row) for row in rows]
    
    async def _get_hangup_causes(
        self,
        conn,
        days: int,
        campaign_id: Optional[int]
    ) -> Dict[str, int]:
        where_conditions = [f"created_at >= CURRENT_DATE - INTERVAL '{days} days'"]
        
        if campaign_id:
            where_conditions.append(f"campaign_id = {campaign_id}")
        
        where_clause = "WHERE " + " AND ".join(where_conditions)
        
        rows = await conn.fetch(f"""
            SELECT hangup_cause, COUNT(*) as count
            FROM call_results
            {where_clause} AND hangup_cause IS NOT NULL
            GROUP BY hangup_cause
            ORDER BY count DESC
        """)
        return {row['hangup_cause']: row['count'] for row in rows}
    
    async def _get_best_hours(self, conn, days: int) -> List[int]:
        rows = await conn.fetch(f"""
            SELECT EXTRACT(HOUR FROM created_at) as hour
            FROM call_results
            WHERE created_at >= CURRENT_DATE - INTERVAL '{days} days'
            AND status = 'agreed'
            GROUP BY hour
            ORDER BY COUNT(*) DESC
            LIMIT 3
        """)
        return [int(row['hour']) for row in rows]
    
    async def _get_best_weekdays(self, conn, days: int) -> List[int]:
        rows = await conn.fetch(f"""
            SELECT EXTRACT(DOW FROM created_at) as weekday
            FROM call_results
            WHERE created_at >= CURRENT_DATE - INTERVAL '{days} days'
            AND status = 'agreed'
            GROUP BY weekday
            ORDER BY COUNT(*) DESC
            LIMIT 3
        """)
        return [int(row['weekday']) for row in rows]
    
    def _generate_recommendations(
        self,
        daily_stats: List[DailyCallStatsResponse],
        hourly_stats: List[HourlyCallStatsResponse],
        hangup_causes: Dict[str, int]
    ) -> List[str]:
        """Сгенерировать рекомендации на основе аналитики"""
        recommendations = []
        
        # Анализ конверсии
        if daily_stats:
            recent_conversion = sum(s.conversion_rate for s in daily_stats[:7]) / min(7, len(daily_stats))
            if recent_conversion < 10:
                recommendations.append("Конверсия ниже 10%. Рекомендуется пересмотреть скрипт разговора или время обзвона.")
        
        # Анализ причин завершения
        busy_count = hangup_causes.get('USER_BUSY', 0) + hangup_causes.get('BUSY', 0)
        total_calls = sum(hangup_causes.values())
        if total_calls > 0 and busy_count / total_calls > 0.3:
            recommendations.append("Более 30% звонков завершаются сигналом 'занято'. Рекомендуется увеличить количество повторных попыток.")
        
        # Лучшие часы
        if hourly_stats:
            best_hours = sorted(hourly_stats, key=lambda x: x.answer_rate, reverse=True)[:3]
            best_hours_str = ", ".join([f"{h.hour}:00" for h in best_hours])
            recommendations.append(f"Лучшее время для звонков: {best_hours_str}. Рекомендуется запускать кампании в эти часы.")
        
        return recommendations
    
    def _format_phone_display(self, phone: str) -> str:
        """Форматирование номера для отображения (см. app.utils.phone)"""
        return _format_phone_display_shared(phone)
    
    def _format_duration(self, duration: Optional[int]) -> Optional[str]:
        """Форматирование длительности"""
        if duration is None:
            return None
        
        minutes = duration // 60
        seconds = duration % 60
        return f"{minutes:02d}:{seconds:02d}"
    
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
        # См. подробный комментарий в campaign.py::_log_audit() - тот же
        # фикс: снимок username/role на момент действия + IP/UA/correlation
        # из контекста запроса вместо вечного NULL.
        import json
        from app.core.logger import get_ip_address, get_user_agent, get_correlation_id, get_request_id
        await conn.execute("""
            INSERT INTO audit_log (
                user_id, username, user_role, action, entity_type, entity_id, details,
                ip_address, user_agent, correlation_id, request_id
            ) VALUES (
                $1,
                (SELECT username FROM users WHERE id = $1),
                (SELECT role FROM users WHERE id = $1),
                $2, $3, $4, $5, $6, $7, $8, $9
            )
        """, user_id, action, entity_type, entity_id, json.dumps(details) if details else None,
             get_ip_address(), get_user_agent(), get_correlation_id(), get_request_id())
    
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
        logger.info("CallResultService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_call_service: Optional[CallResultService] = None


def get_call_service() -> CallResultService:
    """Получить глобальный экземпляр CallResultService"""
    global _call_service
    if _call_service is None:
        raise RuntimeError("CallResultService не инициализирован")
    return _call_service


def set_call_service(service: CallResultService) -> None:
    """Установить глобальный экземпляр CallResultService"""
    global _call_service
    _call_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "CallResultService",
    "CallError",
    "CallNotFoundError",
    "RecordingNotFoundError",
    "CallDeleteError",
    "get_call_service",
    "set_call_service",
]
