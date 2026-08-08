#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Нормализация и форматирование номеров телефонов (российский план нумерации)
AutoDialer Ultimate v3.0.0

Единственный источник истины для правил российской нумерации — раньше
`normalize_phone`/`validate_phone_number`/`format_phone_display` были
продублированы (с небольшими расхождениями) в app/models/contact.py,
app/models/blacklist.py, app/models/incoming.py и app/services/dialer.py.
Любое уточнение правил (код оператора, длина номера и т.п.) теперь нужно
вносить только здесь.

Правила:
- Ведущая "8" (внутрироссийский формат) заменяется на код страны "7".
- Голый 10-значный мобильный номер, начинающийся с "9", дополняется
  кодом страны "7" (9991234567 -> 79991234567).
- 11-значный номер, уже начинающийся с "7", не трогается.
- Второй код после "7" не может быть "0" или "1" — таких кодов
  оператора/региона в России не существует.
"""

import re
from typing import Optional


def normalize_phone(phone: Optional[str]) -> str:
    """
    Нормализация номера телефона к цифровой строке международного формата.
    Возвращает "" для пустого/отсутствующего номера.
    """
    if not phone:
        return ""

    digits = re.sub(r'[^\d]', '', phone)

    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    elif len(digits) == 11 and digits.startswith('7'):
        pass
    elif len(digits) == 10 and digits.startswith('9'):
        digits = '7' + digits

    return digits


def validate_phone_number(phone: str) -> bool:
    """
    Проверка корректности номера телефона (после normalize_phone
    или сырой строки — нормализует самостоятельно).
    """
    digits = normalize_phone(phone)

    if len(digits) < 10:
        return False

    # Проверка российских номеров
    if digits.startswith('7'):
        if len(digits) != 11:
            return False
        # Кодов оператора/региона, начинающихся с 0 или 1, не существует
        if digits[1] in ('0', '1'):
            return False

    # Международные номера (до 15 цифр)
    if len(digits) > 15:
        return False

    return True


def format_phone_display(phone: str) -> str:
    """
    Форматирование номера для отображения: +7 (900) 123-45-67.
    """
    digits = normalize_phone(phone)

    if len(digits) == 11 and digits.startswith('7'):
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"

    if len(digits) == 10:
        return f"+7 ({digits[0:3]}) {digits[3:6]}-{digits[6:8]}-{digits[8:10]}"

    # Для прочих форматов просто добавляем "+"
    return f"+{digits}" if digits else ""


__all__ = [
    "normalize_phone",
    "validate_phone_number",
    "format_phone_display",
]
