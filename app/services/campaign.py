#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления кампаниями
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- Создания и управления кампаниями
- Запуска и остановки кампаний
- Управления контактами кампании
- Статистики кампаний
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from app.core.config import settings
from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS
from app.models.campaign import (
    CampaignStatus, CampaignPriority, ScheduleType,
    CampaignCreateRequest, CampaignUpdateRequest,
    CampaignResponse, CampaignDetailResponse, CampaignListResponse,
    CampaignStatsResponse, CampaignProgressResponse,
    RetryStrategySchema, CampaignScheduleSchema, DialerSettingsSchema
)
from app.utils.task_registry import TaskRegistry, get_task_registry
from prometheus_client import Counter


# =============================================
# Метрики
# =============================================
campaign_created_counter = Counter(
    'autodialer_campaigns_created_total',
    'Total campaigns created'
)
campaign_started_counter = Counter(
    'autodialer_campaigns_started_total',
    'Total campaigns started'
)
campaign_completed_counter = Counter(
    'autodialer_campaigns_completed_total',
    'Total campaigns completed'
)
campaign_failed_counter = Counter(
    'autodialer_campaigns_failed_total',
    'Total campaigns failed'
)


# =============================================
# Исключения
# =============================================
class CampaignError(Exception):
    """Базовое исключение сервиса кампаний"""
    pass


class CampaignNotFoundError(CampaignError):
    """Кампания не найдена"""
    pass


class CampaignAlreadyRunningError(CampaignError):
    """Кампания уже запущена"""
    pass


class CampaignNotRunningError(CampaignError):
    """Кампания не запущена"""
    pass


class CampaignNoContactsError(CampaignError):
    """В кампании нет контактов"""
    pass


class CampaignValidationError(CampaignError):
    """Ошибка валидации данных кампании"""
    pass


# =============================================
# Модели данных
# =============================================
@dataclass
class CampaignContext:
    """Контекст выполняющейся кампании"""
    campaign_id: int
    task_id: str
    started_at: datetime
    processed_contacts: int = 0
    current_cps: float = 0.0
    last_update: datetime = None
    
    def __post_init__(self):
        if self.last_update is None:
            self.last_update = self.started_at


