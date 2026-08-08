#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль безопасности
AutoDialer Ultimate v3.0.0

Предоставляет:
- Хеширование и проверка паролей (bcrypt)
- JWT токены (создание, проверка, обновление)
- API ключи для внешнего доступа
- Генерация безопасных случайных строк
- Защита от timing attacks
- Валидация сложности паролей
- Блокировка после неудачных попыток
- Двухфакторная аутентификация (TOTP)

ИСПОЛЬЗОВАНИЕ:
    from app.core.security import (
        hash_password, verify_password,
        create_access_token, decode_token,
        generate_api_key, verify_api_key
    )
"""

import re
import uuid
import hmac
import hashlib
import secrets
import base64
from typing import Dict, Optional, Tuple, Any, List
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError, ExpiredSignatureError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import settings
from app.core.logger import logger


# =============================================
# Исключения безопасности
# =============================================
class SecurityError(Exception):
    """Базовое исключение безопасности"""
    pass


class PasswordValidationError(SecurityError):
    """Ошибка валидации пароля"""
    pass


class TokenError(SecurityError):
    """Ошибка токена"""
    pass


class TokenExpiredError(TokenError):
    """Токен истёк"""
    pass


class TokenInvalidError(TokenError):
    """Токен невалиден"""
    pass


class TokenRevokedError(TokenError):
    """Токен отозван"""
    pass


class ApiKeyError(SecurityError):
    """Ошибка API ключа"""
    pass


# =============================================
# Пароли (bcrypt)
# =============================================
def hash_password(password: str) -> str:
    """
    Хешировать пароль с использованием bcrypt.
    
    Args:
        password: Пароль в открытом виде
    
    Returns:
        Хеш пароля
    """
    if not password:
        raise PasswordValidationError("Пароль не может быть пустым")
    
    # Проверка сложности (опционально)
    if settings.ENVIRONMENT == "production":
        validate_password_strength(password)
    
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Проверить пароль.
    
    Args:
        plain_password: Пароль в открытом виде
        hashed_password: Хеш пароля
    
    Returns:
        True если пароль верный
    """
    if not plain_password or not hashed_password:
        return False
    
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def validate_password_strength(password: str) -> None:
    """
    Проверить сложность пароля.
    
    Args:
        password: Пароль для проверки
    
    Raises:
        PasswordValidationError: Если пароль не соответствует требованиям
    """
    errors = []
    
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"Минимальная длина пароля: {settings.PASSWORD_MIN_LENGTH} символов")
    
    if settings.PASSWORD_REQUIRE_UPPER and not re.search(r'[A-ZА-Я]', password):
        errors.append("Пароль должен содержать хотя бы одну заглавную букву")
    
    if settings.PASSWORD_REQUIRE_LOWER and not re.search(r'[a-zа-я]', password):
        errors.append("Пароль должен содержать хотя бы одну строчную букву")
    
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r'\d', password):
        errors.append("Пароль должен содержать хотя бы одну цифру")
    
    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("Пароль должен содержать хотя бы один специальный символ")
    
    # Проверка на распространённые пароли
    common_passwords = {
        'password', '123456', '12345678', 'qwerty', 'abc123',
        'password123', 'admin', 'administrator', 'root', 'autodialer'
    }
    if password.lower() in common_passwords:
        errors.append("Пароль слишком распространён")
    
    # Проверка на последовательности
    sequences = ['123456', 'abcdef', 'qwerty', 'йцукен', 'фывапр']
    for seq in sequences:
        if seq in password.lower():
            errors.append("Пароль содержит простую последовательность символов")
            break
    
    if errors:
        raise PasswordValidationError("; ".join(errors))


