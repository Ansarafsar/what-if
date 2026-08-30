def test_health_returns_ok(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "whatif-api"
    assert body["version"] == "0.1.0"


def test_ready_reports_database_ok(client):
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["database"]["status"] == "ok"


def test_ready_degraded_when_database_unreachable(client):
    from app.core.database import get_session_factory

    class BrokenSessionFactory:
        def __call__(self):
            raise RuntimeError("no database")

    client.app.dependency_overrides[get_session_factory] = lambda: BrokenSessionFactory()

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["database"]["status"] == "error"


def test_docs_served(client):
    response = client.get("/docs")
    assert response.status_code == 200


def test_request_id_header_returned(client):
    response = client.get("/api/v1/health")
    assert "x-request-id" in {k.lower() for k in response.headers.keys()}
