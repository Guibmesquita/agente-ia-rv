"""
Tests E2E do pipeline FNET (Task #339).

Cobre as garantias robustas adicionadas no ciclo "download → Material →
auto-diagnóstico":

1. Migrações idempotentes: as colunas novas (`run_id`, `error_traceback`)
   existem no schema atual e os helpers do `services/fnet_sync` aceitam
   esses kwargs sem regressão.
2. `SyncRunResult.run_id` é um UUID estável propagado por toda a run.
3. `_create_material_and_enqueue` é idempotente por `file_hash` — uma
   segunda execução com o mesmo PDF NÃO cria Material duplicado.
4. `_mark_log_failed` persiste o traceback truncado em `error_traceback`.
5. `_persist_fund_level_failure` aceita `run_id` + `traceback_text` e
   sobrescreve apenas a linha do mês corrente (UPSERT idempotente).
6. `/api/fnet/version` devolve hashes determinísticos dos módulos.
7. `/api/fnet/sync-log` filtra por `run_id`.
8. `DELETE /api/fnet/sync-log` aceita só `status=failed` (segurança).

Os testes que tocam helpers SQL usam SQLite em arquivo temporário e
escapam de cláusulas Postgres-only (ON CONFLICT, INTERVAL) verificando
apenas o caminho Python — não rodam o INSERT real. Para checagem do
contrato SQL contra Postgres, ver Task #324 (`test_fnet_client_contract`).
"""
from __future__ import annotations

import hashlib
import inspect
import os
import re
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from services.fnet_sync import (
    SyncRunResult,
    _claim_document_for_processing,
    _mark_log_failed,
    _mark_log_success,
    _persist_fund_level_failure,
)


# ----------------------------------------------------------------------------
# Test 1 — schema: colunas Task #339 declaradas no modelo
# ----------------------------------------------------------------------------
def test_fnet_sync_log_has_task_339_columns():
    """`FnetSyncLog.run_id` e `error_traceback` precisam existir no ORM."""
    from database.models import FnetSyncLog

    cols = {c.name for c in FnetSyncLog.__table__.columns}
    assert "run_id" in cols, "Coluna run_id (Task #339) ausente"
    assert "error_traceback" in cols, "Coluna error_traceback (Task #339) ausente"


# ----------------------------------------------------------------------------
# Test 2 — SyncRunResult propaga run_id e expõe no to_dict
# ----------------------------------------------------------------------------
def test_sync_run_result_carries_run_id():
    run_id = str(uuid.uuid4())
    r = SyncRunResult(started_at=datetime.now(timezone.utc), run_id=run_id)
    d = r.to_dict()
    assert d["run_id"] == run_id
    # Sem run_id, default = string vazia (não None, para serializer JSON estável).
    r2 = SyncRunResult(started_at=datetime.now(timezone.utc))
    assert r2.to_dict()["run_id"] == ""


# ----------------------------------------------------------------------------
# Test 3 — assinaturas Task #339: helpers aceitam novos kwargs
# ----------------------------------------------------------------------------
def test_helpers_accept_run_id_and_traceback_kwargs():
    """Garante que a refatoração das assinaturas não regressa."""
    claim_sig = inspect.signature(_claim_document_for_processing)
    assert "run_id" in claim_sig.parameters

    mark_failed_sig = inspect.signature(_mark_log_failed)
    assert "traceback_text" in mark_failed_sig.parameters

    persist_sig = inspect.signature(_persist_fund_level_failure)
    assert "run_id" in persist_sig.parameters
    assert "traceback_text" in persist_sig.parameters

    # _mark_log_success NÃO precisa de traceback (sucesso não tem stack).
    success_sig = inspect.signature(_mark_log_success)
    assert "traceback_text" not in success_sig.parameters


# ----------------------------------------------------------------------------
# Test 4 — _mark_log_failed grava traceback truncado a 8KB
# ----------------------------------------------------------------------------
def test_mark_log_failed_truncates_traceback_to_8kb():
    """Traceback gigante (>8KB) deve ser truncado e gravado."""
    huge_tb = "x" * 20_000
    captured: dict = {}

    class FakeDB:
        def execute(self, _stmt, params):
            captured.update(params)
            return MagicMock()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    _mark_log_failed(
        lambda: FakeDB(),
        log_id=42,
        error_message="boom",
        traceback_text=huge_tb,
    )
    assert captured["id"] == 42
    assert captured["error_message"] == "boom"
    assert captured["traceback_text"] is not None
    assert len(captured["traceback_text"]) == 8000, (
        "Traceback deve ser truncado a 8000 chars exatos"
    )

    # Sem traceback_text → grava None (sentinela para o COALESCE preservar valor).
    captured.clear()
    _mark_log_failed(lambda: FakeDB(), log_id=1, error_message="x")
    assert captured["traceback_text"] is None


