# app/api/contact_groups.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление группами контактов (отдельный роутер)
"""

from fastapi import APIRouter

# Реэкспорт для обратной совместимости
from app.api.contacts import (
    list_contact_groups,
    create_contact_group,
    get_contact_group,
    update_contact_group,
    delete_contact_group,
    get_contact_group_tree
)

router = APIRouter()

# Все эндпоинты уже определены в contacts.py
# Здесь просто реэкспортируем их
router.get("/")(list_contact_groups)
router.post("/")(create_contact_group)
router.get("/tree")(get_contact_group_tree)
router.get("/{group_id}")(get_contact_group)
router.patch("/{group_id}")(update_contact_group)
router.delete("/{group_id}")(delete_contact_group)
