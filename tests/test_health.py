from fastapi.testclient import TestClient


def test_health_reports_empty_index(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "documents_loaded": 0}
    assert response.headers["X-Request-ID"]


def test_home_serves_chat_page(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "PropLens" in response.text
    assert "AI property assistant for DarGlobal &amp; Wasalt" in response.text