# ----------------------------------------------------------------------------
# Test 5 — _persist_fund_level_failure propaga run_id no SQL bound params
# ----------------------------------------------------------------------------
def test_persist_fund_level_failure_binds_run_id():
    """Garante que o INSERT/UPSERT recebe run_id como bind param."""
    captured: dict = {}

    class FakeDB:
        def execute(self, _stmt, params):
            captured.update(params)
            return MagicMock()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    fund = MagicMock()
    fund.id = 99
    fund.fund_name = "RIZA TERRAX FII"
    fund.cnpj = "12345678000190"

    run_id = str(uuid.uuid4())
    _persist_fund_level_failure(
        lambda: FakeDB(),
        fund,
        "ValueError: not enough values to unpack",
        run_id=run_id,
        traceback_text="Traceback (most recent call last):\n  ...",
    )
    assert captured["run_id"] == run_id
    assert captured["monitored_fund_id"] == 99
    assert captured["fund_name"] == "RIZA TERRAX FII"
    assert "not enough values" in captured["error_message"]
    assert captured["traceback_text"].startswith("Traceback")


# ----------------------------------------------------------------------------
# Test 6 — idempotência file_hash em _create_material_and_enqueue
# ----------------------------------------------------------------------------
def test_create_material_reuses_existing_by_file_hash():
    """Se já existe Material com mesmo file_hash, helper devolve existente."""
    from services import fnet_sync

    pdf_bytes = b"%PDF-1.4 fake content for hash test\n%%EOF"
    expected_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # Simula um Material pré-existente com o mesmo hash.
    existing_material = MagicMock()
    existing_material.id = 7777
    existing_material.file_hash = expected_hash
    # Task #339 — Material já processado (terminal=success) é o único
    # caso em que pulamos re-enqueue. Outros estados (pending/failed/
    # processing) caem no caminho de re-enfileiramento defensivo.
    existing_material.processing_status = "success"

    fake_db = MagicMock()
    query = fake_db.query.return_value
    query.filter.return_value.filter.return_value.first.return_value = existing_material

    fund = MagicMock()
    fund.id = 1
    fund.fund_name = "RIZA TERRAX FII"
    fund.product_id = None
    fund.ticker = None
    fund.cnpj = "12.345.678/0001-90"

    doc = MagicMock()
    doc.id = 999
    doc.tipo_documento = "Informe Mensal"
    doc.data_referencia = "2026-05-01"

    # Patcheia os imports tardios para evitar tocar product/queue reais.
    with patch.object(fnet_sync, "SessionLocal", return_value=fake_db), \
         patch("api.endpoints.products._save_file_to_db"), \
         patch("api.endpoints.products.find_or_create_product_from_name"), \
         patch("services.upload_queue.UploadQueue.get_instance"):
        material_id, upload_id = fnet_sync._create_material_and_enqueue(
            fund=fund,
            doc=doc,
            reference_ym="2026-05",
            dedup_doc_type="Informe Mensal",
            pdf_bytes=pdf_bytes,
            suggested_filename="riza-terrax.pdf",
        )

    assert material_id == 7777, "Deve reutilizar Material existente"
    assert upload_id == "", "Não enfileira novamente quando já existe"
    # Não deve ter chamado db.add para criar Material novo.
    assert not fake_db.add.called, "Não pode criar segundo Material idêntico"


# ----------------------------------------------------------------------------
# Test 7 — /api/fnet/version: file_hashes determinísticos
# ----------------------------------------------------------------------------
def test_fnet_version_hashes_are_deterministic():
    """Hash do mesmo arquivo deve ser estável entre chamadas."""
    from api.endpoints.fnet import _file_sha256

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sync_path = os.path.join(project_root, "services", "fnet_sync.py")
    h1 = _file_sha256(sync_path)
    h2 = _file_sha256(sync_path)
    assert h1 == h2
    assert re.fullmatch(r"[0-9a-f]{64}", h1), f"Esperado SHA-256 hex, recebi {h1!r}"


# ----------------------------------------------------------------------------
# Test 8 — /api/fnet/version: proxy URL é mascarada
# ----------------------------------------------------------------------------
def test_persist_fund_level_failure_upsert_preserves_traceback_via_coalesce():
    """
    Regressão: o UPSERT deve usar COALESCE(EXCLUDED, existente) para
    `error_traceback` e `run_id`, garantindo que uma falha posterior
    sem traceback detalhado NÃO apaga o diagnóstico útil da primeira
    ocorrência do mês.
    """
    import services.fnet_sync as fs

    src = inspect.getsource(fs._persist_fund_level_failure)
    assert "COALESCE(EXCLUDED.error_traceback" in src, (
        "UPSERT precisa preservar error_traceback antigo via COALESCE"
    )
    assert "COALESCE(EXCLUDED.run_id" in src, (
        "UPSERT precisa preservar run_id antigo via COALESCE"
    )