# =============================================
# Сервис кампаний
# =============================================
class CampaignService:
    """
    Сервис управления кампаниями.
    
    Отвечает за:
    - CRUD операции с кампаниями
    - Запуск/остановку/паузу кампаний
    - Управление контактами кампании
    - Сбор статистики
    """
    
    def __init__(
        self,
        db_pool: ConnectionPool,
        redis_client: RedisClient,
        dialer_manager=None,
        task_registry: Optional[TaskRegistry] = None
    ):
        self.db_pool = db_pool
        self.redis = redis_client
        self.dialer_manager = dialer_manager
        self.task_registry = task_registry or get_task_registry()
        
        # Кеш активных кампаний
        self._active_campaigns: Dict[int, CampaignContext] = {}
        
        logger.info("CampaignService инициализирован")
    
    # =============================================
    # CRUD операции
    # =============================================
    async def create_campaign(
        self,
        request: CampaignCreateRequest,
        user_id: int
    ) -> int:
        """
        Создать новую кампанию.
        
        Args:
            request: Данные для создания кампании
            user_id: ID пользователя-создателя
        
        Returns:
            ID созданной кампании
        """
        # Валидация
        await self._validate_campaign_create(request)
        
        async with self.db_pool.acquire() as conn:
            # Вставляем кампанию
            campaign_id = await conn.fetchval("""
                INSERT INTO campaigns (
                    name, description, priority, status,
                    max_calls, cps, dial_mode, call_timeout, answer_timeout,
                    caller_id, caller_id_number, audio_id, dtmf_enabled, dtmf_timeout,
                    retry_strategy, schedule,
                    created_by, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8, $9,
                    $10, $11, $12, $13, $14,
                    $15, $16,
                    $17, NOW(), NOW()
                )
                RETURNING id
            """,
                request.name,
                request.description,
                request.priority,
                CampaignStatus.DRAFT.value,
                request.dialer_settings.max_calls,
                request.dialer_settings.cps,
                request.dialer_settings.dial_mode,
                request.dialer_settings.call_timeout,
                request.dialer_settings.answer_timeout,
                request.dialer_settings.caller_id,
                request.dialer_settings.caller_id_number,
                request.dialer_settings.audio_id,
                request.dialer_settings.dtmf_enabled,
                request.dialer_settings.dtmf_timeout,
                json.dumps(request.retry_strategy.model_dump()),
                json.dumps(request.schedule.model_dump()),
                user_id
            )
            
            # Добавляем контакты
            await self._add_contacts_to_campaign(
                conn,
                campaign_id,
                request.contact_group_ids,
                request.contact_ids,
                request.contact_filter
            )
            
            # Добавляем теги
            if request.tags:
                await self._add_campaign_tags(conn, campaign_id, request.tags)
            
            # Сохраняем метаданные
            if request.metadata:
                await conn.execute("""
                    UPDATE campaigns SET metadata = $1 WHERE id = $2
                """, json.dumps(request.metadata), campaign_id)
            
            # Логируем
            await self._log_audit(conn, user_id, 'campaign_created', 'campaign', campaign_id, {
                'name': request.name,
                'contacts_count': await self._get_campaign_contacts_count(conn, campaign_id)
            })
        
        campaign_created_counter.inc()
        logger.info(f"Кампания создана: {request.name} (ID: {campaign_id})")
        
        return campaign_id
    
    async def get_campaign(self, campaign_id: int) -> Optional[CampaignDetailResponse]:
        """Получить кампанию по ID"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    c.*,
                    u.username as created_by_name,
                    a.name as audio_name
                FROM campaigns c
                LEFT JOIN users u ON c.created_by = u.id
                LEFT JOIN audio_files a ON c.audio_id = a.id
                WHERE c.id = $1
            """, campaign_id)
            
            if not row:
                return None
            
            # Получаем статистику
            stats = await self._get_campaign_stats(conn, campaign_id)
            
            # Получаем группы контактов
            groups = await self._get_campaign_contact_groups(conn, campaign_id)
            
            # Получаем последние звонки
            recent_calls = await self._get_campaign_recent_calls(conn, campaign_id)
            
            # Парсим JSON поля
            retry_strategy = json.loads(row['retry_strategy']) if row['retry_strategy'] else {}
            schedule = json.loads(row['schedule']) if row['schedule'] else {}
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            tags = await self._get_campaign_tags(conn, campaign_id)
            
            return CampaignDetailResponse(
                id=row['id'],
                name=row['name'],
                description=row['description'],
                status=CampaignStatus(row['status']),
                priority=CampaignPriority(row['priority']),
                dialer_settings=DialerSettingsSchema(
                    max_calls=row['max_calls'],
                    cps=row['cps'],
                    dial_mode=row['dial_mode'],
                    call_timeout=row['call_timeout'],
                    answer_timeout=row['answer_timeout'],
                    caller_id=row['caller_id'],
                    caller_id_number=row['caller_id_number'],
                    audio_id=row['audio_id'],
                    audio_name=row['audio_name'],
                    dtmf_enabled=row['dtmf_enabled'] if row['dtmf_enabled'] is not None else True,
                    dtmf_timeout=row['dtmf_timeout'] if row['dtmf_timeout'] is not None else 8
                ),
                retry_strategy=RetryStrategySchema(**retry_strategy) if retry_strategy else None,
                schedule=CampaignScheduleSchema(**schedule) if schedule else None,
                audio_id=row['audio_id'],
                audio_name=row['audio_name'],
                created_by=row['created_by'],
                created_by_name=row['created_by_name'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                started_at=row['started_at'],
                paused_at=row['paused_at'],
                stopped_at=row['stopped_at'],
                completed_at=row['completed_at'],
                tags=tags,
                metadata=metadata,
                stats=stats,
                contact_groups=groups,
                recent_calls=recent_calls
            )
    
    async def update_campaign(
        self,
        campaign_id: int,
        request: CampaignUpdateRequest,
        user_id: int
    ) -> bool:
        """Обновить кампанию"""
        async with self.db_pool.acquire() as conn:
            # Проверяем существование и статус
            campaign = await conn.fetchrow(
                "SELECT status FROM campaigns WHERE id = $1",
                campaign_id
            )
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")
            
            # Нельзя обновлять запущенную кампанию (кроме некоторых полей)
            if campaign['status'] == CampaignStatus.RUNNING.value:
                raise CampaignError("Нельзя обновлять запущенную кампанию")
            
            updates = []
            params = []
            param_idx = 1
            
            if request.name is not None:
                updates.append(f"name = ${param_idx}")
                params.append(request.name)
                param_idx += 1
            
            if request.description is not None:
                updates.append(f"description = ${param_idx}")
                params.append(request.description)
                param_idx += 1
            
            if request.priority is not None:
                updates.append(f"priority = ${param_idx}")
                params.append(request.priority)
                param_idx += 1
            
            if request.dialer_settings:
                ds = request.dialer_settings
                updates.extend([
                    f"max_calls = ${param_idx}",
                    f"cps = ${param_idx + 1}",
                    f"dial_mode = ${param_idx + 2}",
                    f"call_timeout = ${param_idx + 3}",
                    f"answer_timeout = ${param_idx + 4}",
                    f"caller_id = ${param_idx + 5}",
                    f"caller_id_number = ${param_idx + 6}",
                    f"audio_id = ${param_idx + 7}",
                    f"dtmf_enabled = ${param_idx + 8}",
                    f"dtmf_timeout = ${param_idx + 9}"
                ])
                params.extend([
                    ds.max_calls, ds.cps, ds.dial_mode,
                    ds.call_timeout, ds.answer_timeout,
                    ds.caller_id, ds.caller_id_number, ds.audio_id,
                    ds.dtmf_enabled, ds.dtmf_timeout
                ])
                param_idx += 10
            
            if request.retry_strategy is not None:
                updates.append(f"retry_strategy = ${param_idx}")
                params.append(json.dumps(request.retry_strategy.model_dump()))
                param_idx += 1
            
            if request.schedule is not None:
                updates.append(f"schedule = ${param_idx}")
                params.append(json.dumps(request.schedule.model_dump()))
                param_idx += 1
            
            if updates:
                updates.append(f"updated_at = NOW()")
                params.append(campaign_id)
                query = f"""
                    UPDATE campaigns 
                    SET {', '.join(updates)}
                    WHERE id = ${param_idx}
                """
                await conn.execute(query, *params)
            
            # Обновляем теги
            if request.tags is not None:
                await self._update_campaign_tags(conn, campaign_id, request.tags)
            
            # Обновляем метаданные
            if request.metadata is not None:
                await conn.execute("""
                    UPDATE campaigns 
                    SET metadata = $1 
                    WHERE id = $2
                """, json.dumps(request.metadata), campaign_id)
            
            await self._log_audit(conn, user_id, 'campaign_updated', 'campaign', campaign_id)
        
        logger.info(f"Кампания {campaign_id} обновлена")
        return True
    
    async def delete_campaign(self, campaign_id: int, user_id: int) -> bool:
        """Удалить кампанию"""
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow(
                "SELECT status FROM campaigns WHERE id = $1",
                campaign_id
            )
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")
            
            if campaign['status'] == CampaignStatus.RUNNING.value:
                raise CampaignError("Нельзя удалить запущенную кампанию")
            
            # Удаляем связи с контактами
            await conn.execute(
                "DELETE FROM campaign_contacts WHERE campaign_id = $1",
                campaign_id
            )
            
            # Удаляем теги
            await conn.execute(
                "DELETE FROM campaign_tags WHERE campaign_id = $1",
                campaign_id
            )
            
            # Удаляем кампанию
            await conn.execute(
                "DELETE FROM campaigns WHERE id = $1",
                campaign_id
            )
            
            await self._log_audit(conn, user_id, 'campaign_deleted', 'campaign', campaign_id)
        
        logger.info(f"Кампания {campaign_id} удалена")
        return True
    
    async def get_summary(self) -> Dict[str, int]:
        """
        Сводка по количеству кампаний в каждом статусе - для виджета
        "Сводка по кампаниям" на дашборде (App.dashboard.loadCampaignsSummary).
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status, COUNT(*) AS cnt FROM campaigns GROUP BY status"
            )

        by_status = {row['status']: row['cnt'] for row in rows}
        total = sum(by_status.values())

        return {
            "total": total,
            "running": by_status.get(CampaignStatus.RUNNING.value, 0),
            "completed": by_status.get(CampaignStatus.COMPLETED.value, 0),
            "draft": by_status.get(CampaignStatus.DRAFT.value, 0)
        }

    async def list_campaigns(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[List[CampaignStatus]] = None,
        priority: Optional[List[CampaignPriority]] = None,
        search: Optional[str] = None,
        created_by: Optional[int] = None,
        tags: Optional[List[str]] = None,
        sort_by: str = "created_at",
        sort_order: str = "DESC"
    ) -> CampaignListResponse:
        """Получить список кампаний с фильтрацией"""
        offset = (page - 1) * page_size
        
        async with self.db_pool.acquire() as conn:
            # Строим WHERE условия
            where_conditions = []
            params = []
            param_idx = 1
            
            if status:
                placeholders = ','.join([f"${param_idx + i}" for i in range(len(status))])
                where_conditions.append(f"c.status IN ({placeholders})")
                params.extend([s.value for s in status])
                param_idx += len(status)
            
            if priority:
                placeholders = ','.join([f"${param_idx + i}" for i in range(len(priority))])
                where_conditions.append(f"c.priority IN ({placeholders})")
                params.extend([p.value for p in priority])
                param_idx += len(priority)
            
            if search:
                where_conditions.append(f"(c.name ILIKE ${param_idx} OR c.description ILIKE ${param_idx})")
                params.append(f"%{search}%")
                param_idx += 1
            
            if created_by:
                where_conditions.append(f"c.created_by = ${param_idx}")
                params.append(created_by)
                param_idx += 1
            
            if tags:
                where_conditions.append(f"""
                    c.id IN (
                        SELECT campaign_id FROM campaign_tags 
                        WHERE tag = ANY(${param_idx})
                    )
                """)
                params.append(tags)
                param_idx += 1
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            # Получаем общее количество
            count_query = f"""
                SELECT COUNT(*) FROM campaigns c
                {where_clause}
            """
            total = await conn.fetchval(count_query, *params)
            
            # Получаем данные
            query = f"""
                SELECT 
                    c.*,
                    u.username as created_by_name,
                    a.name as audio_name
                FROM campaigns c
                LEFT JOIN users u ON c.created_by = u.id
                LEFT JOIN audio_files a ON c.audio_id = a.id
                {where_clause}
                ORDER BY c.{sort_by} {sort_order}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([page_size, offset])
            
            rows = await conn.fetch(query, *params)
            
            items = []
            for row in rows:
                retry_strategy = json.loads(row['retry_strategy']) if row['retry_strategy'] else {}
                schedule = json.loads(row['schedule']) if row['schedule'] else {}
                metadata = json.loads(row['metadata']) if row['metadata'] else {}
                tags = await self._get_campaign_tags(conn, row['id'])
                stats = await self._get_campaign_stats(conn, row['id'])

                items.append(CampaignResponse(
                    id=row['id'],
                    name=row['name'],
                    description=row['description'],
                    status=CampaignStatus(row['status']),
                    priority=CampaignPriority(row['priority']),
                    dialer_settings=DialerSettingsSchema(
                        max_calls=row['max_calls'],
                        cps=row['cps'],
                        dial_mode=row['dial_mode'],
                        call_timeout=row['call_timeout'],
                        answer_timeout=row['answer_timeout'],
                        caller_id=row['caller_id'],
                        caller_id_number=row['caller_id_number'],
                        audio_id=row['audio_id'],
                        audio_name=row['audio_name'],
                        dtmf_enabled=row['dtmf_enabled'] if row['dtmf_enabled'] is not None else True,
                        dtmf_timeout=row['dtmf_timeout'] if row['dtmf_timeout'] is not None else 8
                    ),
                    retry_strategy=RetryStrategySchema(**retry_strategy) if retry_strategy else None,
                    schedule=CampaignScheduleSchema(**schedule) if schedule else None,
                    audio_id=row['audio_id'],
                    audio_name=row['audio_name'],
                    created_by=row['created_by'],
                    created_by_name=row['created_by_name'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    started_at=row['started_at'],
                    paused_at=row['paused_at'],
                    stopped_at=row['stopped_at'],
                    completed_at=row['completed_at'],
                    tags=tags,
                    metadata=metadata,
                    stats=stats
                ))
            
            return CampaignListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=(total + page_size - 1) // page_size
            )
    
    # =============================================
    # Связь выбранного аудио с файлом, который реально ищет диалплан
    # =============================================
    async def _link_campaign_audio(
        self,
        conn,
        campaign_id: int,
        audio_id: Optional[int]
    ) -> None:
        """
        [sub-media] в asterisk/extensions.conf проверяет наличие файла
        tts/main_<campaign_id>.sln и, если его нет, проигрывает
        tts/default.sln:

            Set(AUDIO_FILE=tts/main_${CAMPAIGN_ID})
            GotoIf($[${STAT(e,${AUDIO_FILE})} = 1]?play)
            Set(AUDIO_FILE=tts/default)

        TTS-генерация (AudioService._generate_audio_sync) сохраняет файлы
        под случайным именем tts_<timestamp>_<uuid>.sln, никак не
        привязанным к campaign_id - ничего в приложении раньше не
        создавало файл с именем main_<campaign_id>.sln, поэтому какое бы
        аудио ни было выбрано в форме кампании (dialer_settings.audio_id),
        при звонках всегда проигрывался только общий tts/default.sln.
        Линкуем выбранный файл под ожидаемым диалпланом именем при каждом
        запуске кампании, и убираем линк, если аудио не выбрано (или файл
        пропал) - иначе повторный запуск той же кампании с другим/снятым
        аудио тихо продолжал бы играть сообщение от предыдущего запуска.
        """
        target = settings.TTS_DIR / f"main_{campaign_id}.sln"
        source: Optional[Path] = None

        if audio_id:
            row = await conn.fetchrow(
                "SELECT file_path FROM audio_files WHERE id = $1",
                audio_id
            )
            if row and row['file_path']:
                candidate = Path(row['file_path'])
                if candidate.exists():
                    source = candidate
                else:
                    logger.warning(
                        f"Кампания {campaign_id}: аудиофайл audio_id={audio_id} "
                        f"не найден на диске ({candidate}), использую tts/default"
                    )

        try:
            if target.is_symlink() or target.exists():
                target.unlink()
            if source:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(source)
        except OSError as e:
            logger.error(f"Кампания {campaign_id}: не удалось связать аудио ({target}): {e}")

    # =============================================
    # Управление жизненным циклом кампании
    # =============================================
    async def start_campaign(
        self,
        campaign_id: int,
        user_id: int,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Запустить кампанию.
        
        Args:
            campaign_id: ID кампании
            user_id: ID пользователя
            force: Принудительный запуск (игнорировать расписание)
        
        Returns:
            Информация о запуске
        """
        # Проверяем, включена ли система
        if not await self.redis.is_system_enabled():
            raise CampaignError("Система отключена")
        
        # Проверяем dialer
        if not self.dialer_manager:
            raise CampaignError("Dialer не инициализирован")
        
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow("""
                SELECT * FROM campaigns WHERE id = $1 FOR UPDATE
            """, campaign_id)
            
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")
            
            if campaign['status'] == CampaignStatus.RUNNING.value:
                raise CampaignAlreadyRunningError("Кампания уже запущена")

            # Повторный запуск (completed/stopped/failed, не draft) - без
            # этого обзвон физически нельзя было повторить: ниже контакты
            # выбираются с "cc.status != 'completed'", а завершённые
            # контакты (после прошлого прогона - agreed/declined, или
            # busy/noanswer/failed с исчерпанными попытками, см.
            # _schedule_retry() в dialer.py) как раз в статусе 'completed'.
            # Пользователь явно просил возможность запускать один и тот же
            # обзвон по той же группе сколько угодно раз - каждый повторный
            # запуск обзванивает ВСЕХ заново, а не только тех, кто ещё не
            # был обработан в прошлый раз.
            if campaign['status'] != CampaignStatus.DRAFT.value:
                await conn.execute("""
                    UPDATE campaign_contacts
                    SET status = 'pending', retry_count = 0, next_retry_at = NULL
                    WHERE campaign_id = $1
                """, campaign_id)

            # Проверяем расписание (если не force)
            if not force:
                schedule = json.loads(campaign['schedule']) if campaign['schedule'] else {}
                if schedule.get('enabled'):
                    if not self._check_schedule(schedule):
                        raise CampaignError("Кампания не может быть запущена по расписанию")

            # Проверяем наличие контактов
            contacts_count = await conn.fetchval("""
                SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id = $1
            """, campaign_id)
            
            if contacts_count == 0:
                raise CampaignNoContactsError("В кампании нет контактов")
            
            # Получаем контакты для обзвона
            contacts = await conn.fetch("""
                SELECT c.phone, COALESCE(cc.retry_count, 0) as retry_count
                FROM contacts c
                JOIN campaign_contacts cc ON c.id = cc.contact_id
                WHERE cc.campaign_id = $1 
                AND NOT c.blacklisted
                AND cc.status != 'completed'
            """, campaign_id)

            # [sub-media] в asterisk/extensions.conf ищет файл по имени
            # tts/main_<campaign_id>.sln - без этого шага никакой TTS,
            # выбранный в форме кампании (dialer_settings.audio_id),
            # никогда реально не проигрывался, звонящим всегда шёл общий
            # tts/default.sln независимо от выбора.
            await self._link_campaign_audio(conn, campaign_id, campaign['audio_id'])

            # Обновляем статус кампании
            await conn.execute("""
                UPDATE campaigns
                SET status = $1, started_at = NOW(), updated_at = NOW()
                WHERE id = $2
            """, CampaignStatus.RUNNING.value, campaign_id)

            # Отдельная запись в campaign_runs на КАЖДЫЙ запуск - в отличие
            # от campaigns.started_at/completed_at (которые каждый повторный
            # запуск перезаписывает), это и есть та самая история "когда
            # запускали, когда завершился", которую видно на вкладке
            # "История обзвонов".
            # audio_id - аудио кампании НА МОМЕНТ этого конкретного запуска
            # (campaign['audio_id']), а не то, что может стоять у кампании
            # позже - иначе get_campaign_run()'s "X из Y" сравнивал бы старые
            # запуски с уже сменившимся аудио.
            run_id = await conn.fetchval("""
                INSERT INTO campaign_runs (campaign_id, status, total_contacts, started_by, audio_id)
                VALUES ($1, 'running', $2, $3, $4)
                RETURNING id
            """, campaign_id, len(contacts), user_id, campaign['audio_id'])

            await self._log_audit(conn, user_id, 'campaign_started', 'campaign', campaign_id, {
                'contacts_count': len(contacts),
                'run_id': run_id
            })
        
        # Ни max_calls, ни cps НЕ применяются из campaign[...] здесь: оба -
        # общие (не per-campaign) атрибуты на dialer_manager. max_calls
        # проверяется против ГЛОБАЛЬНОГО счётчика активных каналов в Redis,
        # cps_limiter - тот же самый объект, который делит между собой ВСЕ
        # одновременно запущенные кампании (см. _start_call() в dialer.py).
        # Если бы кампания Б стартовала с другим значением, пока кампания А
        # ещё дозванивает, это тихо подменяло бы единый лимит для ОБЕИХ
        # сразу, а не только для Б. Единственный реальный источник обоих
        # значений - глобальные настройки admin'а (Настройки → Обзвон:
        # dialer.max_calls, dialer.default_cps), которые уже применяются
        # при старте воркера (app/__init__.py) и живьём при изменении
        # (SettingsService._apply_dialer_max_calls/_apply_dialer_cps) -
        # только администратор знает реальный потолок каналов и скорость
        # набора, которые выдержит транк/сервер, так что per-campaign
        # override сюда не пишем.

        # Запускаем задачу обзвона
        task_id = f"campaign_{campaign_id}"

        async def dial_task():
            """Задача обзвона"""
            # Раньше здесь создавался ОТДЕЛЬНЫЙ TokenBucket(campaign['cps']),
            # так что при нескольких одновременных кампаниях каждая дозванивала
            # на полной своей скорости независимо, и суммарный темп набора по
            # системе мог кратно превышать то, что настроил администратор.
            # dialer_manager.cps_limiter - один на все кампании сразу
            # (тот же объект, что и в _start_call()) - acquire() здесь просто
            # ждёт своей очереди в этом общем лимите, вместо того чтобы
            # заводить параллельный, никак не связанный с остальными счётчик.
            bucket = self.dialer_manager.cps_limiter
            processed = 0
            retry_strategy = json.loads(campaign['retry_strategy']) if campaign['retry_strategy'] else {}
            
            ctx = CampaignContext(
                campaign_id=campaign_id,
                task_id=task_id,
                started_at=datetime.utcnow()
            )
            self._active_campaigns[campaign_id] = ctx
            
            try:
                for contact in contacts:
                    # Проверяем статус системы и кампании
                    if not self.dialer_manager.running:
                        logger.info(f"Кампания {campaign_id}: dialer остановлен")
                        break
                    
                    if not await self.redis.is_system_enabled():
                        logger.info(f"Кампания {campaign_id}: система отключена")
                        break
                    
                    # Проверяем статус кампании в БД
                    async with self.db_pool.acquire() as conn:
                        status = await conn.fetchval(
                            "SELECT status FROM campaigns WHERE id = $1",
                            campaign_id
                        )
                        if status != CampaignStatus.RUNNING.value:
                            logger.info(f"Кампания {campaign_id}: статус изменён на {status}")
                            break
                    
                    # Ограничение скорости
                    await bucket.acquire()
                    
                    # Запускаем звонок
                    await self.dialer_manager.start_call(
                        contact['phone'],
                        campaign_id,
                        contact['retry_count']
                    )
                    
                    processed += 1
                    ctx.processed_contacts = processed
                    ctx.last_update = datetime.utcnow()
                    
                    # Обновляем прогресс в Redis
                    await self.redis.hset(
                        f"campaign_progress:{campaign_id}",
                        "processed",
                        str(processed)
                    )

                    # Транслируем прогресс в WebSocket-дашборд не на каждый
                    # звонок (это могут быть сотни тысяч контактов), а раз в
                    # 5 обработанных
                    if processed % 5 == 0:
                        await self._publish_campaign_event(campaign_id)

                # Завершаем кампанию
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE campaigns
                        SET status = $1, completed_at = NOW(), updated_at = NOW()
                        WHERE id = $2
                    """, CampaignStatus.COMPLETED.value, campaign_id)
                    await conn.execute("""
                        UPDATE campaign_runs
                        SET status = 'completed', completed_at = NOW(), processed_contacts = $1
                        WHERE id = $2
                    """, processed, run_id)

                campaign_completed_counter.inc()
                logger.info(f"Кампания {campaign_id} завершена, обработано {processed} контактов")
                await self._publish_campaign_event(campaign_id)

            except asyncio.CancelledError:
                logger.info(f"Кампания {campaign_id} отменена")
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE campaigns
                        SET status = $1, stopped_at = NOW(), updated_at = NOW()
                        WHERE id = $2
                    """, CampaignStatus.STOPPED.value, campaign_id)
                    await conn.execute("""
                        UPDATE campaign_runs
                        SET status = 'stopped', completed_at = NOW(), processed_contacts = $1
                        WHERE id = $2
                    """, processed, run_id)
                await self._publish_campaign_event(campaign_id)
                raise
            except Exception as e:
                logger.error(f"Ошибка в кампании {campaign_id}: {e}")
                campaign_failed_counter.inc()
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE campaigns
                        SET status = $1, updated_at = NOW()
                        WHERE id = $2
                    """, CampaignStatus.FAILED.value, campaign_id)
                    await conn.execute("""
                        UPDATE campaign_runs
                        SET status = 'failed', completed_at = NOW(), processed_contacts = $1
                        WHERE id = $2
                    """, processed, run_id)
                await self._publish_campaign_event(campaign_id)
                raise
            finally:
                self._active_campaigns.pop(campaign_id, None)
        
        # Регистрируем задачу. TaskRegistry.register()'s real signature is
        # (coro, name="unnamed", task_id=None, ...) - the old call here,
        # register(task_id, task), passed the task_id STRING positionally
        # as `coro` and the already-created asyncio.Task as `name`. Since
        # `task_id` (the registry's own param) then defaulted to None, it
        # tried `name.replace(' ', '_')` to auto-generate one - `name` was
        # the Task object, not a string, so this always raised
        # AttributeError, turning every campaign start into a 500 -
        # confirmed live even though the campaign itself started fine,
        # because register() crashed on this line strictly AFTER the real
        # dial_task() coroutine had already been created via
        # asyncio.create_task() and started running independently.
        # register() creates the task itself when given a bare coroutine
        # (asyncio.iscoroutine()/`__await__` branch) and takes task_id as
        # an explicit keyword - passing dial_task() directly (not already
        # wrapped in create_task()) lets it do that in one step, and keeps
        # `task_id=f"campaign_{campaign_id}"` resolvable later by
        # stop_campaign()'s task_registry.cancel(task_id).
        await self.task_registry.register(
            dial_task(),
            name=f"Campaign {campaign_id}",
            task_id=task_id
        )
        
        campaign_started_counter.inc()
        logger.info(f"Кампания {campaign_id} запущена, контактов: {len(contacts)}")
        
        return {
            "status": "started",
            "campaign_id": campaign_id,
            "total_contacts": len(contacts),
            "task_id": task_id
        }
    
    async def stop_campaign(
        self,
        campaign_id: int,
        user_id: int,
        reason: Optional[str] = None
    ) -> bool:
        """Остановить кампанию"""
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow(
                "SELECT status FROM campaigns WHERE id = $1",
                campaign_id
            )
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")
            
            if campaign['status'] != CampaignStatus.RUNNING.value:
                raise CampaignNotRunningError("Кампания не запущена")
            
            # Обновляем статус
            await conn.execute("""
                UPDATE campaigns 
                SET status = $1, stopped_at = NOW(), updated_at = NOW()
                WHERE id = $2
            """, CampaignStatus.STOPPED.value, campaign_id)
            
            await self._log_audit(conn, user_id, 'campaign_stopped', 'campaign', campaign_id, {
                'reason': reason
            })
        
        # Отменяем задачу
        task_id = f"campaign_{campaign_id}"
        await self.task_registry.cancel(task_id)
        
        logger.info(f"Кампания {campaign_id} остановлена")
        return True
    
    async def pause_campaign(self, campaign_id: int, user_id: int) -> bool:
        """Приостановить кампанию"""
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow(
                "SELECT status FROM campaigns WHERE id = $1",
                campaign_id
            )
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")
            
            if campaign['status'] != CampaignStatus.RUNNING.value:
                raise CampaignNotRunningError("Кампания не запущена")
            
            await conn.execute("""
                UPDATE campaigns 
                SET status = $1, paused_at = NOW(), updated_at = NOW()
                WHERE id = $2
            """, CampaignStatus.PAUSED.value, campaign_id)
            
            await self._log_audit(conn, user_id, 'campaign_paused', 'campaign', campaign_id)
        
        # Приостанавливаем задачу (сохраняем состояние)
        task_id = f"campaign_{campaign_id}"
        await self.task_registry.cancel(task_id)
        
        logger.info(f"Кампания {campaign_id} приостановлена")
        return True
    
    async def resume_campaign(self, campaign_id: int, user_id: int) -> Dict[str, Any]:
        """Возобновить кампанию"""
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow("""
                SELECT * FROM campaigns WHERE id = $1
            """, campaign_id)
            
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")
            
            if campaign['status'] != CampaignStatus.PAUSED.value:
                raise CampaignError("Кампания не приостановлена")
        
        # Запускаем заново
        return await self.start_campaign(campaign_id, user_id, force=True)
    
    # =============================================
    # Управление контактами кампании
    # =============================================
    async def add_contacts_to_campaign(
        self,
        campaign_id: int,
        contact_ids: Optional[List[int]] = None,
        group_ids: Optional[List[int]] = None,
        filter_params: Optional[Dict[str, Any]] = None
    ) -> int:
        """Добавить контакты в кампанию"""
        async with self.db_pool.acquire() as conn:
            # Проверяем статус кампании
            campaign = await conn.fetchrow(
                "SELECT status FROM campaigns WHERE id = $1",
                campaign_id
            )
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")
            
            if campaign['status'] == CampaignStatus.RUNNING.value:
                raise CampaignError("Нельзя добавлять контакты в запущенную кампанию")
            
            return await self._add_contacts_to_campaign(
                conn, campaign_id, group_ids, contact_ids, filter_params
            )
    
    async def remove_contacts_from_campaign(
        self,
        campaign_id: int,
        contact_ids: List[int]
    ) -> int:
        """Удалить контакты из кампании"""
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow(
                "SELECT status FROM campaigns WHERE id = $1",
                campaign_id
            )
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")
            
            if campaign['status'] == CampaignStatus.RUNNING.value:
                raise CampaignError("Нельзя удалять контакты из запущенной кампании")
            
            result = await conn.execute("""
                DELETE FROM campaign_contacts
                WHERE campaign_id = $1 AND contact_id = ANY($2)
            """, campaign_id, contact_ids)
            
            # Парсим количество удалённых
            import re
            match = re.search(r'DELETE (\d+)', result)
            removed = int(match.group(1)) if match else 0
            
            return removed
    
    # =============================================
    # Статистика и прогресс
    # =============================================
    async def get_campaign_stats(self, campaign_id: int) -> Optional[CampaignStatsResponse]:
        """Получить статистику кампании"""
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow(
                "SELECT id FROM campaigns WHERE id = $1",
                campaign_id
            )
            if not campaign:
                return None
            
            return await self._get_campaign_stats(conn, campaign_id)
    
    async def get_campaign_progress(self, campaign_id: int) -> Optional[CampaignProgressResponse]:
        """Получить прогресс кампании"""
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow("""
                SELECT id, name, status FROM campaigns WHERE id = $1
            """, campaign_id)
            
            if not campaign:
                return None
            
            # Получаем статистику
            stats = await self._get_campaign_stats(conn, campaign_id)
            
            # Получаем прогресс из Redis (если кампания активна)
            progress_data = await self.redis.hgetall(f"campaign_progress:{campaign_id}")
            
            active_calls = 0
            current_cps = 0.0
            
            if campaign_id in self._active_campaigns:
                ctx = self._active_campaigns[campaign_id]
                active_calls = len([c for c in self.dialer_manager.channel_map.values() 
                                   if f"campaign_{campaign_id}" in c]) if self.dialer_manager else 0
                current_cps = ctx.current_cps
            
            # Оценка времени завершения
            estimated_completion = None
            if stats.remaining_contacts > 0 and current_cps > 0:
                seconds_remaining = stats.remaining_contacts / current_cps
                estimated_completion = datetime.utcnow() + timedelta(seconds=seconds_remaining)
            
            return CampaignProgressResponse(
                campaign_id=campaign_id,
                campaign_name=campaign['name'],
                status=CampaignStatus(campaign['status']),
                total_contacts=stats.total_contacts,
                called_contacts=stats.processed_contacts,
                agreed=stats.agreed,
                declined=stats.declined,
                progress_percent=stats.progress_percent,
                active_calls=active_calls,
                current_cps=current_cps,
                estimated_completion=estimated_completion,
                timestamp=datetime.utcnow()
            )
    
    async def _publish_campaign_event(self, campaign_id: int) -> None:
        """
        Опубликовать CampaignProgressEvent (см. app.models.system) в Redis Pub/Sub
        для WebSocketService (best-effort — отсутствие подписчиков или сбой
        Redis не должны прерывать обзвон кампании).
        """
        try:
            progress = await self.get_campaign_progress(campaign_id)
            if progress:
                await self.redis.publish(f"{REDIS_KEYS.WS_CHANNELS}:campaign", {
                    "type": "campaign",
                    "data": progress.model_dump(mode="json"),
                })
        except Exception as e:
            logger.debug(f"Не удалось опубликовать campaign-событие в WebSocket: {e}")

    async def get_active_campaigns(self) -> List[CampaignProgressResponse]:
        """Получить все активные кампании"""
        result = []
        for campaign_id in list(self._active_campaigns.keys()):
            progress = await self.get_campaign_progress(campaign_id)
            if progress:
                result.append(progress)
        return result
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    async def _validate_campaign_create(self, request: CampaignCreateRequest) -> None:
        """Валидация создания кампании"""
        if request.max_contacts and request.max_contacts < 1:
            raise CampaignValidationError("max_contacts должен быть больше 0")
        
        if request.max_duration_hours and request.max_duration_hours < 0.1:
            raise CampaignValidationError("max_duration_hours должен быть не менее 0.1")
    
    async def _add_contacts_to_campaign(
        self,
        conn,
        campaign_id: int,
        group_ids: Optional[List[int]],
        contact_ids: Optional[List[int]],
        filter_params: Optional[Dict[str, Any]]
    ) -> int:
        """Внутренний метод добавления контактов"""
        added = 0
        
        # Добавляем из групп
        if group_ids:
            result = await conn.execute("""
                INSERT INTO campaign_contacts (campaign_id, contact_id, status)
                SELECT $1, c.id, 'pending'
                FROM contacts c
                JOIN contact_group_members cgm ON c.id = cgm.contact_id
                WHERE cgm.group_id = ANY($2)
                AND NOT c.blacklisted
                AND NOT EXISTS (
                    SELECT 1 FROM campaign_contacts cc
                    WHERE cc.campaign_id = $1 AND cc.contact_id = c.id
                )
            """, campaign_id, group_ids)
            match = re.search(r'INSERT \d+ (\d+)', result)
            added += int(match.group(1)) if match else 0
        
        # Добавляем конкретные контакты
        if contact_ids:
            await conn.execute("""
                INSERT INTO campaign_contacts (campaign_id, contact_id, status)
                SELECT $1, c.id, 'pending'
                FROM contacts c
                WHERE c.id = ANY($2)
                AND NOT c.blacklisted
                AND NOT EXISTS (
                    SELECT 1 FROM campaign_contacts cc
                    WHERE cc.campaign_id = $1 AND cc.contact_id = c.id
                )
            """, campaign_id, contact_ids)
            added += len(contact_ids)
        
        return added
    
    async def assign_contacts(
        self,
        campaign_id: int,
        group_ids: List[int],
        contact_ids: List[int],
        replace: bool,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Назначить контакты существующей кампании - POST
        /campaigns/{id}/assign-contacts. Раньше маршрута не существовало
        вообще (см. комментарий у CampaignAssignContactsRequest), из-за
        чего ни "Назначить контакты" в деталях кампании, ни смена группы
        обзвона при редактировании никогда не работали (404 на каждый
        вызов).

        replace=False (кнопка "Назначить контакты") - добавляет контакты
        к уже существующим в кампании, дубликаты по contact_id молча
        пропускаются (тот же _add_contacts_to_campaign, что и при
        создании).
        replace=True (смена группы в форме редактирования) - полностью
        стирает текущий campaign_contacts кампании и заполняет заново
        выбранными группами/контактами. call_results и campaign_runs
        хранятся отдельно по contact_id/campaign_id и от этого не
        страдают - вся история звонков остаётся на месте, меняется только
        то, кого кампания будет обзванивать дальше.
        """
        async with self.db_pool.acquire() as conn:
            campaign = await conn.fetchrow(
                "SELECT status FROM campaigns WHERE id = $1 FOR UPDATE", campaign_id
            )
            if not campaign:
                raise CampaignNotFoundError(f"Кампания {campaign_id} не найдена")

            if campaign['status'] == CampaignStatus.RUNNING.value:
                raise CampaignError(
                    "Нельзя менять контакты у запущенного обзвона - сначала остановите его"
                )

            if replace:
                await conn.execute(
                    "DELETE FROM campaign_contacts WHERE campaign_id = $1", campaign_id
                )

            added = await self._add_contacts_to_campaign(
                conn, campaign_id, group_ids, contact_ids, None
            )
            total = await self._get_campaign_contacts_count(conn, campaign_id)

            await self._log_audit(conn, user_id, 'campaign_contacts_assigned', 'campaign', campaign_id, {
                'group_ids': group_ids,
                'contact_ids': contact_ids,
                'replace': replace,
                'added': added,
                'total': total
            })

        return {'added': added, 'total': total}

    async def _get_campaign_contacts_count(self, conn, campaign_id: int) -> int:
        """Получить количество контактов в кампании"""
        return await conn.fetchval("""
            SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id = $1
        """, campaign_id)
    
    async def _get_campaign_stats(self, conn, campaign_id: int) -> CampaignStatsResponse:
        """Получить статистику кампании"""
        row = await conn.fetchrow("""
            SELECT 
                COUNT(DISTINCT cc.contact_id) as total_contacts,
                COUNT(DISTINCT CASE WHEN cr.id IS NOT NULL THEN cc.contact_id END) as processed_contacts,
                COUNT(DISTINCT CASE WHEN cr.id IS NULL THEN cc.contact_id END) as remaining_contacts,
                COUNT(cr.id) as total_calls,
                COUNT(CASE WHEN cr.status = 'agreed' THEN 1 END) as agreed,
                COUNT(CASE WHEN cr.status = 'declined' THEN 1 END) as declined,
                COUNT(CASE WHEN cr.status = 'busy' THEN 1 END) as busy,
                COUNT(CASE WHEN cr.status = 'noanswer' THEN 1 END) as noanswer,
                COUNT(CASE WHEN cr.status = 'failed' THEN 1 END) as failed,
                COUNT(CASE WHEN cr.status = 'timeout' THEN 1 END) as timeout,
                COUNT(CASE WHEN cr.status = 'machine' THEN 1 END) as machine,
                COUNT(CASE WHEN cr.status = 'canceled' THEN 1 END) as canceled,
                AVG(cr.duration) as avg_duration,
                COALESCE(SUM(cr.duration), 0) as total_duration,
                AVG(cr.wait_time) as avg_wait_time
            FROM campaign_contacts cc
            LEFT JOIN call_results cr ON cc.campaign_id = cr.campaign_id 
                AND cc.contact_id = cr.contact_id
            WHERE cc.campaign_id = $1
        """, campaign_id)
        
        if not row:
            return CampaignStatsResponse()
        
        total = row['total_contacts'] or 0
        processed = row['processed_contacts'] or 0
        agreed = row['agreed'] or 0
        total_calls = row['total_calls'] or 0
        
        return CampaignStatsResponse(
            total_contacts=total,
            processed_contacts=processed,
            remaining_contacts=row['remaining_contacts'] or 0,
            skipped_contacts=0,
            total_calls=total_calls,
            answered_calls=agreed + (row['declined'] or 0),
            agreed=agreed,
            declined=row['declined'] or 0,
            busy=row['busy'] or 0,
            noanswer=row['noanswer'] or 0,
            failed=row['failed'] or 0,
            timeout=row['timeout'] or 0,
            machine=row['machine'] or 0,
            cancelled=row['canceled'] or 0,
            conversion_rate=round(agreed / total_calls * 100, 2) if total_calls > 0 else 0.0,
            answer_rate=round((agreed + (row['declined'] or 0)) / total_calls * 100, 2) if total_calls > 0 else 0.0,
            avg_duration=round(row['avg_duration'] or 0, 2),
            total_duration=row['total_duration'] or 0,
            avg_wait_time=round(row['avg_wait_time'] or 0, 2),
            progress_percent=round(processed / total * 100, 2) if total > 0 else 0.0,
            estimated_completion=None,
            current_cps=0.0,
            avg_cps=0.0,
            peak_cps=0.0
        )
    
    # =============================================
    # История запусков (вкладка "История обзвонов")
    # =============================================
    async def list_campaign_runs(
        self,
        page: int = 1,
        page_size: int = 20,
        campaign_id: Optional[int] = None,
        status: Optional[str] = None,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """Список запусков обзвонов - одна строка на каждый прогон, а не на кампанию"""
        offset = (page - 1) * page_size

        async with self.db_pool.acquire() as conn:
            where = []
            params = []
            idx = 1

            if campaign_id:
                where.append(f"cr.campaign_id = ${idx}")
                params.append(campaign_id)
                idx += 1

            if status:
                where.append(f"cr.status = ${idx}")
                params.append(status)
                idx += 1

            if search:
                where.append(f"c.name ILIKE ${idx}")
                params.append(f"%{search}%")
                idx += 1

            where_clause = "WHERE " + " AND ".join(where) if where else ""

            total = await conn.fetchval(f"""
                SELECT COUNT(*) FROM campaign_runs cr
                JOIN campaigns c ON c.id = cr.campaign_id
                {where_clause}
            """, *params)

            rows = await conn.fetch(f"""
                SELECT cr.*, c.name as campaign_name
                FROM campaign_runs cr
                JOIN campaigns c ON c.id = cr.campaign_id
                {where_clause}
                ORDER BY cr.started_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}
            """, *params, page_size, offset)

        items = []
        for row in rows:
            total_contacts = row['total_contacts'] or 0
            processed = row['processed_contacts'] or 0
            items.append({
                'id': row['id'],
                'campaign_id': row['campaign_id'],
                'campaign_name': row['campaign_name'],
                'status': row['status'],
                'started_at': row['started_at'],
                'completed_at': row['completed_at'],
                'total_contacts': total_contacts,
                'processed_contacts': processed,
                'progress_percent': round(processed / total_contacts * 100, 2) if total_contacts else 0.0
            })

        total = total or 0
        return {
            'items': items,
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': max(1, (total + page_size - 1) // page_size)
        }

    async def get_campaign_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Детали одного запуска - статистика + звонки, попавшие именно в его временное окно"""
        async with self.db_pool.acquire() as conn:
            # a.duration - длительность аудио, которое реально проигрывается
            # звонящим, нужна фронту, чтобы можно было сравнить с
            # call_results.duration и понять, дослушал ли абонент сообщение
            # целиком или бросил трубку на середине (например, файл 40с, а
            # звонок длился всего 10с). COALESCE(cr.audio_id, c.audio_id) -
            # cr.audio_id снимается на момент КОНКРЕТНОГО запуска (см.
            # start_campaign()), так что смена аудио кампании между
            # запусками больше не искажает старые запуски; запуски,
            # сделанные ДО добавления этой колонки, имеют cr.audio_id=NULL и
            # по-прежнему падают на текущее аудио кампании как раньше.
            row = await conn.fetchrow("""
                SELECT cr.*, c.name as campaign_name, a.duration as audio_duration
                FROM campaign_runs cr
                JOIN campaigns c ON c.id = cr.campaign_id
                LEFT JOIN audio_files a ON a.id = COALESCE(cr.audio_id, c.audio_id)
                WHERE cr.id = $1
            """, run_id)

            if not row:
                return None

            # call_results не хранит run_id (звонки этой кампании вообще
            # никак не различают, в рамках какого запуска они сделаны) -
            # используем временное окно самого запуска как единственный
            # доступный способ отличить "этот прогон" от предыдущих/
            # последующих без более крупной миграции.
            #
            # Верхнюю границу окна НЕЛЬЗЯ брать из completed_at: dial_task()
            # помечает запуск завершённым сразу после того, как ВСЕ контакты
            # поставлены в очередь (Redis dial_queue) - это происходит почти
            # мгновенно, а сам звонок идёт асинхронно через AMI и получает
            # свой call_results только когда реально завершится, зачастую
            # уже ПОСЛЕ этого момента. Подтверждено живьём: started_at ==
            # completed_at до секунды, "Обзвонено: 1/1", но список звонков
            # пуст - реальная запись в call_results появилась позже конца
            # этого узкого окна. Вместо completed_at берём начало
            # СЛЕДУЮЩЕГО запуска этой же кампании (если он уже есть) или
            # "сейчас" (если это последний/текущий запуск) - тогда окно
            # покрывает вообще всё время между этим запуском и следующим.
            next_run_started_at = await conn.fetchval("""
                SELECT started_at FROM campaign_runs
                WHERE campaign_id = $1 AND started_at > $2
                ORDER BY started_at ASC
                LIMIT 1
            """, row['campaign_id'], row['started_at'])
            window_end = next_run_started_at or datetime.utcnow()

            calls = await conn.fetch("""
                SELECT res.*, ct.phone, ct.name as contact_name
                FROM call_results res
                LEFT JOIN contacts ct ON res.contact_id = ct.id
                WHERE res.campaign_id = $1
                AND res.created_at >= $2
                AND res.created_at < $3
                ORDER BY res.created_at DESC
                LIMIT 200
            """, row['campaign_id'], row['started_at'], window_end)

        total_contacts = row['total_contacts'] or 0
        processed = row['processed_contacts'] or 0

        return {
            'id': row['id'],
            'campaign_id': row['campaign_id'],
            'campaign_name': row['campaign_name'],
            'status': row['status'],
            'started_at': row['started_at'],
            'completed_at': row['completed_at'],
            'total_contacts': total_contacts,
            'processed_contacts': processed,
            'progress_percent': round(processed / total_contacts * 100, 2) if total_contacts else 0.0,
            'audio_duration': round(row['audio_duration']) if row['audio_duration'] is not None else None,
            'calls': [dict(c) for c in calls]
        }

    async def _get_campaign_contact_groups(self, conn, campaign_id: int) -> List[Dict[str, Any]]:
        """Получить группы контактов кампании"""
        rows = await conn.fetch("""
            SELECT DISTINCT cg.id, cg.name, cg.color
            FROM contact_groups cg
            JOIN contact_group_members cgm ON cg.id = cgm.group_id
            JOIN campaign_contacts cc ON cgm.contact_id = cc.contact_id
            WHERE cc.campaign_id = $1
        """, campaign_id)
        return [dict(row) for row in rows]
    
    async def _get_campaign_recent_calls(self, conn, campaign_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получить последние звонки кампании"""
        rows = await conn.fetch("""
            SELECT cr.*, c.phone, c.name as contact_name
            FROM call_results cr
            LEFT JOIN contacts c ON cr.contact_id = c.id
            WHERE cr.campaign_id = $1
            ORDER BY cr.created_at DESC
            LIMIT $2
        """, campaign_id, limit)
        return [dict(row) for row in rows]
    
    async def _get_campaign_tags(self, conn, campaign_id: int) -> List[str]:
        """Получить теги кампании"""
        rows = await conn.fetch("""
            SELECT tag FROM campaign_tags WHERE campaign_id = $1
        """, campaign_id)
        return [row['tag'] for row in rows]
    
    async def _add_campaign_tags(self, conn, campaign_id: int, tags: List[str]) -> None:
        """Добавить теги кампании"""
        for tag in tags:
            await conn.execute("""
                INSERT INTO campaign_tags (campaign_id, tag)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, campaign_id, tag)
    
    async def _update_campaign_tags(self, conn, campaign_id: int, tags: List[str]) -> None:
        """Обновить теги кампании"""
        await conn.execute("DELETE FROM campaign_tags WHERE campaign_id = $1", campaign_id)
        await self._add_campaign_tags(conn, campaign_id, tags)
    
    def _check_schedule(self, schedule: Dict[str, Any]) -> bool:
        """Проверить, можно ли запустить кампанию по расписанию"""
        now = datetime.utcnow()
        
        start_at = schedule.get('start_at')
        end_at = schedule.get('end_at')
        
        if start_at:
            start = datetime.fromisoformat(start_at) if isinstance(start_at, str) else start_at
            if now < start:
                return False
        
        if end_at:
            end = datetime.fromisoformat(end_at) if isinstance(end_at, str) else end_at
            if now > end:
                return False
        
        # Проверка дней недели
        days_of_week = schedule.get('days_of_week')
        if days_of_week:
            weekday = now.weekday()
            if weekday not in days_of_week:
                return False
        
        # Проверка часов
        hours = schedule.get('hours')
        if hours:
            hour = now.hour
            if hour not in hours:
                return False
        
        return True
    
    async def _log_audit(
        self,
        conn,
        user_id: int,
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
                "active_campaigns": len(self._active_campaigns),
                "dialer_available": self.dialer_manager is not None
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def shutdown(self) -> None:
        """Корректное завершение"""
        # Останавливаем все активные кампании
        for campaign_id in list(self._active_campaigns.keys()):
            try:
                task_id = f"campaign_{campaign_id}"
                await self.task_registry.cancel(task_id)
            except Exception as e:
                logger.error(f"Ошибка при остановке кампании {campaign_id}: {e}")
        
        self._active_campaigns.clear()
        logger.info("CampaignService остановлен")


# =============================================
# Глобальный экземпляр
# =============================================
_campaign_service: Optional[CampaignService] = None


def get_campaign_service() -> CampaignService:
    """Получить глобальный экземпляр CampaignService"""
    global _campaign_service
    if _campaign_service is None:
        raise RuntimeError("CampaignService не инициализирован")
    return _campaign_service


def set_campaign_service(service: CampaignService) -> None:
    """Установить глобальный экземпляр CampaignService"""
    global _campaign_service
    _campaign_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "CampaignService",
    "CampaignError",
    "CampaignNotFoundError",
    "CampaignAlreadyRunningError",
    "CampaignNotRunningError",
    "CampaignNoContactsError",
    "CampaignValidationError",
    "get_campaign_service",
    "set_campaign_service",
]
