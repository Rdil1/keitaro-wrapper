import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app import models  # noqa: F401
from app.api import get_keitaro
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.keitaro import KeitaroClient
from app.main import app
from tests.fake_keitaro import FakeKeitaro


@pytest.fixture
def fake():
    return FakeKeitaro()


@pytest.fixture
def client(fake):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(_env_file=None, keitaro_api_key="test-key", campaign_prefix="test_ivanov_")

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    def _kt():
        kt = KeitaroClient(settings.api_base, "test-key", transport=fake.transport())
        yield kt
        kt.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_keitaro] = _kt
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.clear()
