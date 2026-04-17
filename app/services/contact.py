#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сервис управления контактами и группами контактов
AutoDialer Ultimate v3.0.0

Предоставляет бизнес-логику для:
- CRUD операций с контактами
- Массового импорта/экспорта контактов
- Управления группами контактов
- Валидации и нормализации номеров
- Дедупликации контактов
"""

import re
import json
import csv
import io
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Set
from dataclasses import dataclass

from app.core.logger import logger
from app.core.database import ConnectionPool
from app.core.redis import RedisClient, REDIS_KEYS
from app.models.contact import (
    ContactStatus, ContactSource, ContactGender,
    ContactCreateRequest, ContactUpdateRequest, ContactBulkImportRequest,
    ContactResponse, ContactDetailResponse, ContactListResponse,
    ContactBulkImportResponse,
    ContactGroupCreateRequest, ContactGroupUpdateRequest,
    ContactGroupResponse, ContactGroupListResponse,
    ContactFilterRequest,
    normalize_phone, validate_phone_number, format_phone_display
)
from prometheus_client import Counter


# =============================================
# Метрики
# =============================================
contact_created_counter = Counter(
    'autodialer_contacts_created_total',
    'Total contacts created'
)
contact_updated_counter = Counter(
    'autodialer_contacts_updated_total',
    'Total contacts updated'
)
contact_deleted_counter = Counter(
    'autodialer_contacts_deleted_total',
    'Total contacts deleted'
)
contact_imported_counter = Counter(
    'autodialer_contacts_imported_total',
    'Total contacts imported'
)


# =============================================
# Исключения
# =============================================
class ContactError(Exception):
    """Базовое исключение сервиса контактов"""
    pass


class ContactNotFoundError(ContactError):
    """Контакт не найден"""
    pass


class ContactDuplicateError(ContactError):
    """Дубликат контакта"""
    pass


class ContactValidationError(ContactError):
    """Ошибка валидации контакта"""
    pass


class ContactGroupNotFoundError(ContactError):
    """Группа контактов не найдена"""
    pass


class ContactImportError(ContactError):
    """Ошибка импорта контактов"""
    pass


# =============================================
# Сервис контактов
# =============================================
class ContactService:
    """
    Сервис управления контактами.
    
    Отвечает за:
    - CRUD операции с контактами
    - Массовый импорт/экспорт
    - Валидацию и нормализацию номеров
    - Поиск и фильтрацию
    """
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        
        logger.info("ContactService инициализирован")
    
    # =============================================
    # CRUD операции
    # =============================================
    async def create_contact(
        self,
        request: ContactCreateRequest,
        user_id: Optional[int] = None
    ) -> ContactResponse:
        """
        Создать новый контакт.
        
        Args:
            request: Данные контакта
            user_id: ID пользователя-создателя
        
        Returns:
            Созданный контакт
        """
        # Нормализуем телефон
        phone = normalize_phone(request.phone)
        if not validate_phone_number(phone):
            raise ContactValidationError(f"Неверный формат номера: {request.phone}")
        
        async with self.db_pool.acquire() as conn:
            # Проверяем существование
            existing = await conn.fetchrow(
                "SELECT id, phone FROM contacts WHERE phone = $1",
                phone
            )
            if existing:
                raise ContactDuplicateError(f"Контакт с номером {phone} уже существует (ID: {existing['id']})")
            
            # Проверяем чёрный список
            if await self.redis.is_blacklisted(phone):
                raise ContactValidationError(f"Номер {phone} находится в чёрном списке")
            
            # Нормализуем дополнительные телефоны
            phone2 = normalize_phone(request.phone2) if request.phone2 else None
            phone3 = normalize_phone(request.phone3) if request.phone3 else None
            
            # Вставляем контакт
            contact_id = await conn.fetchval("""
                INSERT INTO contacts (
                    phone, name, email,
                    phone2, phone3,
                    gender, birth_date, company, position,
                    country, region, city, address, postal_code,
                    source, status, custom_fields, notes,
                    created_by, created_at, updated_at
                ) VALUES (
                    $1, $2, $3,
                    $4, $5,
                    $6, $7, $8, $9,
                    $10, $11, $12, $13, $14,
                    $15, $16, $17, $18,
                    $19, NOW(), NOW()
                )
                RETURNING id
            """,
                phone,
                request.name,
                request.email,
                phone2,
                phone3,
                request.gender.value if request.gender else None,
                request.birth_date,
                request.company,
                request.position,
                request.country,
                request.region,
                request.city,
                request.address,
                request.postal_code,
                request.source.value if request.source else ContactSource.MANUAL.value,
                ContactStatus.ACTIVE.value,
                json.dumps(request.custom_fields) if request.custom_fields else None,
                request.notes,
                user_id
            )
            
            # Добавляем в группы
            group_ids = request.group_ids or []
            if request.group_id:
                group_ids.append(request.group_id)
            
            if group_ids:
                await self._add_contact_to_groups(conn, contact_id, group_ids)
            
            # Добавляем теги
            if request.tags:
                await self._add_contact_tags(conn, contact_id, request.tags)
            
            # Кешируем в Redis
            await self._cache_contact(contact_id, phone)
            
            # Получаем полные данные
            contact = await self._get_contact_by_id(conn, contact_id)
        
        contact_created_counter.inc()
        logger.info(f"Контакт создан: {phone} (ID: {contact_id})")
        
        return contact
    
    async def get_contact(self, contact_id: int) -> Optional[ContactDetailResponse]:
        """Получить контакт по ID"""
        async with self.db_pool.acquire() as conn:
            contact = await self._get_contact_by_id(conn, contact_id)
            if not contact:
                return None
            
            # Получаем дополнительные данные
            groups = await self._get_contact_groups(conn, contact_id)
            recent_calls = await self._get_contact_recent_calls(conn, contact_id, 10)
            campaigns = await self._get_contact_campaigns(conn, contact_id)
            notes_history = await self._get_contact_notes_history(conn, contact_id)
            
            return ContactDetailResponse(
                **contact.model_dump(),
                recent_calls=recent_calls,
                campaigns=campaigns,
                notes_history=notes_history
            )
    
    async def get_contact_by_phone(self, phone: str) -> Optional[ContactResponse]:
        """Получить контакт по номеру телефона"""
        normalized = normalize_phone(phone)
        
        # Проверяем кеш
        cached = await self.redis.get(f"contact:phone:{normalized}")
        if cached:
            contact_id = int(cached)
            return await self.get_contact(contact_id)
        
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM contacts WHERE phone = $1",
                normalized
            )
            if not row:
                return None
            
            return await self._get_contact_by_id(conn, row['id'])
    
    async def update_contact(
        self,
        contact_id: int,
        request: ContactUpdateRequest,
        user_id: Optional[int] = None
    ) -> ContactResponse:
        """Обновить контакт"""
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id, phone FROM contacts WHERE id = $1",
                contact_id
            )
            if not existing:
                raise ContactNotFoundError(f"Контакт {contact_id} не найден")
            
            updates = []
            params = []
            param_idx = 1
            
            if request.name is not None:
                updates.append(f"name = ${param_idx}")
                params.append(request.name)
                param_idx += 1
            
            if request.email is not None:
                updates.append(f"email = ${param_idx}")
                params.append(request.email)
                param_idx += 1
            
            if request.phone2 is not None:
                updates.append(f"phone2 = ${param_idx}")
                params.append(normalize_phone(request.phone2) if request.phone2 else None)
                param_idx += 1
            
            if request.phone3 is not None:
                updates.append(f"phone3 = ${param_idx}")
                params.append(normalize_phone(request.phone3) if request.phone3 else None)
                param_idx += 1
            
            if request.gender is not None:
                updates.append(f"gender = ${param_idx}")
                params.append(request.gender.value)
                param_idx += 1
            
            if request.birth_date is not None:
                updates.append(f"birth_date = ${param_idx}")
                params.append(request.birth_date)
                param_idx += 1
            
            if request.company is not None:
                updates.append(f"company = ${param_idx}")
                params.append(request.company)
                param_idx += 1
            
            if request.position is not None:
                updates.append(f"position = ${param_idx}")
                params.append(request.position)
                param_idx += 1
            
            if request.country is not None:
                updates.append(f"country = ${param_idx}")
                params.append(request.country)
                param_idx += 1
            
            if request.region is not None:
                updates.append(f"region = ${param_idx}")
                params.append(request.region)
                param_idx += 1
            
            if request.city is not None:
                updates.append(f"city = ${param_idx}")
                params.append(request.city)
                param_idx += 1
            
            if request.address is not None:
                updates.append(f"address = ${param_idx}")
                params.append(request.address)
                param_idx += 1
            
            if request.postal_code is not None:
                updates.append(f"postal_code = ${param_idx}")
                params.append(request.postal_code)
                param_idx += 1
            
            if request.custom_fields is not None:
                updates.append(f"custom_fields = ${param_idx}")
                params.append(json.dumps(request.custom_fields))
                param_idx += 1
            
            if request.notes is not None:
                updates.append(f"notes = ${param_idx}")
                params.append(request.notes)
                param_idx += 1
            
            if request.status is not None:
                updates.append(f"status = ${param_idx}")
                params.append(request.status.value)
                param_idx += 1
            
            if updates:
                updates.append(f"updated_at = NOW()")
                params.append(contact_id)
                query = f"""
                    UPDATE contacts 
                    SET {', '.join(updates)}
                    WHERE id = ${param_idx}
                """
                await conn.execute(query, *params)
            
            # Обновляем группы
            if request.group_id is not None:
                await self._update_contact_groups(conn, contact_id, [request.group_id])
            
            # Обновляем теги
            if request.tags is not None:
                await self._update_contact_tags(conn, contact_id, request.tags)
            
            # Инвалидируем кеш
            await self.redis.delete(f"contact:{contact_id}")
            await self.redis.delete(f"contact:phone:{existing['phone']}")
            
            # Получаем обновлённый контакт
            contact = await self._get_contact_by_id(conn, contact_id)
        
        contact_updated_counter.inc()
        logger.info(f"Контакт {contact_id} обновлён")
        
        return contact
    
    async def delete_contact(self, contact_id: int, user_id: Optional[int] = None) -> bool:
        """Удалить контакт (мягкое удаление)"""
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id, phone FROM contacts WHERE id = $1 AND deleted_at IS NULL",
                contact_id
            )
            if not existing:
                raise ContactNotFoundError(f"Контакт {contact_id} не найден")
            
            # Мягкое удаление
            await conn.execute("""
                UPDATE contacts 
                SET deleted_at = NOW(), status = $1, updated_at = NOW()
                WHERE id = $2
            """, ContactStatus.INACTIVE.value, contact_id)
            
            # Удаляем из групп
            await conn.execute(
                "DELETE FROM contact_group_members WHERE contact_id = $1",
                contact_id
            )
            
            # Удаляем теги
            await conn.execute(
                "DELETE FROM contact_tags WHERE contact_id = $1",
                contact_id
            )
            
            # Инвалидируем кеш
            await self.redis.delete(f"contact:{contact_id}")
            await self.redis.delete(f"contact:phone:{existing['phone']}")
            
            await self._log_audit(conn, user_id, 'contact_deleted', 'contact', contact_id)
        
        contact_deleted_counter.inc()
        logger.info(f"Контакт {contact_id} удалён")
        
        return True
    
    async def delete_contact_permanent(self, contact_id: int, user_id: Optional[int] = None) -> bool:
        """Полностью удалить контакт (администратор)"""
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id, phone FROM contacts WHERE id = $1",
                contact_id
            )
            if not existing:
                raise ContactNotFoundError(f"Контакт {contact_id} не найден")
            
            # Проверяем, есть ли связанные звонки
            calls_count = await conn.fetchval(
                "SELECT COUNT(*) FROM call_results WHERE contact_id = $1",
                contact_id
            )
            if calls_count > 0:
                raise ContactError(f"Нельзя удалить контакт с историей звонков ({calls_count} звонков)")
            
            # Удаляем связи
            await conn.execute("DELETE FROM contact_group_members WHERE contact_id = $1", contact_id)
            await conn.execute("DELETE FROM contact_tags WHERE contact_id = $1", contact_id)
            await conn.execute("DELETE FROM campaign_contacts WHERE contact_id = $1", contact_id)
            
            # Удаляем контакт
            await conn.execute("DELETE FROM contacts WHERE id = $1", contact_id)
            
            # Инвалидируем кеш
            await self.redis.delete(f"contact:{contact_id}")
            await self.redis.delete(f"contact:phone:{existing['phone']}")
            
            await self._log_audit(conn, user_id, 'contact_permanently_deleted', 'contact', contact_id)
        
        logger.info(f"Контакт {contact_id} удалён навсегда")
        return True
    
    async def restore_contact(self, contact_id: int, user_id: Optional[int] = None) -> ContactResponse:
        """Восстановить удалённый контакт"""
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM contacts WHERE id = $1 AND deleted_at IS NOT NULL",
                contact_id
            )
            if not existing:
                raise ContactNotFoundError(f"Удалённый контакт {contact_id} не найден")
            
            await conn.execute("""
                UPDATE contacts 
                SET deleted_at = NULL, status = $1, updated_at = NOW()
                WHERE id = $2
            """, ContactStatus.ACTIVE.value, contact_id)
            
            contact = await self._get_contact_by_id(conn, contact_id)
            
            await self._log_audit(conn, user_id, 'contact_restored', 'contact', contact_id)
        
        logger.info(f"Контакт {contact_id} восстановлен")
        return contact
    
    async def list_contacts(
        self,
        page: int = 1,
        page_size: int = 20,
        filter_params: Optional[ContactFilterRequest] = None,
        include_deleted: bool = False
    ) -> ContactListResponse:
        """Получить список контактов с фильтрацией"""
        offset = (page - 1) * page_size
        
        async with self.db_pool.acquire() as conn:
            where_conditions = []
            params = []
            param_idx = 1
            
            if not include_deleted:
                where_conditions.append("c.deleted_at IS NULL")
            
            if filter_params:
                if filter_params.search:
                    where_conditions.append(f"""
                        (c.phone LIKE ${param_idx} 
                         OR c.name ILIKE ${param_idx}
                         OR c.email ILIKE ${param_idx}
                         OR c.company ILIKE ${param_idx})
                    """)
                    params.append(f"%{filter_params.search}%")
                    param_idx += 1
                
                if filter_params.group_ids:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.group_ids))])
                    where_conditions.append(f"""
                        c.id IN (
                            SELECT contact_id FROM contact_group_members 
                            WHERE group_id IN ({placeholders})
                        )
                    """)
                    params.extend(filter_params.group_ids)
                    param_idx += len(filter_params.group_ids)
                
                if filter_params.status:
                    placeholders = ','.join([f"${param_idx + i}" for i in range(len(filter_params.status))])
                    where_conditions.append(f"c.status IN ({placeholders})")
                    params.extend([s.value for s in filter_params.status])
                    param_idx += len(filter_params.status)
                
                if filter_params.tags:
                    where_conditions.append(f"""
                        c.id IN (
                            SELECT contact_id FROM contact_tags 
                            WHERE tag = ANY(${param_idx})
                        )
                    """)
                    params.append(filter_params.tags)
                    param_idx += 1
                
                if filter_params.has_calls is not None:
                    if filter_params.has_calls:
                        where_conditions.append("c.total_calls > 0")
                    else:
                        where_conditions.append("c.total_calls = 0")
                
                if filter_params.created_after:
                    where_conditions.append(f"c.created_at >= ${param_idx}")
                    params.append(filter_params.created_after)
                    param_idx += 1
                
                if filter_params.created_before:
                    where_conditions.append(f"c.created_at <= ${param_idx}")
                    params.append(filter_params.created_before)
                    param_idx += 1
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            # Общее количество
            count_query = f"SELECT COUNT(*) FROM contacts c {where_clause}"
            total = await conn.fetchval(count_query, *params)
            
            # Сортировка
            sort_by = filter_params.sort_by if filter_params else "id"
            sort_order = filter_params.sort_order if filter_params else "DESC"
            
            # Получаем данные
            query = f"""
                SELECT 
                    c.*,
                    cg.id as group_id,
                    cg.name as group_name
                FROM contacts c
                LEFT JOIN contact_group_members cgm ON c.id = cgm.contact_id
                LEFT JOIN contact_groups cg ON cgm.group_id = cg.id
                {where_clause}
                ORDER BY c.{sort_by} {sort_order}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([page_size, offset])
            
            rows = await conn.fetch(query, *params)
            
            # Группируем контакты (из-за LEFT JOIN могут быть дубли)
            contacts_map: Dict[int, ContactResponse] = {}
            contact_groups_map: Dict[int, List[Dict]] = {}
            
            for row in rows:
                contact_id = row['id']
                if contact_id not in contacts_map:
                    tags = await self._get_contact_tags(conn, contact_id)
                    custom_fields = json.loads(row['custom_fields']) if row['custom_fields'] else {}
                    
                    contacts_map[contact_id] = ContactResponse(
                        id=contact_id,
                        phone=row['phone'],
                        phone_display=format_phone_display(row['phone']),
                        name=row['name'],
                        email=row['email'],
                        phone2=row['phone2'],
                        phone3=row['phone3'],
                        gender=row['gender'],
                        birth_date=row['birth_date'],
                        company=row['company'],
                        position=row['position'],
                        country=row['country'],
                        region=row['region'],
                        city=row['city'],
                        address=row['address'],
                        postal_code=row['postal_code'],
                        group_id=row['group_id'],
                        group_name=row['group_name'],
                        group_ids=[],
                        tags=tags,
                        custom_fields=custom_fields,
                        notes=row['notes'],
                        status=ContactStatus(row['status']),
                        blacklisted=row['blacklisted'],
                        blacklist_reason=row['blacklist_reason'],
                        source=ContactSource(row['source']) if row['source'] else ContactSource.MANUAL,
                        last_call_at=row['last_call_at'],
                        last_call_status=row['last_call_status'],
                        total_calls=row['total_calls'] or 0,
                        successful_calls=row['successful_calls'] or 0,
                        dnd=row['dnd'],
                        dnd_until=row['dnd_until'],
                        view_count=row['view_count'] or 0,
                        created_at=row['created_at'],
                        updated_at=row['updated_at']
                    )
                    contact_groups_map[contact_id] = []
                
                if row['group_id']:
                    contact_groups_map[contact_id].append({
                        'id': row['group_id'],
                        'name': row['group_name']
                    })
            
            # Заполняем group_ids
            items = []
            for contact_id, contact in contacts_map.items():
                contact.group_ids = [g['id'] for g in contact_groups_map[contact_id]]
                items.append(contact)
            
            return ContactListResponse(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=(total + page_size - 1) // page_size
            )
    
    # =============================================
    # Массовый импорт
    # =============================================
    async def bulk_import_contacts(
        self,
        request: ContactBulkImportRequest,
        user_id: Optional[int] = None
    ) -> ContactBulkImportResponse:
        """Массовый импорт контактов"""
        result = ContactBulkImportResponse(
            total=len(request.contacts),
            imported=0,
            updated=0,
            skipped=0,
            duplicates=0,
            blacklisted=0,
            invalid=0,
            errors=[]
        )
        
        async with self.db_pool.acquire() as conn:
            for idx, contact_data in enumerate(request.contacts):
                try:
                    # Получаем телефон
                    phone_field = request.field_mapping.get('phone', 'phone')
                    phone = contact_data.get(phone_field, '').strip()
                    
                    if not phone:
                        result.skipped += 1
                        result.errors.append({'row': idx + 1, 'error': 'Отсутствует номер телефона'})
                        continue
                    
                    # Нормализуем
                    normalized = normalize_phone(phone)
                    if not validate_phone_number(normalized):
                        if request.skip_invalid:
                            result.invalid += 1
                            continue
                        else:
                            result.errors.append({'row': idx + 1, 'phone': phone, 'error': 'Неверный формат номера'})
                            continue
                    
                    # Проверяем чёрный список
                    if await self.redis.is_blacklisted(normalized):
                        if request.skip_blacklisted:
                            result.blacklisted += 1
                            continue
                    
                    # Проверяем существование
                    existing = await conn.fetchrow(
                        "SELECT id FROM contacts WHERE phone = $1",
                        normalized
                    )
                    
                    if existing:
                        if request.skip_duplicates:
                            result.duplicates += 1
                            continue
                        elif request.update_existing:
                            # Обновляем существующий
                            await self._update_contact_from_import(
                                conn, existing['id'], contact_data, request
                            )
                            result.updated += 1
                            continue
                    
                    # Создаём новый контакт
                    contact_id = await self._create_contact_from_import(
                        conn, normalized, contact_data, request
                    )
                    
                    # Добавляем в группы
                    if request.group_id:
                        await self._add_contact_to_groups(conn, contact_id, [request.group_id])
                    
                    # Добавляем теги
                    if request.tags:
                        await self._add_contact_tags(conn, contact_id, request.tags)
                    
                    result.imported += 1
                    
                except Exception as e:
                    logger.error(f"Ошибка импорта контакта (строка {idx + 1}): {e}")
                    result.errors.append({'row': idx + 1, 'error': str(e)})
                    result.skipped += 1
        
        contact_imported_counter.inc(result.imported)
        logger.info(f"Импорт контактов завершён: {result.imported} импортировано, {result.updated} обновлено")
        
        return result
    
    async def export_contacts(
        self,
        filter_params: Optional[ContactFilterRequest] = None,
        format: str = "csv",
        fields: Optional[List[str]] = None
    ) -> bytes:
        """Экспорт контактов"""
        # Получаем все контакты (без пагинации)
        response = await self.list_contacts(page=1, page_size=100000, filter_params=filter_params)
        
        if format == "csv":
            return await self._export_to_csv(response.items, fields)
        elif format == "json":
            return await self._export_to_json(response.items, fields)
        else:
            raise ContactError(f"Неподдерживаемый формат экспорта: {format}")
    
    # =============================================
    # Чёрный список
    # =============================================
    async def blacklist_contact(
        self,
        contact_id: int,
        reason: str,
        user_id: Optional[int] = None
    ) -> bool:
        """Добавить контакт в чёрный список"""
        async with self.db_pool.acquire() as conn:
            contact = await conn.fetchrow(
                "SELECT id, phone FROM contacts WHERE id = $1",
                contact_id
            )
            if not contact:
                raise ContactNotFoundError(f"Контакт {contact_id} не найден")
            
            await conn.execute("""
                UPDATE contacts 
                SET blacklisted = TRUE, blacklist_reason = $1, updated_at = NOW()
                WHERE id = $2
            """, reason, contact_id)
            
            # Добавляем в Redis
            await self.redis.add_to_blacklist(contact['phone'])
            
            await self._log_audit(conn, user_id, 'contact_blacklisted', 'contact', contact_id, {
                'reason': reason
            })
        
        logger.info(f"Контакт {contact_id} добавлен в чёрный список")
        return True
    
    async def unblacklist_contact(
        self,
        contact_id: int,
        user_id: Optional[int] = None
    ) -> bool:
        """Убрать контакт из чёрного списка"""
        async with self.db_pool.acquire() as conn:
            contact = await conn.fetchrow(
                "SELECT id, phone FROM contacts WHERE id = $1",
                contact_id
            )
            if not contact:
                raise ContactNotFoundError(f"Контакт {contact_id} не найден")
            
            await conn.execute("""
                UPDATE contacts 
                SET blacklisted = FALSE, blacklist_reason = NULL, updated_at = NOW()
                WHERE id = $1
            """, contact_id)
            
            # Удаляем из Redis
            await self.redis.remove_from_blacklist(contact['phone'])
            
            await self._log_audit(conn, user_id, 'contact_unblacklisted', 'contact', contact_id)
        
        logger.info(f"Контакт {contact_id} убран из чёрного списка")
        return True
    
    # =============================================
    # Вспомогательные методы
    # =============================================
    async def _get_contact_by_id(self, conn, contact_id: int) -> Optional[ContactResponse]:
        """Получить контакт по ID (внутренний метод)"""
        row = await conn.fetchrow("""
            SELECT 
                c.*,
                cg.id as group_id,
                cg.name as group_name
            FROM contacts c
            LEFT JOIN contact_group_members cgm ON c.id = cgm.contact_id AND cgm.is_primary = TRUE
            LEFT JOIN contact_groups cg ON cgm.group_id = cg.id
            WHERE c.id = $1 AND c.deleted_at IS NULL
        """, contact_id)
        
        if not row:
            return None
        
        tags = await self._get_contact_tags(conn, contact_id)
        groups = await self._get_contact_groups(conn, contact_id)
        custom_fields = json.loads(row['custom_fields']) if row['custom_fields'] else {}
        
        return ContactResponse(
            id=row['id'],
            phone=row['phone'],
            phone_display=format_phone_display(row['phone']),
            name=row['name'],
            email=row['email'],
            phone2=row['phone2'],
            phone3=row['phone3'],
            gender=row['gender'],
            birth_date=row['birth_date'],
            company=row['company'],
            position=row['position'],
            country=row['country'],
            region=row['region'],
            city=row['city'],
            address=row['address'],
            postal_code=row['postal_code'],
            group_id=row['group_id'],
            group_name=row['group_name'],
            group_ids=[g['id'] for g in groups],
            tags=tags,
            custom_fields=custom_fields,
            notes=row['notes'],
            status=ContactStatus(row['status']),
            blacklisted=row['blacklisted'],
            blacklist_reason=row['blacklist_reason'],
            source=ContactSource(row['source']) if row['source'] else ContactSource.MANUAL,
            last_call_at=row['last_call_at'],
            last_call_status=row['last_call_status'],
            total_calls=row['total_calls'] or 0,
            successful_calls=row['successful_calls'] or 0,
            dnd=row['dnd'],
            dnd_until=row['dnd_until'],
            view_count=row['view_count'] or 0,
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
    
    async def _get_contact_tags(self, conn, contact_id: int) -> List[str]:
        rows = await conn.fetch(
            "SELECT tag FROM contact_tags WHERE contact_id = $1",
            contact_id
        )
        return [row['tag'] for row in rows]
    
    async def _get_contact_groups(self, conn, contact_id: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT cg.id, cg.name, cg.color, cgm.is_primary
            FROM contact_groups cg
            JOIN contact_group_members cgm ON cg.id = cgm.group_id
            WHERE cgm.contact_id = $1
            ORDER BY cgm.is_primary DESC, cg.name
        """, contact_id)
        return [dict(row) for row in rows]
    
    async def _get_contact_recent_calls(self, conn, contact_id: int, limit: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT cr.*, c.name as campaign_name
            FROM call_results cr
            LEFT JOIN campaigns c ON cr.campaign_id = c.id
            WHERE cr.contact_id = $1
            ORDER BY cr.created_at DESC
            LIMIT $2
        """, contact_id, limit)
        return [dict(row) for row in rows]
    
    async def _get_contact_campaigns(self, conn, contact_id: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT DISTINCT c.id, c.name, c.status, cc.created_at
            FROM campaigns c
            JOIN campaign_contacts cc ON c.id = cc.campaign_id
            WHERE cc.contact_id = $1
            ORDER BY cc.created_at DESC
        """, contact_id)
        return [dict(row) for row in rows]
    
    async def _get_contact_notes_history(self, conn, contact_id: int) -> List[Dict[str, Any]]:
        rows = await conn.fetch("""
            SELECT * FROM contact_notes_history
            WHERE contact_id = $1
            ORDER BY created_at DESC
        """, contact_id)
        return [dict(row) for row in rows]
    
    async def _add_contact_to_groups(self, conn, contact_id: int, group_ids: List[int]) -> None:
        for group_id in group_ids:
            await conn.execute("""
                INSERT INTO contact_group_members (contact_id, group_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, contact_id, group_id)
    
    async def _update_contact_groups(self, conn, contact_id: int, group_ids: List[int]) -> None:
        await conn.execute("DELETE FROM contact_group_members WHERE contact_id = $1", contact_id)
        await self._add_contact_to_groups(conn, contact_id, group_ids)
    
    async def _add_contact_tags(self, conn, contact_id: int, tags: List[str]) -> None:
        for tag in tags:
            await conn.execute("""
                INSERT INTO contact_tags (contact_id, tag)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, contact_id, tag)
    
    async def _update_contact_tags(self, conn, contact_id: int, tags: List[str]) -> None:
        await conn.execute("DELETE FROM contact_tags WHERE contact_id = $1", contact_id)
        await self._add_contact_tags(conn, contact_id, tags)
    
    async def _cache_contact(self, contact_id: int, phone: str) -> None:
        """Кешировать контакт в Redis"""
        await self.redis.setex(f"contact:phone:{phone}", 3600, str(contact_id))
    
    async def _create_contact_from_import(
        self,
        conn,
        phone: str,
        data: Dict[str, str],
        request: ContactBulkImportRequest
    ) -> int:
        """Создать контакт из данных импорта"""
        name_field = request.field_mapping.get('name', 'name')
        email_field = request.field_mapping.get('email', 'email')
        company_field = request.field_mapping.get('company', 'company')
        
        return await conn.fetchval("""
            INSERT INTO contacts (
                phone, name, email, company,
                source, status, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, NOW(), NOW()
            )
            RETURNING id
        """,
            phone,
            data.get(name_field, '').strip() or None,
            data.get(email_field, '').strip() or None,
            data.get(company_field, '').strip() or None,
            request.source.value,
            ContactStatus.ACTIVE.value
        )
    
    async def _update_contact_from_import(
        self,
        conn,
        contact_id: int,
        data: Dict[str, str],
        request: ContactBulkImportRequest
    ) -> None:
        """Обновить контакт из данных импорта"""
        updates = []
        params = []
        param_idx = 1
        
        name_field = request.field_mapping.get('name', 'name')
        if name_field in data:
            updates.append(f"name = ${param_idx}")
            params.append(data[name_field].strip() or None)
            param_idx += 1
        
        email_field = request.field_mapping.get('email', 'email')
        if email_field in data:
            updates.append(f"email = ${param_idx}")
            params.append(data[email_field].strip() or None)
            param_idx += 1
        
        company_field = request.field_mapping.get('company', 'company')
        if company_field in data:
            updates.append(f"company = ${param_idx}")
            params.append(data[company_field].strip() or None)
            param_idx += 1
        
        if updates:
            updates.append(f"updated_at = NOW()")
            params.append(contact_id)
            query = f"""
                UPDATE contacts 
                SET {', '.join(updates)}
                WHERE id = ${param_idx}
            """
            await conn.execute(query, *params)
    
    async def _export_to_csv(self, contacts: List[ContactResponse], fields: Optional[List[str]]) -> bytes:
        """Экспорт в CSV"""
        if not fields:
            fields = ['id', 'phone', 'name', 'email', 'company', 'position', 'status', 'created_at']
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        
        for contact in contacts:
            row = {}
            for field in fields:
                if hasattr(contact, field):
                    value = getattr(contact, field)
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    elif isinstance(value, (list, dict)):
                        value = json.dumps(value, ensure_ascii=False)
                    row[field] = value or ''
            writer.writerow(row)
        
        return output.getvalue().encode('utf-8-sig')
    
    async def _export_to_json(self, contacts: List[ContactResponse], fields: Optional[List[str]]) -> bytes:
        """Экспорт в JSON"""
        data = []
        for contact in contacts:
            contact_dict = contact.model_dump()
            if fields:
                contact_dict = {k: v for k, v in contact_dict.items() if k in fields}
            data.append(contact_dict)
        
        return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    
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
        logger.info("ContactService остановлен")


# =============================================
# Сервис групп контактов
# =============================================
class ContactGroupService:
    """Сервис управления группами контактов"""
    
    def __init__(self, db_pool: ConnectionPool, redis_client: RedisClient):
        self.db_pool = db_pool
        self.redis = redis_client
        
        logger.info("ContactGroupService инициализирован")
    
    async def create_group(
        self,
        request: ContactGroupCreateRequest,
        user_id: Optional[int] = None
    ) -> ContactGroupResponse:
        """Создать группу контактов"""
        async with self.db_pool.acquire() as conn:
            group_id = await conn.fetchval("""
                INSERT INTO contact_groups (name, description, color, parent_id, is_public, created_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """,
                request.name,
                request.description,
                request.color,
                request.parent_id,
                request.is_public,
                user_id
            )
            
            group = await self._get_group_by_id(conn, group_id)
        
        logger.info(f"Группа контактов создана: {request.name} (ID: {group_id})")
        return group
    
    async def get_group(self, group_id: int) -> Optional[ContactGroupResponse]:
        """Получить группу по ID"""
        async with self.db_pool.acquire() as conn:
            return await self._get_group_by_id(conn, group_id)
    
    async def update_group(
        self,
        group_id: int,
        request: ContactGroupUpdateRequest,
        user_id: Optional[int] = None
    ) -> ContactGroupResponse:
        """Обновить группу"""
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM contact_groups WHERE id = $1",
                group_id
            )
            if not existing:
                raise ContactGroupNotFoundError(f"Группа {group_id} не найдена")
            
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
            
            if request.color is not None:
                updates.append(f"color = ${param_idx}")
                params.append(request.color)
                param_idx += 1
            
            if request.parent_id is not None:
                updates.append(f"parent_id = ${param_idx}")
                params.append(request.parent_id)
                param_idx += 1
            
            if request.is_public is not None:
                updates.append(f"is_public = ${param_idx}")
                params.append(request.is_public)
                param_idx += 1
            
            if updates:
                updates.append(f"updated_at = NOW()")
                params.append(group_id)
                query = f"""
                    UPDATE contact_groups 
                    SET {', '.join(updates)}
                    WHERE id = ${param_idx}
                """
                await conn.execute(query, *params)
            
            group = await self._get_group_by_id(conn, group_id)
        
        logger.info(f"Группа {group_id} обновлена")
        return group
    
    async def delete_group(self, group_id: int, user_id: Optional[int] = None) -> bool:
        """Удалить группу"""
        async with self.db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM contact_groups WHERE id = $1",
                group_id
            )
            if not existing:
                raise ContactGroupNotFoundError(f"Группа {group_id} не найдена")
            
            # Удаляем связи с контактами
            await conn.execute(
                "DELETE FROM contact_group_members WHERE group_id = $1",
                group_id
            )
            
            # Обновляем дочерние группы
            await conn.execute(
                "UPDATE contact_groups SET parent_id = NULL WHERE parent_id = $1",
                group_id
            )
            
            # Удаляем группу
            await conn.execute("DELETE FROM contact_groups WHERE id = $1", group_id)
        
        logger.info(f"Группа {group_id} удалена")
        return True
    
    async def list_groups(
        self,
        parent_id: Optional[int] = None,
        include_empty: bool = True
    ) -> ContactGroupListResponse:
        """Получить список групп"""
        async with self.db_pool.acquire() as conn:
            where_conditions = []
            params = []
            param_idx = 1
            
            if parent_id is not None:
                where_conditions.append(f"parent_id = ${param_idx}")
                params.append(parent_id)
                param_idx += 1
            else:
                where_conditions.append("parent_id IS NULL")
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            rows = await conn.fetch(f"""
                SELECT 
                    cg.*,
                    (SELECT COUNT(*) FROM contact_group_members WHERE group_id = cg.id) as contacts_count,
                    (SELECT COUNT(*) FROM contact_group_members cgm 
                     JOIN contacts c ON cgm.contact_id = c.id 
                     WHERE cgm.group_id = cg.id AND c.status = 'active') as active_contacts_count
                FROM contact_groups cg
                {where_clause}
                ORDER BY cg.name
            """, *params)
            
            items = []
            for row in rows:
                # Получаем дочерние группы
                children = await self._get_child_groups(conn, row['id'])
                
                items.append(ContactGroupResponse(
                    id=row['id'],
                    name=row['name'],
                    description=row['description'],
                    color=row['color'],
                    parent_id=row['parent_id'],
                    parent_name=None,
                    is_public=row['is_public'],
                    contacts_count=row['contacts_count'],
                    active_contacts_count=row['active_contacts_count'],
                    created_by=row['created_by'],
                    created_by_name=None,
                    children=children,
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                ))
            
            # Фильтруем пустые группы если нужно
            if not include_empty:
                items = [item for item in items if item.contacts_count > 0]
            
            return ContactGroupListResponse(
                items=items,
                total=len(items),
                tree=items if parent_id is None else None
            )
    
    async def get_group_tree(self) -> List[ContactGroupResponse]:
        """Получить дерево групп"""
        response = await self.list_groups(parent_id=None, include_empty=True)
        return response.tree or response.items
    
    async def add_contacts_to_group(self, group_id: int, contact_ids: List[int]) -> int:
        """Добавить контакты в группу"""
        async with self.db_pool.acquire() as conn:
            added = 0
            for contact_id in contact_ids:
                try:
                    await conn.execute("""
                        INSERT INTO contact_group_members (group_id, contact_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                    """, group_id, contact_id)
                    added += 1
                except Exception:
                    pass
            
            return added
    
    async def remove_contacts_from_group(self, group_id: int, contact_ids: List[int]) -> int:
        """Удалить контакты из группы"""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM contact_group_members
                WHERE group_id = $1 AND contact_id = ANY($2)
            """, group_id, contact_ids)
            
            import re
            match = re.search(r'DELETE (\d+)', result)
            return int(match.group(1)) if match else 0
    
    async def _get_group_by_id(self, conn, group_id: int) -> Optional[ContactGroupResponse]:
        """Получить группу по ID (внутренний метод)"""
        row = await conn.fetchrow("""
            SELECT 
                cg.*,
                parent.name as parent_name,
                u.username as created_by_name,
                (SELECT COUNT(*) FROM contact_group_members WHERE group_id = cg.id) as contacts_count,
                (SELECT COUNT(*) FROM contact_group_members cgm 
                 JOIN contacts c ON cgm.contact_id = c.id 
                 WHERE cgm.group_id = cg.id AND c.status = 'active') as active_contacts_count
            FROM contact_groups cg
            LEFT JOIN contact_groups parent ON cg.parent_id = parent.id
            LEFT JOIN users u ON cg.created_by = u.id
            WHERE cg.id = $1
        """, group_id)
        
        if not row:
            return None
        
        children = await self._get_child_groups(conn, group_id)
        
        return ContactGroupResponse(
            id=row['id'],
            name=row['name'],
            description=row['description'],
            color=row['color'],
            parent_id=row['parent_id'],
            parent_name=row['parent_name'],
            is_public=row['is_public'],
            contacts_count=row['contacts_count'],
            active_contacts_count=row['active_contacts_count'],
            created_by=row['created_by'],
            created_by_name=row['created_by_name'],
            children=children,
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
    
    async def _get_child_groups(self, conn, parent_id: int) -> List[ContactGroupResponse]:
        """Получить дочерние группы"""
        rows = await conn.fetch("""
            SELECT id FROM contact_groups WHERE parent_id = $1
        """, parent_id)
        
        children = []
        for row in rows:
            child = await self._get_group_by_id(conn, row['id'])
            if child:
                children.append(child)
        
        return children
    
    async def health_check(self) -> Dict[str, Any]:
        return {"status": "healthy"}
    
    async def shutdown(self) -> None:
        logger.info("ContactGroupService остановлен")


# =============================================
# Глобальные экземпляры
# =============================================
_contact_service: Optional[ContactService] = None
_contact_group_service: Optional[ContactGroupService] = None


def get_contact_service() -> ContactService:
    global _contact_service
    if _contact_service is None:
        raise RuntimeError("ContactService не инициализирован")
    return _contact_service


def get_contact_group_service() -> ContactGroupService:
    global _contact_group_service
    if _contact_group_service is None:
        raise RuntimeError("ContactGroupService не инициализирован")
    return _contact_group_service


def set_contact_service(service: ContactService) -> None:
    global _contact_service
    _contact_service = service


def set_contact_group_service(service: ContactGroupService) -> None:
    global _contact_group_service
    _contact_group_service = service


# =============================================
# Экспорт
# =============================================
__all__ = [
    "ContactService",
    "ContactGroupService",
    "ContactError",
    "ContactNotFoundError",
    "ContactDuplicateError",
    "ContactValidationError",
    "ContactGroupNotFoundError",
    "ContactImportError",
    "get_contact_service",
    "get_contact_group_service",
    "set_contact_service",
    "set_contact_group_service",
]
