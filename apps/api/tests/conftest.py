import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm_provider
from app.core.database import get_db, get_session_factory
from app.llm.demo_responses import DEMO_RESPONSES
from app.llm.mock import MockProvider
from app.main import create_app
from app.models import Base


@pytest.fixture()
def test_engine():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def test_session_factory(test_engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def mock_provider():
    return MockProvider(dict(DEMO_RESPONSES))


@pytest.fixture()
def client(test_session_factory, mock_provider):
    app = create_app()

    def override_get_db():
        session = test_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: test_session_factory
    app.dependency_overrides[get_llm_provider] = lambda: mock_provider
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def db_session(test_session_factory):
    session = test_session_factory()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def bengaluru_scenario(client):
    response = client.post(
        "/api/v1/scenarios",
        json={
            "input": (
                "I got a job offer in Bengaluru. I currently live with my parents, "
                "I'm comfortable with my current job, I have a relationship here, "
                "and I've always wanted to build a startup. The new job pays 40% more."
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]
