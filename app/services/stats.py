#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис статистики и аналитики
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Сбора системной статистики
- Статистики по кампаниям
- Статистики по звонкам
- Статистики по контактам
- Дневной/недельной/месячной аналитики
- Экспорта отчётов
"""

import json
import csv
import io
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient
from app.models.stats import (
    SystemStats, DailyStats, CampaignStatsSummary, FullStatsResponse
)
from app.models.campaign import CampaignStatsResponse
from app.models.call import CallStatsResponse, DailyCallStatsResponse
from app.models.incoming import IncomingCallStatsResponse
from prometheus_client import Gauge, Counter


# =============================================
# Метрики
# =============================================
stats_calls_total_gauge = Gauge(
    'autodialer_stats_calls_total',
    'Total calls in stats'
)
stats_contacts_total_gauge = Gauge(
    'autodialer_stats_contacts_total',
    'Total contacts in stats'
)
stats_campaigns_active_gauge = Gauge(
    'autodialer_stats_campaigns_active',
    'Active campaigns'
)
stats_export_counter = Counter(
    'autodialer_stats_exports_total',
    'Total stats exports',
    ['format']
)


# =============================================
# Исключения
# =============================================
class StatsError(Exception):
    """Базовое исключение сервиса статистики"""
    pass


# =============================================
# Модели данных
# =============================================
@dataclass
class DateRange:
    """Диапазон дат"""
    from_date: date
    to_date: date
    
    @property
    def days(self) -> int:
        return (self.to_date - self.from_date).days + 1


# =============================================
# Сервис статистики
# =============================================
class StatsService:
    """
    Сервис статистики и аналитики.
    
    Отвечает за:
    - Сбор системной статистики
    - Статистику по кампаниям и звонкам
    - Аналитику по периодам
    - Экспорт отчётов
    """
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        
        logger.info("StatsService инициализирован")
    
    # =============================================
    # Системная статистика
    # =============================================
    async def get_system_stats(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> SystemStats:
        """
        Получить системную статистику.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            Системная статистика
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        async with self.db_pool.acquire() as conn:
            # Кампании
            campaigns = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'running' THEN 1 END) as active
                FROM campaigns
                WHERE created_at::date >= $1 AND created_at::date <= $2
            """, from_date, to_date)
            
            # Контакты
            contacts = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                    COUNT(CASE WHEN blacklisted = TRUE THEN 1 END) as blacklisted
                FROM contacts
                WHERE deleted_at IS NULL
            """)
            
            # Звонки
            calls = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN created_at::date = CURRENT_DATE THEN 1 END) as today,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    AVG(duration) as avg_duration,
                    COALESCE(SUM(duration), 0) as total_duration
                FROM call_results
                WHERE created_at::date >= $1 AND created_at::date <= $2
            """, from_date, to_date)
            
            total_calls = calls['total'] or 0
            agreed = calls['agreed'] or 0
            
            stats_calls_total_gauge.set(total_calls)
            stats_contacts_total_gauge.set(contacts['total'] or 0)
            stats_campaigns_active_gauge.set(campaigns['active'] or 0)
            
            return SystemStats(
                total_campaigns=campaigns['total'] or 0,
                active_campaigns=campaigns['active'] or 0,
                total_contacts=contacts['total'] or 0,
                active_contacts=contacts['active'] or 0,
                blacklisted_contacts=contacts['blacklisted'] or 0,
                total_calls=total_calls,
                calls_today=calls['today'] or 0,
                agreed_calls=agreed,
                conversion_rate=round(agreed / total_calls * 100, 2) if total_calls > 0 else 0.0,
                avg_call_duration=round(calls['avg_duration'] or 0, 2),
                total_call_duration=calls['total_duration'] or 0
            )
    
    async def get_full_stats(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> FullStatsResponse:
        """
        Получить полную статистику системы.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            Полная статистика
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        # Системная статистика
        system = await self.get_system_stats(from_date, to_date)
        
        # Дневная статистика
        daily = await self.get_daily_stats(from_date, to_date)
        
        # Статистика по кампаниям
        by_campaign = await self.get_campaigns_summary(from_date, to_date)
        
        # Статистика по статусам
        by_status = await self.get_stats_by_status(from_date, to_date)
        
        return FullStatsResponse(
            system=system,
            daily=daily,
            by_campaign=by_campaign,
            by_status=by_status
        )
    
    # =============================================
    # Дневная/периодическая статистика
    # =============================================
    async def get_daily_stats(
        self,
        from_date: date,
        to_date: date
    ) -> List[DailyStats]:
        """
        Получить дневную статистику.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            Список дневной статистики
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    created_at::date as date,
                    COUNT(*) as total_calls,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status = 'declined' THEN 1 END) as declined,
                    COUNT(CASE WHEN status = 'busy' THEN 1 END) as busy,
                    COUNT(CASE WHEN status = 'noanswer' THEN 1 END) as noanswer,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                    AVG(duration) as avg_duration
                FROM call_results
                WHERE created_at::date >= $1 AND created_at::date <= $2
                GROUP BY created_at::date
                ORDER BY date DESC
            """, from_date, to_date)
            
            result = []
            for row in rows:
                total = row['total_calls']
                agreed = row['agreed'] or 0
                
                result.append(DailyStats(
                    date=row['date'].isoformat() if row['date'] else "",
                    total_calls=total,
                    agreed=agreed,
                    declined=row['declined'] or 0,
                    busy=row['busy'] or 0,
                    noanswer=row['noanswer'] or 0,
                    failed=row['failed'] or 0,
                    conversion_rate=round(agreed / total * 100, 2) if total > 0 else 0.0,
                    avg_duration=round(row['avg_duration'] or 0, 2)
                ))
            
            return result
    
    async def get_weekly_stats(self, weeks: int = 12) -> List[Dict[str, Any]]:
        """
        Получить недельную статистику.
        
        Args:
            weeks: Количество недель
        
        Returns:
            Список недельной статистики
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    DATE_TRUNC('week', created_at) as week_start,
                    COUNT(*) as total_calls,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status = 'declined' THEN 1 END) as declined,
                    AVG(duration) as avg_duration
                FROM call_results
                WHERE created_at >= NOW() - INTERVAL '1 week' * $1
                GROUP BY week_start
                ORDER BY week_start DESC
            """, weeks)
            
            result = []
            for row in rows:
                total = row['total_calls']
                agreed = row['agreed'] or 0
                
                result.append({
                    "week_start": row['week_start'].isoformat() if row['week_start'] else None,
                    "total_calls": total,
                    "agreed": agreed,
                    "declined": row['declined'] or 0,
                    "conversion_rate": round(agreed / total * 100, 2) if total > 0 else 0.0,
                    "avg_duration": round(row['avg_duration'] or 0, 2)
                })
            
            return result
    
    async def get_monthly_stats(self, months: int = 12) -> List[Dict[str, Any]]:
        """
        Получить месячную статистику.
        
        Args:
            months: Количество месяцев
        
        Returns:
            Список месячной статистики
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    DATE_TRUNC('month', created_at) as month_start,
                    COUNT(*) as total_calls,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status = 'declined' THEN 1 END) as declined,
                    AVG(duration) as avg_duration
                FROM call_results
                WHERE created_at >= NOW() - INTERVAL '1 month' * $1
                GROUP BY month_start
                ORDER BY month_start DESC
            """, months)
            
            result = []
            for row in rows:
                total = row['total_calls']
                agreed = row['agreed'] or 0
                
                result.append({
                    "month_start": row['month_start'].isoformat() if row['month_start'] else None,
                    "total_calls": total,
                    "agreed": agreed,
                    "declined": row['declined'] or 0,
                    "conversion_rate": round(agreed / total * 100, 2) if total > 0 else 0.0,
                    "avg_duration": round(row['avg_duration'] or 0, 2)
                })
            
            return result
    
    async def get_hourly_stats(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Получить почасовую статистику.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            Список почасовой статистики
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    EXTRACT(HOUR FROM created_at) as hour,
                    COUNT(*) as total_calls,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status IN ('agreed', 'declined') THEN 1 END) as answered
                FROM call_results
                WHERE created_at::date >= $1 AND created_at::date <= $2
                GROUP BY hour
                ORDER BY hour
            """, from_date, to_date)
            
            result = []
            for row in rows:
                hour = int(row['hour'])
                total = row['total_calls']
                answered = row['answered'] or 0
                agreed = row['agreed'] or 0
                
                result.append({
                    "hour": hour,
                    "total_calls": total,
                    "agreed": agreed,
                    "answered": answered,
                    "answer_rate": round(answered / total * 100, 2) if total > 0 else 0.0,
                    "conversion_rate": round(agreed / total * 100, 2) if total > 0 else 0.0
                })
            
            return result
    
    async def get_weekday_stats(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Получить статистику по дням недели.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            Список статистики по дням недели
        """
        if not from_date:
            from_date = date.today() - timedelta(days=90)
        if not to_date:
            to_date = date.today()
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    EXTRACT(DOW FROM created_at) as weekday,
                    COUNT(*) as total_calls,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    COUNT(CASE WHEN status IN ('agreed', 'declined') THEN 1 END) as answered
                FROM call_results
                WHERE created_at::date >= $1 AND created_at::date <= $2
                GROUP BY weekday
                ORDER BY weekday
            """, from_date, to_date)
            
            weekday_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
            result = []
            
            for row in rows:
                weekday = int(row['weekday'])
                total = row['total_calls']
                answered = row['answered'] or 0
                agreed = row['agreed'] or 0
                
                result.append({
                    "weekday": weekday,
                    "weekday_name": weekday_names[weekday] if weekday < 7 else str(weekday),
                    "total_calls": total,
                    "agreed": agreed,
                    "answered": answered,
                    "answer_rate": round(answered / total * 100, 2) if total > 0 else 0.0,
                    "conversion_rate": round(agreed / total * 100, 2) if total > 0 else 0.0
                })
            
            return result
    
    # =============================================
    # Статистика по кампаниям
    # =============================================
    async def get_campaigns_summary(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[CampaignStatsSummary]:
        """
        Получить сводку по кампаниям.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            Список статистики по кампаниям
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    c.id as campaign_id,
                    c.name as campaign_name,
                    c.status,
                    COUNT(cr.id) as total_calls,
                    COUNT(CASE WHEN cr.status = 'agreed' THEN 1 END) as agreed
                FROM campaigns c
                LEFT JOIN call_results cr ON c.id = cr.campaign_id
                    AND cr.created_at::date >= $1 
                    AND cr.created_at::date <= $2
                WHERE c.created_at::date >= $1 AND c.created_at::date <= $2
                GROUP BY c.id, c.name, c.status
                ORDER BY total_calls DESC
            """, from_date, to_date)
            
            result = []
            for row in rows:
                total = row['total_calls']
                agreed = row['agreed'] or 0
                
                result.append(CampaignStatsSummary(
                    campaign_id=row['campaign_id'],
                    campaign_name=row['campaign_name'],
                    status=row['status'],
                    total_calls=total,
                    agreed=agreed,
                    conversion_rate=round(agreed / total * 100, 2) if total > 0 else 0.0
                ))
            
            return result
    
    async def get_top_campaigns(
        self,
        limit: int = 10,
        metric: str = "total_calls",
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Получить топ кампаний по метрике.
        
        Args:
            limit: Количество записей
            metric: Метрика (total_calls, agreed, conversion_rate)
            from_date: С даты
            to_date: По дату
        
        Returns:
            Список топ кампаний
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        order_by = {
            "total_calls": "total_calls DESC",
            "agreed": "agreed DESC",
            "conversion_rate": "CASE WHEN total_calls > 0 THEN agreed::float / total_calls ELSE 0 END DESC"
        }.get(metric, "total_calls DESC")
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT 
                    c.id,
                    c.name,
                    COUNT(cr.id) as total_calls,
                    COUNT(CASE WHEN cr.status = 'agreed' THEN 1 END) as agreed,
                    CASE 
                        WHEN COUNT(cr.id) > 0 
                        THEN ROUND(COUNT(CASE WHEN cr.status = 'agreed' THEN 1 END)::numeric / COUNT(cr.id) * 100, 2)
                        ELSE 0 
                    END as conversion_rate
                FROM campaigns c
                LEFT JOIN call_results cr ON c.id = cr.campaign_id
                    AND cr.created_at::date >= $1 
                    AND cr.created_at::date <= $2
                GROUP BY c.id, c.name
                ORDER BY {order_by}
                LIMIT $3
            """, from_date, to_date, limit)
            
            return [dict(row) for row in rows]
    
    # =============================================
    # Статистика по звонкам
    # =============================================
    async def get_stats_by_status(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> Dict[str, int]:
        """
        Получить статистику по статусам звонков.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            Словарь статус -> количество
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT status, COUNT(*) as count
                FROM call_results
                WHERE created_at::date >= $1 AND created_at::date <= $2
                GROUP BY status
            """, from_date, to_date)
            
            return {row['status']: row['count'] for row in rows}
    
    async def get_top_phones(
        self,
        limit: int = 20,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Получить топ номеров по количеству звонков.
        
        Args:
            limit: Количество записей
            from_date: С даты
            to_date: По дату
        
        Returns:
            Список топ номеров
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    phone,
                    COUNT(*) as total_calls,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed,
                    AVG(duration) as avg_duration
                FROM call_results
                WHERE created_at::date >= $1 AND created_at::date <= $2
                GROUP BY phone
                ORDER BY total_calls DESC
                LIMIT $3
            """, from_date, to_date, limit)
            
            return [dict(row) for row in rows]
    
    async def get_hangup_causes_stats(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> Dict[str, int]:
        """
        Получить статистику по причинам завершения звонков.
        
        Args:
            from_date: С даты
            to_date: По дату
        
        Returns:
            Словарь причина -> количество
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT hangup_cause, COUNT(*) as count
                FROM call_results
                WHERE created_at::date >= $1 AND created_at::date <= $2
                AND hangup_cause IS NOT NULL
                GROUP BY hangup_cause
                ORDER BY count DESC
            """, from_date, to_date)
            
            return {row['hangup_cause']: row['count'] for row in rows}
    
    # =============================================
    # Статистика по контактам
    # =============================================
    async def get_contacts_stats(self) -> Dict[str, Any]:
        """Получить статистику по контактам"""
        async with self.db_pool.acquire() as conn:
            totals = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active,
                    COUNT(CASE WHEN blacklisted = TRUE THEN 1 END) as blacklisted,
                    COUNT(CASE WHEN total_calls > 0 THEN 1 END) as with_calls,
                    COUNT(CASE WHEN created_at::date > CURRENT_DATE - INTERVAL '30 days' THEN 1 END) as new_last_30_days
                FROM contacts
                WHERE deleted_at IS NULL
            """)
            
            by_source = await conn.fetch("""
                SELECT source, COUNT(*) as count
                FROM contacts
                WHERE deleted_at IS NULL
                GROUP BY source
                ORDER BY count DESC
            """)
            
            return {
                "total": totals['total'] or 0,
                "active": totals['active'] or 0,
                "blacklisted": totals['blacklisted'] or 0,
                "with_calls": totals['with_calls'] or 0,
                "new_last_30_days": totals['new_last_30_days'] or 0,
                "by_source": {row['source']: row['count'] for row in by_source}
            }
    
    # =============================================
    # Статистика по входящим звонкам
    # =============================================
    async def get_incoming_stats(
        self,
        days: int = 30
    ) -> IncomingCallStatsResponse:
        """
        Получить статистику по входящим звонкам.
        
        Args:
            days: Период в днях
        
        Returns:
            Статистика входящих звонков
        """
        async with self.db_pool.acquire() as conn:
            from_date = date.today() - timedelta(days=days)
            
            row = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total,
                    SUM(duration) as total_duration,
                    AVG(duration) as avg_duration,
                    SUM(file_size) as total_size,
                    COUNT(CASE WHEN listened = FALSE THEN 1 END) as new_count,
                    COUNT(CASE WHEN listened = TRUE THEN 1 END) as listened_count,
                    COUNT(CASE WHEN status = 'archived' THEN 1 END) as archived_count
                FROM incoming_calls
                WHERE call_date::date >= $1
            """, from_date)
            
            # Статусы транскрибации
            transcription_rows = await conn.fetch("""
                SELECT transcription_status, COUNT(*) as count
                FROM incoming_calls
                WHERE call_date::date >= $1
                GROUP BY transcription_status
            """, from_date)
            transcription = {row['transcription_status']: row['count'] for row in transcription_rows}
            
            # По дням
            daily_rows = await conn.fetch("""
                SELECT 
                    call_date::date as date,
                    COUNT(*) as count,
                    SUM(duration) as duration
                FROM incoming_calls
                WHERE call_date::date >= $1
                GROUP BY call_date::date
                ORDER BY date DESC
            """, from_date)
            daily_stats = [dict(row) for row in daily_rows]
            
            # По часам
            hourly_rows = await conn.fetch("""
                SELECT 
                    EXTRACT(HOUR FROM call_date) as hour,
                    COUNT(*) as count
                FROM incoming_calls
                WHERE call_date::date >= $1
                GROUP BY hour
                ORDER BY hour
            """, from_date)
            hourly_stats = [{'hour': int(row['hour']), 'count': row['count']} for row in hourly_rows]
            
            # Топ номеров
            top_callers = await conn.fetch("""
                SELECT 
                    caller_number,
                    COUNT(*) as calls,
                    SUM(duration) as total_duration
                FROM incoming_calls
                WHERE call_date::date >= $1
                GROUP BY caller_number
                ORDER BY calls DESC
                LIMIT 10
            """, from_date)
            
            # По дням недели
            weekday_rows = await conn.fetch("""
                SELECT 
                    EXTRACT(DOW FROM call_date) as weekday,
                    COUNT(*) as count
                FROM incoming_calls
                WHERE call_date::date >= $1
                GROUP BY weekday
                ORDER BY weekday
            """, from_date)
            by_weekday = {int(row['weekday']): row['count'] for row in weekday_rows}
            
            return IncomingCallStatsResponse(
                period_days=days,
                from_date=datetime.combine(from_date, datetime.min.time()),
                to_date=datetime.utcnow(),
                total=row['total'] or 0,
                total_duration=row['total_duration'] or 0,
                avg_duration=round(row['avg_duration'] or 0, 2),
                total_size=row['total_size'] or 0,
                new_count=row['new_count'] or 0,
                listened_count=row['listened_count'] or 0,
                archived_count=row['archived_count'] or 0,
                transcription=transcription,
                daily_stats=daily_stats,
                hourly_stats=hourly_stats,
                top_callers=[dict(r) for r in top_callers],
                by_weekday=by_weekday
            )
    
    # =============================================
    # Дашборд
    # =============================================
    async def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Получить данные для дашборда.
        
        Returns:
            Данные для дашборда
        """
        today = date.today()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        async with self.db_pool.acquire() as conn:
            # Ключевые метрики
            metrics = await conn.fetchrow("""
                SELECT 
                    (SELECT COUNT(*) FROM campaigns WHERE status = 'running') as active_campaigns,
                    (SELECT COUNT(*) FROM call_results WHERE created_at::date = $1) as calls_today,
                    (SELECT COUNT(*) FROM call_results WHERE created_at::date >= $2 AND status = 'agreed') as agreed_week,
                    (SELECT AVG(duration) FROM call_results WHERE created_at::date >= $2) as avg_duration,
                    (SELECT COUNT(*) FROM contacts WHERE created_at::date >= $2) as new_contacts,
                    (SELECT COUNT(*) FROM incoming_calls WHERE call_date::date = $1) as incoming_today
            """, today, week_ago)
            
            # График звонков за неделю
            calls_chart = await conn.fetch("""
                SELECT 
                    created_at::date as date,
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'agreed' THEN 1 END) as agreed
                FROM call_results
                WHERE created_at::date >= $1
                GROUP BY created_at::date
                ORDER BY date
            """, week_ago)
            
            # Топ кампаний
            top_campaigns = await conn.fetch("""
                SELECT 
                    c.id,
                    c.name,
                    COUNT(cr.id) as calls,
                    COUNT(CASE WHEN cr.status = 'agreed' THEN 1 END) as agreed
                FROM campaigns c
                LEFT JOIN call_results cr ON c.id = cr.campaign_id
                    AND cr.created_at::date >= $1
                WHERE c.status = 'running'
                GROUP BY c.id, c.name
                ORDER BY calls DESC
                LIMIT 5
            """, week_ago)
            
            # Статусы звонков
            status_pie = await conn.fetch("""
                SELECT status, COUNT(*) as count
                FROM call_results
                WHERE created_at::date >= $1
                GROUP BY status
            """, week_ago)
            
            # Активность по часам
            hourly_activity = await conn.fetch("""
                SELECT 
                    EXTRACT(HOUR FROM created_at) as hour,
                    COUNT(*) as count
                FROM call_results
                WHERE created_at::date >= $1
                GROUP BY hour
                ORDER BY hour
            """, week_ago)
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "metrics": {
                    "active_campaigns": metrics['active_campaigns'] or 0,
                    "calls_today": metrics['calls_today'] or 0,
                    "agreed_week": metrics['agreed_week'] or 0,
                    "avg_duration": round(metrics['avg_duration'] or 0, 1),
                    "new_contacts": metrics['new_contacts'] or 0,
                    "incoming_today": metrics['incoming_today'] or 0
                },
                "calls_chart": [
                    {
                        "date": row['date'].isoformat() if row['date'] else None,
                        "total": row['total'],
                        "agreed": row['agreed']
                    }
                    for row in calls_chart
                ],
                "top_campaigns": [dict(row) for row in top_campaigns],
                "status_distribution": {
                    row['status']: row['count'] for row in status_pie
                },
                "hourly_activity": [
                    {"hour": int(row['hour']), "count": row['count']}
                    for row in hourly_activity
                ]
            }
    
    # =============================================
    # Экспорт отчётов
    # =============================================
    async def export_stats(
        self,
        report_type: str,
        format: str = "csv",
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> bytes:
        """
        Экспортировать статистику.
        
        Args:
            report_type: Тип отчёта (calls, campaigns, contacts, incoming)
            format: Формат (csv, json)
            from_date: С даты
            to_date: По дату
        
        Returns:
            Данные отчёта
        """
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        stats_export_counter.labels(format=format).inc()
        
        if report_type == "calls":
            return await self._export_calls_stats(format, from_date, to_date)
        elif report_type == "campaigns":
            return await self._export_campaigns_stats(format, from_date, to_date)
        elif report_type == "contacts":
            return await self._export_contacts_stats(format)
        elif report_type == "incoming":
            return await self._export_incoming_stats(format, from_date, to_date)
        else:
            raise StatsError(f"Неизвестный тип отчёта: {report_type}")
    
    async def _export_calls_stats(
        self,
        format: str,
        from_date: date,
        to_date: date
    ) -> bytes:
        """Экспорт статистики звонков"""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    created_at::date as date,
                    status,
                    COUNT(*) as count,
                    AVG(duration) as avg_duration,
                    SUM(duration) as total_duration
                FROM call_results
                WHERE created_at::date >= $1 AND created_at::date <= $2
                GROUP BY created_at::date, status
                ORDER BY date DESC, status
            """, from_date, to_date)
            
            if format == "csv":
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["date", "status", "count", "avg_duration", "total_duration"])
                
                for row in rows:
                    writer.writerow([
                        row['date'].isoformat() if row['date'] else "",
                        row['status'],
                        row['count'],
                        round(row['avg_duration'] or 0, 2),
                        row['total_duration'] or 0
                    ])
                
                return output.getvalue().encode('utf-8-sig')
            else:
                data = {
                    "exported_at": datetime.utcnow().isoformat(),
                    "from_date": from_date.isoformat(),
                    "to_date": to_date.isoformat(),
                    "data": [
                        {
                            "date": row['date'].isoformat() if row['date'] else None,
                            "status": row['status'],
                            "count": row['count'],
                            "avg_duration": round(row['avg_duration'] or 0, 2),
                            "total_duration": row['total_duration']
                        }
                        for row in rows
                    ]
                }
                return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    
    async def _export_campaigns_stats(
        self,
        format: str,
        from_date: date,
        to_date: date
    ) -> bytes:
        """Экспорт статистики кампаний"""
        data = await self.get_campaigns_summary(from_date, to_date)
        
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["campaign_id", "campaign_name", "status", "total_calls", "agreed", "conversion_rate"])
            
            for item in data:
                writer.writerow([
                    item.campaign_id,
                    item.campaign_name,
                    item.status,
                    item.total_calls,
                    item.agreed,
                    item.conversion_rate
                ])
            
            return output.getvalue().encode('utf-8-sig')
        else:
            export_data = {
                "exported_at": datetime.utcnow().isoformat(),
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "data": [
                    {
                        "campaign_id": item.campaign_id,
                        "campaign_name": item.campaign_name,
                        "status": item.status,
                        "total_calls": item.total_calls,
                        "agreed": item.agreed,
                        "conversion_rate": item.conversion_rate
                    }
                    for item in data
                ]
            }
            return json.dumps(export_data, ensure_ascii=False, indent=2).encode('utf-8')
    
    async def _export_contacts_stats(self, format: str) -> bytes:
        """Экспорт статистики контактов"""
        stats = await self.get_contacts_stats()
        
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["metric", "value"])
            
            for key, value in stats.items():
                if key != "by_source":
                    writer.writerow([key, value])
            
            writer.writerow([])
            writer.writerow(["source", "count"])
            for source, count in stats.get("by_source", {}).items():
                writer.writerow([source, count])
            
            return output.getvalue().encode('utf-8-sig')
        else:
            export_data = {
                "exported_at": datetime.utcnow().isoformat(),
                "data": stats
            }
            return json.dumps(export_data, ensure_ascii=False, indent=2).encode('utf-8')
    
    async def _export_incoming_stats(
        self,
        format: str,
        from_date: date,
        to_date: date
    ) -> bytes:
        """Экспорт статистики входящих звонков"""
        days = (to_date - from_date).days + 1
        stats = await self.get_incoming_stats(days)
        
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["metric", "value"])
            writer.writerow(["total_calls", stats.total])
            writer.writerow(["total_duration", stats.total_duration])
            writer.writerow(["avg_duration", stats.avg_duration])
            writer.writerow(["new", stats.new_count])
            writer.writerow(["listened", stats.listened_count])
            writer.writerow(["archived", stats.archived_count])
            
            writer.writerow([])
            writer.writerow(["status", "count"])
            for status, count in stats.transcription.items():
                writer.writerow([status, count])
            
            return output.getvalue().encode('utf-8-sig')
        else:
            export_data = {
                "exported_at": datetime.utcnow().isoformat(),
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "data": stats.model_dump()
            }
            return json.dumps(export_data, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    
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
        logger.info("StatsService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_stats_service: Optional[StatsService] = None


def get_stats_service() -> StatsService:
    """Получить глобальный экземпляр StatsService"""
    global _stats_service
    if _stats_service is None:
        raise RuntimeError("StatsService не инициализирован")
    return _stats_service


def set_stats_service(service: StatsService) -> None:
    """Установить глобальный экземпляр StatsService"""
    global _stats_service
    _stats_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "StatsService",
    "StatsError",
    "DateRange",
    "get_stats_service",
    "set_stats_service",
]
