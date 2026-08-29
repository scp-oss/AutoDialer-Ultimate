# app/api/contacts.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление контактами
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.core.dependencies import get_current_user, TokenData, PaginationParams
from app.services import get_contact_service, get_contact_group_service
from app.models.contact import (
    ContactCreateRequest, ContactUpdateRequest, ContactBulkImportRequest,
    ContactResponse, ContactDetailResponse, ContactListResponse,
    ContactBulkImportResponse, ContactFilterRequest,
    ContactGroupCreateRequest, ContactGroupUpdateRequest,
    ContactGroupResponse, ContactGroupListResponse,
    ContactStatus
)

router = APIRouter()


# =============================================
# Контакты
# =============================================
@router.get("/", response_model=ContactListResponse)
async def list_contacts(
    pagination: PaginationParams = Depends(),
    search: Optional[str] = None,
    group_id: Optional[int] = None,
    status: Optional[List[ContactStatus]] = None,
    tags: Optional[List[str]] = None,
    user: TokenData = Depends(get_current_user)
):
    """Получить список контактов"""
    contact_service = get_contact_service()
    
    filter_params = ContactFilterRequest(
        search=search,
        group_ids=[group_id] if group_id else None,
        status=status,
        tags=tags
    )
    
    return await contact_service.list_contacts(
        page=pagination.page,
        page_size=pagination.page_size,
        filter_params=filter_params
    )


@router.post("/", response_model=ContactResponse)
async def create_contact(
    request: ContactCreateRequest,
    user: TokenData = Depends(get_current_user)
):
    """Создать новый контакт"""
    contact_service = get_contact_service()
    return await contact_service.create_contact(request, user.user_id)


@router.post("/import", response_model=ContactBulkImportResponse)
async def import_contacts(
    request: ContactBulkImportRequest,
    user: TokenData = Depends(get_current_user)
):
    """Массовый импорт контактов"""
    contact_service = get_contact_service()
    return await contact_service.bulk_import_contacts(request, user.user_id)


@router.get("/export")
async def export_contacts(
    format: str = "csv",
    user: TokenData = Depends(get_current_user)
):
    """Экспорт контактов"""
    from fastapi.responses import StreamingResponse
    import io

    contact_service = get_contact_service()
    content = await contact_service.export_contacts(format=format)

    media_type = "text/csv" if format == "csv" else "application/json"
    filename = f"contacts_export.{format}"

    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/duplicates")
async def get_duplicate_contacts(user: TokenData = Depends(get_current_user)):
    """Найти дубликаты контактов по номеру телефона"""
    contact_service = get_contact_service()
    return await contact_service.find_duplicates()


@router.post("/merge")
async def merge_duplicate_contacts(
    phone: str,
    user: TokenData = Depends(get_current_user)
):
    """Объединить дубликаты контактов с одинаковым номером"""
    contact_service = get_contact_service()
    removed = await contact_service.merge_duplicates(phone, user.user_id)
    return {"status": "merged", "removed": removed}