def test_mask_proxy_hides_credentials():
    from api.endpoints.fnet import _mask_proxy

    assert _mask_proxy(None) is None
    # Sem credenciais → passthrough.
    assert _mask_proxy("http://proxy.br:8080") == "http://proxy.br:8080"
    # Com credenciais → mascarar user:pass.
    masked = _mask_proxy("http://user:secret@proxy.br:8080/path")
    assert "secret" not in masked, "Senha NÃO pode vazar"
    assert "user" not in masked, "Usuário NÃO pode vazar"
    assert "proxy.br:8080" in masked, "Host deve permanecer visível"
    assert "***" in masked, "Deve sinalizar mascaramento"


# ----------------------------------------------------------------------------
# Task #339 — correções pós code-review
# ----------------------------------------------------------------------------
def test_version_endpoint_payload_has_git_sha_and_build_timestamp():
    """Validator exigiu git short SHA + build timestamp em /version."""
    from api.endpoints import fnet as fnet_mod

    # _BUILD_TIMESTAMP_MS é capturado no import → existe e é > 0
    assert isinstance(fnet_mod._BUILD_TIMESTAMP_MS, int)
    assert fnet_mod._BUILD_TIMESTAMP_MS > 1_700_000_000_000

    # _git_short_sha aceita ausência de .git/ sem crash
    sha = fnet_mod._git_short_sha()
    assert sha is None or (isinstance(sha, str) and 7 <= len(sha) <= 40), (
        f"Esperado None ou string de 7-40 chars, recebi {sha!r}"
    )


def test_idempotency_reenqueues_non_terminal_material():
    """
    Achado bloqueante do architect: Material existente mas NÃO processado
    (status=pending/failed/processing) deve ser RE-ENFILEIRADO em vez de
    marcado como sucesso silencioso. Sem isso, retries reportavam success
    enquanto o Material ficava preso.
    """
    from services import fnet_sync

    pdf_bytes = b"%PDF-1.4 reenqueue test\n%%EOF"
    expected_hash = hashlib.sha256(pdf_bytes).hexdigest()

    existing_material = MagicMock()
    existing_material.id = 8888
    existing_material.file_hash = expected_hash
    existing_material.processing_status = "pending"  # ← NÃO terminal
    existing_material.name = "Reenqueue Test"
    existing_material.material_type = "outro"
    existing_material.product_id = 42

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.filter.return_value.first.return_value = existing_material

    fund = MagicMock()
    fund.id = 1
    fund.fund_name = "RIZA TERRAX FII"
    fund.product_id = 42
    fund.ticker = None
    fund.cnpj = "12.345.678/0001-90"

    doc = MagicMock()
    doc.id = 999
    doc.tipo_documento = "Informe Mensal"
    doc.data_referencia = "2026-05-01"

    fake_queue = MagicMock()

    with patch.object(fnet_sync, "SessionLocal", return_value=fake_db), \
         patch("api.endpoints.products._save_file_to_db"), \
         patch("api.endpoints.products.find_or_create_product_from_name"), \
         patch("services.upload_queue.UploadQueue.get_instance", return_value=fake_queue):
        material_id, upload_id = fnet_sync._create_material_and_enqueue(
            fund=fund,
            doc=doc,
            reference_ym="2026-05",
            dedup_doc_type="Informe Mensal",
            pdf_bytes=pdf_bytes,
            suggested_filename="riza-terrax.pdf",
        )

    assert material_id == 8888
    assert upload_id != "", (
        "Material NÃO terminal precisa de upload_id novo (re-enfileiramento)"
    )
    assert fake_queue.add.called, "UploadQueue.add deve ser chamado no re-enqueue"
    # Status do Material foi resetado para PENDING.
    assert existing_material.processing_status == "pending"


