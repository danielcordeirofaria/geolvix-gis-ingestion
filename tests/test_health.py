"""
Testes do endpoint GET /api/v1/gis/health

Usa fastapi.testclient.TestClient (síncrono) para testar o health check
sem subir banco de dados. O endpoint /health não usa Depends(get_db_with_tenant)
nem autenticação, portanto nenhum mock de banco é necessário.

O lifespan do app chama engine.dispose() no shutdown. Para evitar que o
TestClient tente abrir conexão com o banco durante o ciclo de vida, injetamos
um engine mockado via monkeypatch antes de importar o app.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture: client com engine mockado
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """
    Cria um TestClient isolado com o engine do SQLAlchemy mockado.

    O patch em 'app.database.engine' substitui o engine real por um MagicMock
    cujo método dispose() é um AsyncMock — isso impede qualquer tentativa de
    conexão com o banco durante o startup/shutdown do lifespan.
    """
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock(return_value=None)

    with patch("app.database.engine", mock_engine):
        # Importamos o app após o patch para garantir que o lifespan já vê o mock
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as test_client:
            yield test_client


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

def test_health_retorna_ok(client):
    """
    GET /api/v1/gis/health deve retornar HTTP 200 com corpo JSON contendo:
      - "status": "ok"
      - "service": nome do serviço configurado em Settings.APP_NAME
      - "version": versão configurada em Settings.APP_VERSION

    Este teste não acessa banco de dados e deve rodar completamente offline.
    """
    response = client.get("/api/v1/gis/health")

    # Verifica código de status HTTP
    assert response.status_code == 200, (
        f"Esperado 200, obtido {response.status_code}. Body: {response.text}"
    )

    body = response.json()

    # Verifica que o campo 'status' é exatamente "ok"
    assert "status" in body, "Resposta deve conter o campo 'status'"
    assert body["status"] == "ok", f"status esperado 'ok', obtido '{body['status']}'"

    # Verifica que o campo 'service' está presente e não é vazio
    assert "service" in body, "Resposta deve conter o campo 'service'"
    assert isinstance(body["service"], str) and len(body["service"]) > 0, (
        "Campo 'service' deve ser uma string não vazia"
    )

    # Verifica que o campo 'version' está presente e não é vazio
    assert "version" in body, "Resposta deve conter o campo 'version'"
    assert isinstance(body["version"], str) and len(body["version"]) > 0, (
        "Campo 'version' deve ser uma string não vazia"
    )
