import pytest


@pytest.mark.asyncio
async def test_health_endpoint(test_client):
    response = await test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
