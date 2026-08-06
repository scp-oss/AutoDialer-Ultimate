"""
Integration test: full app lifespan (DB + Redis connect, services init)
against a real Postgres/Redis, exactly like production - only AMI/Asterisk
is expected to be unreachable, which must not prevent startup.
"""


def test_health_endpoint_reports_status(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert "status" in body


def test_liveness_and_readiness_probes(client):
    assert client.get("/api/health/live").status_code == 200
    # Readiness may report not-ready if AMI is unreachable (expected in CI
    # without Asterisk) - the endpoint itself must still respond, not 5xx.
    assert client.get("/api/health/ready").status_code == 200


def test_docs_available_in_debug_mode(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