def check_password_strength(password: str) -> Dict[str, Any]:
    """
    Оценить сложность пароля.
    
    Returns:
        Словарь с оценкой и рекомендациями
    """
    score = 0
    feedback = []
    
    # Длина
    if len(password) >= 12:
        score += 3
    elif len(password) >= 10:
        score += 2
    elif len(password) >= 8:
        score += 1
    else:
        feedback.append("Увеличьте длину пароля")
    
    # Разнообразие символов
    if re.search(r'[A-ZА-Я]', password):
        score += 1
    else:
        feedback.append("Добавьте заглавные буквы")
    
    if re.search(r'[a-zа-я]', password):
        score += 1
    else:
        feedback.append("Добавьте строчные буквы")
    
    if re.search(r'\d', password):
        score += 1
    else:
        feedback.append("Добавьте цифры")
    
    if re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        score += 2
    else:
        feedback.append("Добавьте специальные символы")
    
    # Оценка
    if score >= 6:
        strength = "strong"
    elif score >= 4:
        strength = "medium"
    else:
        strength = "weak"
    
    return {
        "score": score,
        "strength": strength,
        "feedback": feedback,
        "is_valid": len(feedback) == 0 or strength != "weak"
    }


# =============================================
# JWT Токены
# =============================================
def create_token(
    data: Dict[str, Any],
    expires_delta: Optional[int] = None,
    token_type: str = "access"
) -> str:
    """
    Создать JWT токен.
    
    Args:
        data: Данные для включения в токен
        expires_delta: Время жизни в секундах
        token_type: Тип токена ('access' или 'refresh')
    
    Returns:
        JWT токен
    """
    to_encode = data.copy()
    
    # Время жизни
    if expires_delta:
        expire = datetime.now(timezone.utc) + timedelta(seconds=expires_delta)
    elif token_type == "access":
        expire = datetime.now(timezone.utc) + settings.access_token_expires
    else:
        expire = datetime.now(timezone.utc) + settings.refresh_token_expires
    
    # Добавляем стандартные поля
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
        "type": token_type,
        "iss": "autodialer",
        "aud": "autodialer-api",
    })
    
    # Создаём токен
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    
    return encoded_jwt


def create_access_token(data: Dict[str, Any], expires_delta: Optional[int] = None) -> str:
    """Создать access токен"""
    return create_token(data, expires_delta, "access")


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[int] = None) -> str:
    """Создать refresh токен"""
    return create_token(data, expires_delta, "refresh")


def decode_token(token: str, verify_exp: bool = True) -> Dict[str, Any]:
    """
    Декодировать и проверить JWT токен.
    
    Args:
        token: JWT токен
        verify_exp: Проверять срок действия
    
    Returns:
        Данные из токена
    
    Raises:
        TokenExpiredError: Токен истёк
        TokenInvalidError: Токен невалиден
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience="autodialer-api",
            issuer="autodialer",
            options={"verify_exp": verify_exp}
        )
        return payload
    except ExpiredSignatureError:
        raise TokenExpiredError("Токен истёк")
    except JWTError as e:
        raise TokenInvalidError(f"Невалидный токен: {e}")


def verify_token(token: str, token_type: Optional[str] = None) -> Tuple[bool, Optional[Dict], Optional[str]]:
    """
    Проверить токен и вернуть данные.
    
    Returns:
        (успех, данные, ошибка)
    """
    try:
        payload = decode_token(token)
        
        if token_type and payload.get("type") != token_type:
            return False, None, f"Неверный тип токена, ожидался {token_type}"
        
        return True, payload, None
    except TokenExpiredError:
        return False, None, "Токен истёк"
    except TokenInvalidError as e:
        return False, None, str(e)


def get_token_payload(token: str) -> Optional[Dict[str, Any]]:
    """
    Получить данные из токена без проверки подписи.
    (Только для отладки!)
    """
    try:
        # Разделяем токен на части
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        # Декодируем payload (вторая часть)
        payload = parts[1]
        # Добавляем padding если нужно
        payload += '=' * (4 - len(payload) % 4)
        
        decoded = base64.urlsafe_b64decode(payload)
        import json
        return json.loads(decoded)
    except Exception:
        return None


def get_token_ttl(token: str) -> Optional[int]:
    """
    Получить оставшееся время жизни токена в секундах.
    """
    try:
        payload = decode_token(token, verify_exp=False)
        exp = payload.get("exp")
        if exp:
            now = datetime.now(timezone.utc).timestamp()
            return max(0, int(exp - now))
        return None
    except Exception:
        return None


def is_token_expired(token: str) -> bool:
    """Проверить, истёк ли токен"""
    ttl = get_token_ttl(token)
    return ttl is not None and ttl == 0


# =============================================
# API Ключи
# =============================================
def generate_api_key(prefix: str = "ak") -> Tuple[str, str, str]:
    """
    Сгенерировать API ключ.
    
    Returns:
        (полный ключ, префикс+хвост для хранения, хеш для хранения)
    
    Формат ключа: ak_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    """
    # Генерируем случайную часть
    random_part = secrets.token_hex(32)  # 64 символа
    
    # Формируем полный ключ
    full_key = f"{prefix}_live_{random_part}"
    
    # Для хранения в БД (префикс + последние 8 символов)
    key_tail = random_part[-8:]
    stored_key = f"{prefix}_live_...{key_tail}"
    
    # Хеш для безопасного хранения
    key_hash = hash_api_key(full_key)
    
    return full_key, stored_key, key_hash


def hash_api_key(api_key: str) -> str:
    """
    Хешировать API ключ для хранения в БД.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(plain_key: str, stored_hash: str) -> bool:
    """
    Проверить API ключ.
    """
    if not plain_key or not stored_hash:
        return False
    
    computed_hash = hash_api_key(plain_key)
    return constant_time_compare(computed_hash, stored_hash)


