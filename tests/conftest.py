import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "autodialer_test")
os.environ.setdefault("DB_USER", "autodialer")
os.environ.setdefault("DB_PASSWORD", "autodialer_test")
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("AMI_HOST", "127.0.0.1")
os.environ.setdefault("AMI_PORT", "5038")
os.environ.setdefault("AMI_USER", "autodialer")
os.environ.setdefault("AMI_PASSWORD", "test_ami_password")
os.environ.setdefault("JWT_SECRET", "test_secret_key_at_least_32_characters_long_1234")


@pytest.fixture(scope="session")
def app():
    import app as app_package
    return app_package.create_app()


@pytest.fixture(scope="session")
def client(app):
    """
    TestClient as a context manager runs the FastAPI lifespan (startup/
    shutdown) exactly once for the whole test session, so DB/Redis connect
    for real and services are initialized - same code path as production,
    just against local test infrastructure. Session-scoped deliberately:
    app/__init__.py's services rely on module-level singletons
    (ServiceRegistry, _dialer_manager, _websocket_service, ...) that are not
    designed to be torn down and reinitialized repeatedly within one
    process, only once per process lifetime like a real deployment.
    AMI/Asterisk is expected to be unreachable in CI; app startup must not
    fail because of that (see app.services.dialer.init_dialer).
    """
    with TestClient(app) as c:
        yield c
