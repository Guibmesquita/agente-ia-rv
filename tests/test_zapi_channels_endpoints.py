"""
Task #255 — Regressões de endpoint (HTTP) para canais Z-API.

Cobre:
- POST /zapi/channels sem client_token persiste NULL no DB e retorna
  client_token_source="global".
- POST /zapi/channels com client_token preenchido retorna source="own".
- POST com falha no commit retorna HTTP 500 com detail informativo,
  SEM expor valores sensíveis (token/instance_id).
- PATCH normaliza client_token vazio para NULL.
"""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """TestClient com autenticação real (JWT admin) + bypass de conectividade Z-API."""
    monkeypatch.setenv("ZAPI_CLIENT_TOKEN", "GLOBAL_FALLBACK_TOKEN_TEST")

    import main
    import api.endpoints.integrations as integrations_mod
    from core.security import create_access_token
    from services.whatsapp_client import ZAPIClient

    # Bypass autorização específica do endpoint (role check) mas mantém middleware global
    def _fake_auth(request):
        return {"role": "admin", "sub": "test@svn.com.br", "email": "test@svn.com.br"}

    monkeypatch.setattr(integrations_mod, "_auth_zapi_channel", _fake_auth)

    async def _fake_connectivity(self, timeout=5.0):
        return "unreachable"

    monkeypatch.setattr(ZAPIClient, "check_connectivity", _fake_connectivity)

    # Token JWT válido para passar pelo GlobalAuthMiddleware
    token = create_access_token({"sub": "test@svn.com.br", "user_id": 1, "role": "admin"})
    # Lifespan registra os routers — usar TestClient como context manager
    with TestClient(main.app) as tc:
        tc.cookies.set("access_token", token)
        yield tc


def _cleanup_channel(channel_id):
    """Remove canal de teste do banco para idempotência."""
    from database.database import SessionLocal
    from database.models import ZAPIChannel

    db = SessionLocal()
    try:
        ch = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
        if ch:
            db.delete(ch)
            db.commit()
    finally:
        db.close()


def test_post_channel_without_client_token_persists_null(client):
    """POST sem client_token → DB recebe NULL e response.source='global'."""
    payload = {
        "name": "TestChannel_NoToken_T255",
        "label": "T255-NoToken",
        "instance_id": "TEST_INST_T255_NOTOKEN",
        "token": "TEST_TOK_T255_NOTOKEN",
        # client_token AUSENTE
    }
    resp = client.post("/api/integrations/zapi/channels", json=payload)
    assert resp.status_code == 201, f"Esperado 201, veio {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["client_token_source"] == "global"
    channel_id = data["id"]

    try:
        # Confirma NULL no DB
        from database.database import SessionLocal
        from database.models import ZAPIChannel
        db = SessionLocal()
        try:
            ch = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
            assert ch is not None
            assert ch.client_token is None, (
                f"client_token deveria ser NULL no DB, veio: {ch.client_token!r}"
            )
        finally:
            db.close()
    finally:
        _cleanup_channel(channel_id)


def test_post_channel_with_explicit_client_token_persists_own(client):
    """POST com client_token preenchido → DB recebe o valor e response.source='own'."""
    payload = {
        "name": "TestChannel_OwnToken_T255",
        "label": "T255-Own",
        "instance_id": "TEST_INST_T255_OWN",
        "token": "TEST_TOK_T255_OWN",
        "client_token": "OWN_CT_T255_ABC",
    }
    resp = client.post("/api/integrations/zapi/channels", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["client_token_source"] == "own"
    channel_id = data["id"]

    try:
        from database.database import SessionLocal
        from database.models import ZAPIChannel
        db = SessionLocal()
        try:
            ch = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
            assert ch.client_token == "OWN_CT_T255_ABC"
        finally:
            db.close()
    finally:
        _cleanup_channel(channel_id)


def test_post_channel_failure_returns_informative_detail_without_secrets(client, monkeypatch):
    """
    POST com erro no commit retorna HTTP 500 com detail informativo
    e NÃO vaza o token/instance_id na mensagem (mesmo se a exceção bruta os contiver).
    """
    # Força exceção durante o commit incluindo um valor sensível na mensagem
    SECRET_TOKEN = "SUPERSECRET_TOKEN_VALUE_T255"
    SECRET_INST = "SUPERSECRET_INSTANCE_T255"

    from sqlalchemy.orm import Session

    original_commit = Session.commit

    def failing_commit(self, *args, **kwargs):
        raise RuntimeError(f"DB fake error mentioning {SECRET_TOKEN} and {SECRET_INST}")

    monkeypatch.setattr(Session, "commit", failing_commit)

    payload = {
        "name": "TestChannel_Failure_T255",
        "label": "T255-Fail",
        "instance_id": SECRET_INST,
        "token": SECRET_TOKEN,
        "client_token": "OWN_T255_FAIL",
    }
    resp = client.post("/api/integrations/zapi/channels", json=payload)

    # Restaura commit antes de assertions (para cleanup posterior se necessário)
    monkeypatch.setattr(Session, "commit", original_commit)

    assert resp.status_code == 500, f"Esperado 500, veio {resp.status_code}: {resp.text}"
    data = resp.json()
    detail = data.get("detail", "")
    # Mensagem deve ser informativa (não "Ocorreu um erro interno")
    assert "RuntimeError" in detail or "Falha ao criar canal" in detail, (
        f"detail não é informativo: {detail!r}"
    )
    # CRÍTICO: não deve vazar valores sensíveis
    assert SECRET_TOKEN not in detail, f"Token vazado no detail: {detail!r}"
    assert SECRET_INST not in detail, f"Instance ID vazado no detail: {detail!r}"
    # Deve conter o marcador de redação
    assert "***" in detail


def test_patch_channel_clears_client_token_with_empty_string(client):
    """PATCH com client_token='' normaliza para NULL."""
    # Cria canal com client_token próprio
    create_payload = {
        "name": "TestChannel_Clear_T255",
        "label": "T255-Clear",
        "instance_id": "TEST_INST_T255_CLEAR",
        "token": "TEST_TOK_T255_CLEAR",
        "client_token": "OWN_T255_TO_CLEAR",
    }
    resp = client.post("/api/integrations/zapi/channels", json=create_payload)
    assert resp.status_code == 201
    channel_id = resp.json()["id"]

    try:
        # Agora limpa via PATCH com string vazia
        resp = client.patch(
            f"/api/integrations/zapi/channels/{channel_id}",
            json={"client_token": ""},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["client_token_source"] == "global"

        from database.database import SessionLocal
        from database.models import ZAPIChannel
        db = SessionLocal()
        try:
            ch = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
            assert ch.client_token is None, (
                f"PATCH com '' deveria zerar client_token, veio: {ch.client_token!r}"
            )
        finally:
            db.close()
    finally:
        _cleanup_channel(channel_id)