def mask_api_key(api_key: str, visible_chars: int = 8) -> str:
    """
    Маскировать API ключ для отображения.
    
    Пример: ak_live_abcd...wxyz
    """
    if len(api_key) <= visible_chars * 2:
        return "*" * len(api_key)
    
    prefix = api_key.split('_')[0] if '_' in api_key else api_key[:4]
    suffix = api_key[-visible_chars:]
    
    return f"{prefix}_...{suffix}"


def parse_api_key(api_key: str) -> Optional[Dict[str, str]]:
    """
    Разобрать API ключ на компоненты.
    
    Returns:
        {"prefix": "ak", "type": "live", "hash": "..."}
    """
    parts = api_key.split('_')
    if len(parts) < 3:
        return None
    
    return {
        "prefix": parts[0],
        "type": parts[1],
        "secret": '_'.join(parts[2:])
    }


# =============================================
# Двухфакторная аутентификация (TOTP)
# =============================================
class TOTPManager:
    """
    Менеджер TOTP (Time-based One-Time Password).
    
    Совместим с Google Authenticator, Authy, etc.
    """
    
    def __init__(self, issuer: str = "AutoDialer"):
        self.issuer = issuer
    
    def generate_secret(self, length: int = 32) -> str:
        """
        Сгенерировать секретный ключ для TOTP.
        """
        import base64
        random_bytes = secrets.token_bytes(length)
        return base64.b32encode(random_bytes).decode('utf-8').rstrip('=')
    
    def get_totp_uri(self, secret: str, username: str) -> str:
        """
        Получить URI для QR-кода.
        """
        import urllib.parse
        label = urllib.parse.quote(f"{self.issuer}:{username}")
        return f"otpauth://totp/{label}?secret={secret}&issuer={self.issuer}"
    
    def verify_totp(self, secret: str, code: str, window: int = 1) -> bool:
        """
        Проверить TOTP код.
        
        Args:
            secret: Секретный ключ (base32)
            code: Код для проверки (6 цифр)
            window: Допустимое окно (1 = ±30 секунд)
        
        Returns:
            True если код верный
        """
        import hmac
        import hashlib
        import struct
        import time
        import base64
        
        if not code or not secret:
            return False
        
        try:
            code_int = int(code)
            if code_int < 0 or code_int > 999999:
                return False
        except ValueError:
            return False
        
        # Декодируем секрет из base32
        try:
            key = base64.b32decode(secret.upper() + '=' * ((8 - len(secret)) % 8))
        except Exception:
            return False
        
        # Текущее время (30-секундные интервалы)
        now = int(time.time()) // 30
        
        for offset in range(-window, window + 1):
            time_counter = now + offset
            
            # Преобразуем в bytes
            time_bytes = struct.pack('>Q', time_counter)
            
            # HMAC-SHA1
            hmac_hash = hmac.new(key, time_bytes, hashlib.sha1).digest()
            
            # Динамическое усечение
            offset_byte = hmac_hash[-1] & 0x0F
            truncated_hash = hmac_hash[offset_byte:offset_byte + 4]
            
            # Преобразуем в число
            truncated_hash = struct.unpack('>I', truncated_hash)[0] & 0x7FFFFFFF
            
            # Берём последние 6 цифр
            otp = truncated_hash % 1000000
            
            if otp == code_int:
                return True
        
        return False
    
    def generate_recovery_codes(self, count: int = 10) -> List[str]:
        """
        Сгенерировать коды восстановления.
        
        Формат: XXXX-XXXX-XXXX
        """
        codes = []
        for _ in range(count):
            code = '-'.join([
                secrets.token_hex(2).upper(),
                secrets.token_hex(2).upper(),
                secrets.token_hex(2).upper()
            ])
            codes.append(code)
        return codes
    
    def hash_recovery_code(self, code: str) -> str:
        """Хешировать код восстановления"""
        return hashlib.sha256(code.encode()).hexdigest()