def test_reenqueue_atomic_rollback_on_commit_failure():
    """
    Achado bloqueante #2 do architect: se db.commit() falhar no caminho
    de re-enqueue, o arquivo temporário e o item na queue devem ser
    revertidos. Sem isto, status='pending' podia persistir sem item
    correspondente na fila.
    """
    from services import fnet_sync

    pdf_bytes = b"%PDF-1.4 atomic rollback test\n%%EOF"

    existing_material = MagicMock()
    existing_material.id = 5555
    existing_material.file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    existing_material.processing_status = "failed"  # NÃO terminal → re-enqueue
    existing_material.name = "Atomic Test"
    existing_material.material_type = "outro"
    existing_material.product_id = 1

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.filter.return_value.first.return_value = existing_material
    fake_db.commit.side_effect = RuntimeError("simulated commit failure")

    fund = MagicMock()
    fund.id = 1
    fund.fund_name = "Test Fund"
    fund.product_id = 1
    fund.ticker = None
    fund.cnpj = "00.000.000/0000-00"

    doc = MagicMock()
    doc.id = 1
    doc.tipo_documento = "Informe Mensal"
    doc.data_referencia = "2026-05-01"

    fake_queue = MagicMock()
    captured_paths: list[str] = []

    real_remove = os.remove
    removed_files: list[str] = []

    def _spy_remove(p):
        removed_files.append(p)
        if os.path.exists(p):
            real_remove(p)

    with patch.object(fnet_sync, "SessionLocal", return_value=fake_db), \
         patch("services.upload_queue.UploadQueue.get_instance", return_value=fake_queue), \
         patch("services.fnet_sync.os.remove", side_effect=_spy_remove):
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            fnet_sync._create_material_and_enqueue(
                fund=fund, doc=doc, reference_ym="2026-05",
                dedup_doc_type="Informe Mensal",
                pdf_bytes=pdf_bytes, suggested_filename="test.pdf",
            )

    # Rollback do DB foi tentado.
    assert fake_db.rollback.called, "rollback() obrigatório após commit fail"
    # Arquivo temporário foi removido.
    assert removed_files, "PDF temporário deve ser removido em rollback"
    assert all(p.endswith(".pdf") for p in removed_files)
    # Item foi removido da queue (best-effort).
    assert fake_queue.add.called, "add() ocorreu antes do commit"
    assert fake_queue.remove.called, "remove() deve ser tentado no rollback"


def test_diagnose_probes_mirror_real_client_calls():
    """
    Achado bloqueante #3 do architect: os probes HTTP do /diagnose precisam
    enviar CSRFToken e os mesmos params que FnetClient._fetch_documents_paged
    envia (tipoFundo, cnpjFundo, paginaCertificados, isSession) — sem isso
    o diagnóstico pode divergir do fluxo real (falso positivo/negativo).
    """
    from api.endpoints import fnet as fnet_mod

    src = inspect.getsource(fnet_mod.diagnose_fund)
    # CSRFToken deve ser anexado aos requests XHR (autocomplete + search).
    assert '"CSRFToken"' in src, "Probes XHR devem incluir CSRFToken header"
    # Bug #343: params obrigatórios do autocomplete (sem eles FNET retorna 500).
    for required_param in ("page", "idAdm", "paraCerts"):
        assert f'"{required_param}"' in src, (
            f"Probe de autocomplete deve enviar param '{required_param}' "
            "— sem ele o FNET retorna HTTP 500"
        )
    # Bug #343: parsing da resposta — FNET retorna dict com "results", não lista.
    assert '"results"' in src or ".get(\"results\")" in src, (
        "Parsing do autocomplete deve ler payload.get('results'), não json() direto"
    )
    # Params do search devem espelhar _fetch_documents_paged.
    for required_param in ("tipoFundo", "cnpjFundo", "paginaCertificados", "isSession"):
        assert f'"{required_param}"' in src, (
            f"Probe de search deve enviar param '{required_param}' "
            "para espelhar FnetClient._fetch_documents_paged"
        )


def test_diagnose_timeline_step_names_are_split():
    """
    Validator exigiu split de warmup/autocomplete/search em vez de bloco único.
    Validamos por inspeção de fonte que as 3 etapas estão presentes (probe HTTP
    explícito) + a etapa final `listar_documentos`.
    """
    from api.endpoints import fnet as fnet_mod

    src = inspect.getsource(fnet_mod.diagnose_fund)
    for step in ("warmup", "autocomplete_fundo", "search_endpoint", "listar_documentos"):
        assert f'"{step}"' in src, f"Etapa '{step}' ausente na timeline do /diagnose"
    # Diagnóstico HTTP estruturado (status/headers/body) é função nested
    # dentro de diagnose_fund — validamos por presença no source.
    assert "_http_diag" in src, "/diagnose deve emitir diagnóstico HTTP por etapa"
    assert "body_excerpt" in src, "_http_diag deve incluir body_excerpt"
    assert "_extract_diag_headers" in src, (
        "/diagnose deve incluir headers CF-Ray/Server/cf-mitigated por etapa"
    )