# NOTE: /{contact_id} must be registered after every literal sibling path
# above (/import, /export, /duplicates, /merge) - FastAPI/Starlette match
# routes in registration order, and since this path segment has no type
# converter in the route string (only in the Python annotation), a literal
# path like "/export" matches "/{contact_id}" first if that's registered
# first; the int conversion then fails and returns 422 instead of ever
# reaching the real handler. (Confirmed live: /contacts/export and
# /contacts/duplicates both 422'd before this reorder.)
@router.get("/{contact_id}", response_model=ContactDetailResponse)
async def get_contact(
    contact_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить контакт по ID"""
    contact_service = get_contact_service()
    contact = await contact_service.get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    return contact


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int,
    request: ContactUpdateRequest,
    user: TokenData = Depends(get_current_user)
):
    """Обновить контакт"""
    contact_service = get_contact_service()
    return await contact_service.update_contact(contact_id, request, user.user_id)


@router.delete("/{contact_id}")
async def delete_contact(
    contact_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Удалить контакт"""
    contact_service = get_contact_service()
    await contact_service.delete_contact(contact_id, user.user_id)
    return {"status": "deleted"}


@router.post("/{contact_id}/blacklist")
async def blacklist_contact(
    contact_id: int,
    reason: str = None,
    user: TokenData = Depends(get_current_user)
):
    """Добавить контакт в чёрный список"""
    contact_service = get_contact_service()
    await contact_service.blacklist_contact(contact_id, reason or "Manual", user.user_id)
    return {"status": "blacklisted"}


@router.post("/{contact_id}/unblacklist")
async def unblacklist_contact(
    contact_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Убрать контакт из чёрного списка"""
    contact_service = get_contact_service()
    await contact_service.unblacklist_contact(contact_id, user.user_id)
    return {"status": "unblacklisted"}


@router.post("/{contact_id}/restore", response_model=ContactResponse)
async def restore_contact(
    contact_id: int,
    user: TokenData = Depends(get_current_user)
):
    """
    Восстановить удалённый контакт (снять deleted_at).

    ContactService.restore_contact() существовал давно, но не был подключён
    ни к одному API-роуту - удалённый контакт нельзя было вернуть иначе как
    прямым запросом в БД, даже с учётом того, что его номер теперь снова
    можно занять новым контактом (idx_contacts_phone_active, см. schema.sql).
    """
    contact_service = get_contact_service()
    return await contact_service.restore_contact(contact_id, user.user_id)


# =============================================
# Группы контактов
# =============================================
@router.get("/groups", response_model=ContactGroupListResponse)
async def list_contact_groups(
    parent_id: Optional[int] = None,
    user: TokenData = Depends(get_current_user)
):
    """Получить список групп контактов"""
    group_service = get_contact_group_service()
    return await group_service.list_groups(parent_id=parent_id)


@router.post("/groups", response_model=ContactGroupResponse)
async def create_contact_group(
    request: ContactGroupCreateRequest,
    user: TokenData = Depends(get_current_user)
):
    """Создать группу контактов"""
    group_service = get_contact_group_service()
    return await group_service.create_group(request, user.user_id)


@router.get("/groups/tree")
async def get_contact_group_tree(user: TokenData = Depends(get_current_user)):
    """Получить дерево групп контактов"""
    group_service = get_contact_group_service()
    return await group_service.get_group_tree()


# NOTE: /groups/tree must be registered before /groups/{group_id} for the
# same reason as /{contact_id} above - both are 2-segment paths for the
# same method, and "tree" would otherwise get parsed as group_id:int and
# 422 before ever reaching this handler. (Confirmed live.)
@router.get("/groups/{group_id}", response_model=ContactGroupResponse)
async def get_contact_group(
    group_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Получить группу по ID"""
    group_service = get_contact_group_service()
    group = await group_service.get_group(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    return group


@router.get("/groups/{group_id}/contacts", response_model=ContactListResponse)
async def get_contact_group_members(
    group_id: int,
    pagination: PaginationParams = Depends(),
    user: TokenData = Depends(get_current_user)
):
    """Получить контакты, входящие в группу"""
    group_service = get_contact_group_service()
    group = await group_service.get_group(group_id)
    if not group:
        raise HTTPException(404, "Group not found")

    contact_service = get_contact_service()
    filter_params = ContactFilterRequest(group_ids=[group_id])
    return await contact_service.list_contacts(
        page=pagination.page,
        page_size=pagination.page_size,
        filter_params=filter_params
    )


@router.patch("/groups/{group_id}", response_model=ContactGroupResponse)
async def update_contact_group(
    group_id: int,
    request: ContactGroupUpdateRequest,
    user: TokenData = Depends(get_current_user)
):
    """Обновить группу контактов"""
    group_service = get_contact_group_service()
    return await group_service.update_group(group_id, request, user.user_id)


@router.delete("/groups/{group_id}")
async def delete_contact_group(
    group_id: int,
    user: TokenData = Depends(get_current_user)
):
    """Удалить группу контактов"""
    group_service = get_contact_group_service()
    await group_service.delete_group(group_id, user.user_id)
    return {"status": "deleted"}