# Глобальный экземпляр TOTP
totp_manager = TOTPManager(issuer="AutoDialer")


# =============================================
# Шифрование данных (Fernet)
# =============================================
class DataEncryption:
    """
    Шифрование конфиденциальных данных.
    
    Использует Fernet (AES-128-CBC + HMAC-SHA256).
    """
    
    def __init__(self, key: Optional[bytes] = None):
        if key is None:
            # Генерируем ключ из SECRET_KEY
            key = self._derive_key(settings.SECRET_KEY)
        self.fernet = Fernet(key)
    
    @staticmethod
    def _derive_key(secret: str) -> bytes:
        """Получить ключ шифрования из секрета"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"autodialer_salt",
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    
    @classmethod
    def generate_key(cls) -> bytes:
        """Сгенерировать новый ключ шифрования"""
        return Fernet.generate_key()
    
    def encrypt(self, data: str) -> str:
        """Зашифровать строку"""
        if not data:
            return ""
        return self.fernet.encrypt(data.encode()).decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """Расшифровать строку"""
        if not encrypted_data:
            return ""
        try:
            return self.fernet.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            logger.error(f"Ошибка расшифровки: {e}")
            raise SecurityError("Не удалось расшифровать данные")
    
    def encrypt_dict(self, data: Dict[str, Any]) -> str:
        """Зашифровать словарь"""
        import json
        return self.encrypt(json.dumps(data))
    
    def decrypt_dict(self, encrypted_data: str) -> Dict[str, Any]:
        """Расшифровать словарь"""
        import json
        decrypted = self.decrypt(encrypted_data)
        return json.loads(decrypted)


# Глобальный экземпляр шифрования
data_encryption = DataEncryption()


# =============================================
# Утилиты безопасности
# =============================================
def generate_secure_random_string(length: int = 32, chars: str = None) -> str:
    """
    Сгенерировать безопасную случайную строку.
    
    Args:
        length: Длина строки
        chars: Допустимые символы (по умолчанию буквы + цифры)
    """
    if chars is None:
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    
    return ''.join(secrets.choice(chars) for _ in range(length))


def generate_secure_token(length: int = 64) -> str:
    """Сгенерировать безопасный токен (hex)"""
    return secrets.token_hex(length // 2)


def constant_time_compare(a: str, b: str) -> bool:
    """
    Сравнение строк за константное время (защита от timing attacks).
    """
    return hmac.compare_digest(a, b)


def hash_sha256(data: str) -> str:
    """Вычислить SHA-256 хеш"""
    return hashlib.sha256(data.encode()).hexdigest()


def hash_md5(data: str) -> str:
    """Вычислить MD5 хеш (не для безопасности!)"""
    return hashlib.md5(data.encode()).hexdigest()


def mask_sensitive_data(data: str, visible_start: int = 4, visible_end: int = 4) -> str:
    """
    Маскировать конфиденциальные данные.
    
    Пример: mask_sensitive_data("1234567890", 4, 4) -> "1234****7890"
    """
    if not data:
        return ""
    
    length = len(data)
    if length <= visible_start + visible_end:
        return "*" * length
    
    start = data[:visible_start]
    end = data[-visible_end:] if visible_end > 0 else ""
    masked_length = length - visible_start - visible_end
    
    return f"{start}{'*' * masked_length}{end}"


def mask_email(email: str) -> str:
    """Маскировать email"""
    if not email or '@' not in email:
        return "***@***.***"
    
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = local[0] + "*" * (len(local) - 1) if local else "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    
    domain_parts = domain.split('.')
    if len(domain_parts) >= 2:
        masked_domain = domain_parts[0][0] + "*" * (len(domain_parts[0]) - 1) if domain_parts[0] else "*"
        masked_domain += "." + ".".join(domain_parts[1:])
    else:
        masked_domain = domain
    
    return f"{masked_local}@{masked_domain}"


def mask_phone(phone: str) -> str:
    """Маскировать номер телефона"""
    if not phone:
        return ""
    
    digits = re.sub(r'\D', '', phone)
    if len(digits) < 6:
        return "*" * len(phone)
    
    return f"+{digits[0]} (***) ***-{digits[-4:]}"


# =============================================
# Блокировка после неудачных попыток
# =============================================
class LoginAttemptTracker:
    """
    Отслеживание неудачных попыток входа.
    """
    
    def __init__(self, redis_client, max_attempts: int = 5, block_duration: int = 300):
        self.redis = redis_client
        self.max_attempts = max_attempts
        self.block_duration = block_duration
    
    def _key(self, identifier: str) -> str:
        return f"login_attempts:{identifier}"
    
    async def record_failure(self, identifier: str) -> Tuple[int, bool]:
        """
        Записать неудачную попытку.
        
        Returns:
            (количество попыток, заблокирован ли)
        """
        key = self._key(identifier)
        
        # Инкрементируем счётчик
        attempts = await self.redis.incr(key)
        
        # Устанавливаем TTL при первой попытке
        if attempts == 1:
            await self.redis.expire(key, self.block_duration)
        
        is_blocked = attempts >= self.max_attempts
        
        if is_blocked:
            logger.warning(f"Идентификатор {mask_sensitive_data(identifier)} заблокирован после {attempts} попыток")
        
        return attempts, is_blocked
    
    async def record_success(self, identifier: str) -> None:
        """Сбросить счётчик при успешном входе"""
        key = self._key(identifier)
        await self.redis.delete(key)
    
    async def is_blocked(self, identifier: str) -> bool:
        """Проверить, заблокирован ли идентификатор"""
        key = self._key(identifier)
        attempts = await self.redis.get(key)
        return attempts is not None and int(attempts) >= self.max_attempts
    
    async def get_attempts(self, identifier: str) -> int:
        """Получить количество попыток"""
        key = self._key(identifier)
        attempts = await self.redis.get(key)
        return int(attempts) if attempts else 0
    
    async def get_ttl(self, identifier: str) -> int:
        """Получить оставшееся время блокировки"""
        key = self._key(identifier)
        return await self.redis.ttl(key)
    
    async def reset(self, identifier: str) -> None:
        """Сбросить счётчик"""
        key = self._key(identifier)
        await self.redis.delete(key)


# =============================================
# CSRF защита
# =============================================
def generate_csrf_token() -> str:
    """Сгенерировать CSRF токен"""
    return generate_secure_token(32)


def verify_csrf_token(stored_token: str, provided_token: str) -> bool:
    """Проверить CSRF токен"""
    return constant_time_compare(stored_token, provided_token)


# =============================================
# Экспорт
# =============================================
__all__ = [
    # Исключения
    "SecurityError",
    "PasswordValidationError",
    "TokenError",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenRevokedError",
    "ApiKeyError",
    
    # Пароли
    "hash_password",
    "verify_password",
    "validate_password_strength",
    "check_password_strength",
    
    # JWT токены
    "create_token",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "verify_token",
    "get_token_payload",
    "get_token_ttl",
    "is_token_expired",
    
    # API ключи
    "generate_api_key",
    "hash_api_key",
    "verify_api_key",
    "mask_api_key",
    "parse_api_key",
    
    # TOTP (2FA)
    "TOTPManager",
    "totp_manager",
    
    # Шифрование
    "DataEncryption",
    "data_encryption",
    
    # Утилиты
    "generate_secure_random_string",
    "generate_secure_token",
    "constant_time_compare",
    "hash_sha256",
    "hash_md5",
    "mask_sensitive_data",
    "mask_email",
    "mask_phone",
    
    # Блокировка
    "LoginAttemptTracker",
    
    # CSRF
    "generate_csrf_token",
    "verify_csrf_token",
]
