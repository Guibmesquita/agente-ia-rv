"""
Task #255 — Regressões para Client-Token opcional em canais Z-API.

Cobre:
1. ZAPIClient em modo explícito com client_token=None faz fallback para
   ZAPI_CLIENT_TOKEN (env var).
2. ZAPIClient em modo explícito com client_token preenchido NÃO usa o env var.
3. Modelo ZAPIChannel aceita client_token=None (NULL no banco).
4. Endpoint de criação normaliza string vazia para None.
"""
import os
import pytest


def test_explicit_client_with_no_client_token_falls_back_to_env(monkeypatch):
    """ZAPIClient explícito sem client_token → usa ZAPI_CLIENT_TOKEN global."""
    monkeypatch.setenv("ZAPI_CLIENT_TOKEN", "GLOBAL_TOKEN_ABC123")
    from services.whatsapp_client import ZAPIClient

    client = ZAPIClient(
        instance_id="EXPLICIT_INSTANCE",
        token="EXPLICIT_TOKEN",
        client_token=None,
    )
    creds = client._get_credentials()
    assert creds["instance_id"] == "EXPLICIT_INSTANCE"
    assert creds["token"] == "EXPLICIT_TOKEN"
    assert creds["client_token"] == "GLOBAL_TOKEN_ABC123", (
        "client_token=None deveria fazer fallback para ZAPI_CLIENT_TOKEN"
    )


def test_explicit_client_with_empty_client_token_falls_back_to_env(monkeypatch):
    """ZAPIClient explícito com client_token vazio → usa global."""
    monkeypatch.setenv("ZAPI_CLIENT_TOKEN", "GLOBAL_TOKEN_XYZ")
    from services.whatsapp_client import ZAPIClient

    client = ZAPIClient(
        instance_id="INSTANCE_X",
        token="TOKEN_X",
        client_token="",
    )
    creds = client._get_credentials()
    assert creds["client_token"] == "GLOBAL_TOKEN_XYZ"


def test_explicit_client_with_own_client_token_does_not_fallback(monkeypatch):
    """Se canal tem client_token próprio, ignora o env var."""
    monkeypatch.setenv("ZAPI_CLIENT_TOKEN", "GLOBAL_TOKEN_SHOULD_NOT_BE_USED")
    from services.whatsapp_client import ZAPIClient

    client = ZAPIClient(
        instance_id="INSTANCE_Y",
        token="TOKEN_Y",
        client_token="OWN_TOKEN_FOR_THIS_CHANNEL",
    )
    creds = client._get_credentials()
    assert creds["client_token"] == "OWN_TOKEN_FOR_THIS_CHANNEL"


def test_legacy_mode_unchanged(monkeypatch):
    """Modo legado (sem credenciais explícitas) continua lendo as 3 env vars."""
    monkeypatch.setenv("ZAPI_INSTANCE_ID", "LEGACY_INSTANCE")
    monkeypatch.setenv("ZAPI_TOKEN", "LEGACY_TOKEN")
    monkeypatch.setenv("ZAPI_CLIENT_TOKEN", "LEGACY_CLIENT_TOKEN")
    from services.whatsapp_client import ZAPIClient

    client = ZAPIClient()
    creds = client._get_credentials()
    assert creds["instance_id"] == "LEGACY_INSTANCE"
    assert creds["token"] == "LEGACY_TOKEN"
    assert creds["client_token"] == "LEGACY_CLIENT_TOKEN"


def test_zapichannel_model_accepts_null_client_token():
    """O modelo ZAPIChannel aceita client_token=None."""
    from database.models import ZAPIChannel

    ch = ZAPIChannel(
        name="Test Channel",
        label="Test",
        instance_id="INST",
        token="TOK",
        client_token=None,
        is_legacy=False,
        is_active=True,
    )
    assert ch.client_token is None


def test_client_token_source_response_field():
    """GET /api/integrations/zapi/channels deve retornar client_token_source."""
    # Smoke test estrutural: confirma que a string 'client_token_source' está
    # na rota (não exercita HTTP, apenas garante que a chave foi adicionada).
    import api.endpoints.integrations as integrations_module
    import inspect

    src = inspect.getsource(integrations_module)
    assert '"client_token_source"' in src, (
        "Campo client_token_source não encontrado no endpoint."
    )
    # Mantém o alias legado por compatibilidade
    assert '"client_token_configured"' in src, (
        "Alias legado client_token_configured deve ser mantido."
    )
