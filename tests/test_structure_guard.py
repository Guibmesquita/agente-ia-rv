"""Suite automatizada cobrindo as 3 camadas da guarda anti-captura de estrutura
(Tasks #164 e #167).

A guarda existe para impedir que materiais de produtos estruturados (POP, Collar,
Fence, COE...) sejam erroneamente vinculados a produtos-ação cadastrados que
compartilham o ticker do ativo subjacente. Exemplo do bug histórico:
"POP de RAPT4.pdf" caía no produto-ação RAPT4 (Randon).

As 3 camadas:
  1. `_match_products_to_db` (pre-analyze) — rejeita match de candidato
     estrutura contra produto-ação cadastrado.
  2. `link_products_and_queue` (`_cp_is_structure`) — descarta `product_id`
     pré-existente quando material é estrutura e produto matched é ação,
     e força `product_type='estruturada'` ao criar produto novo.
  3. Worker (`_process_item` + `_auto_create_product`) — desvincula
     `mat.product_id` errado em runtime e cria nova estrutura propagando
     `filename_hint`/`material_name`.

Roda como suite pytest (`pytest tests/test_structure_guard.py`) ou standalone
(`python tests/test_structure_guard.py`) — útil em ambientes de dev sem pytest.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_db_with_product(product_attrs: dict):
    """Mock de Session que retorna um único Product no .first() e [] em .all()."""
    mock_product = MagicMock()
    for k, v in product_attrs.items():
        setattr(mock_product, k, v)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_product
    mock_db.query.return_value.filter.return_value.all.return_value = []
    return mock_db, mock_product


def _sqlite_session():
    """Cria uma sessão SQLite in-memory com todos os models — para testes
    behavioral de funções que tocam vários campos / validações do model."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session()


# =========================================================================== #
# Camada 1 — pre-analyze: _match_products_to_db
# =========================================================================== #

def test_matcher_rejects_structure_against_acao_via_filename():
    """Filename "POP RAPT4.pdf" + IA disse "Ação" + RAPT4 ação cadastrada.
    Deve rejeitar o match e marcar is_structure_candidate=True."""
    from api.endpoints.products import _match_products_to_db

    db, _ = _make_db_with_product({
        "id": 999, "ticker": "RAPT4", "name": "Randon",
        "product_type": "acao", "name_aliases": "[]",
    })
    ai = [{"ticker": "RAPT4", "name": "Randon", "product_type": "Ação",
           "underlying_ticker": None}]
    res = _match_products_to_db(db, ai, filename="POP RAPT4 dez28.pdf")
    assert res, "deve devolver pelo menos 1 candidato"
    r = res[0]
    assert r["exists_in_db"] is False, f"esperava exists_in_db=False, veio {r}"
    assert r["is_structure_candidate"] is True
    assert r.get("rejected_match_reason"), "deve carregar motivo da rejeição"


def test_matcher_rejects_structure_via_underlying_ticker():
    """IA disse product_type='Estruturada' + underlying='MYPK3'. Mesmo com MYPK3
    ação no banco, não deve casar."""
    from api.endpoints.products import _match_products_to_db

    db, _ = _make_db_with_product({
        "id": 1001, "ticker": "MYPK3", "name": "Iochpe-Maxion",
        "product_type": "acao", "name_aliases": "[]",
    })
    ai = [{"ticker": None, "name": "POP sobre MYPK3",
           "product_type": "Estruturada", "underlying_ticker": "MYPK3"}]
    res = _match_products_to_db(db, ai, filename=None)
    assert res[0]["exists_in_db"] is False
    assert res[0]["is_structure_candidate"] is True


def test_matcher_keeps_match_when_both_are_structure():
    """Quando candidato é estrutura e produto cadastrado também é estrutura,
    não deve rejeitar (caso normal — re-upload de POP existente)."""
    from api.endpoints.products import _match_products_to_db

    db, _ = _make_db_with_product({
        "id": 2002, "ticker": None, "name": "POP sobre PETR4",
        "product_type": "estruturada", "name_aliases": "[]",
    })
    ai = [{"ticker": None, "name": "POP sobre PETR4",
           "product_type": "Estruturada", "underlying_ticker": "PETR4"}]
    res = _match_products_to_db(db, ai, filename="POP PETR4.pdf")
    assert res[0]["is_structure_candidate"] is True
    assert not res[0].get("rejected_match_reason"), (
        "não deve rejeitar quando ambos são estrutura"
    )


def test_matcher_does_not_flag_normal_acao_as_structure():
    """Negative case: research de ação normal não deve disparar guarda."""
    from api.endpoints.products import _match_products_to_db

    db, _ = _make_db_with_product({
        "id": 3003, "ticker": "PETR4", "name": "Petrobras",
        "product_type": "acao", "name_aliases": "[]",
    })
    ai = [{"ticker": "PETR4", "name": "Petrobras",
           "product_type": "Ação", "underlying_ticker": None}]
    res = _match_products_to_db(db, ai, filename="petr4_research_4t25.pdf")
    assert res[0]["is_structure_candidate"] is False
    assert not res[0].get("rejected_match_reason")


# =========================================================================== #
# Camada 2 — link_products_and_queue: _cp_is_structure + product_id discard
# =========================================================================== #

def test_link_and_queue_force_estruturada_in_source():
    """Source-level guard: link_and_queue precisa ter os dois pontos críticos
    (descarte de pid + coerção de product_type) presentes no código. Pega
    regressão se alguém remover o STRUCTURE_GUARD por engano."""
    src = (ROOT / "api" / "endpoints" / "products.py").read_text(encoding="utf-8")
    assert 'if cp_is_structure_flag and product_type_db != "estruturada"' in src, (
        "link_and_queue precisa coercir product_type para 'estruturada' "
        "quando candidato é estrutura"
    )
    assert 'product_type_db = "estruturada"' in src
    assert "[STRUCTURE_GUARD] layer=link_and_queue" in src
    # O bloco que descarta `pid` quando material é estrutura mas produto é ação:
    assert "pid = None" in src and "force_new = True" in src, (
        "link_and_queue precisa descartar pid pré-existente quando material "
        "é estrutura mas o produto matched é ação"
    )


def test_link_and_queue_discards_pid_when_structure_meets_acao():
    """Behavioral: simula link_products_and_queue invocando o endpoint async
    com mocks. Material "POP RAPT4.pdf" com confirmed_products apontando para
    o produto-ação RAPT4 (id=999). Esperado:
      - product_id 999 é descartado (pid = None)
      - novo Product é criado via db.add com product_type='estruturada'
      - upload_queue.add é chamado com queue_item válido"""
    import api.endpoints.products as products_mod
    from database.models import Product

    # Material parece estrutura via filename E nome.
    mat = MagicMock(spec=["id", "name", "source_file_path", "source_filename",
                          "ai_product_analysis", "material_type", "product_id",
                          "extracted_metadata"])
    mat.id = 42
    mat.name = "POP sobre RAPT4 dez28"
    mat.source_file_path = "/tmp/POP_RAPT4.pdf"
    mat.source_filename = "POP_RAPT4.pdf"
    mat.material_type = "outro"
    mat.product_id = None
    mat.ai_product_analysis = None
    mat.extracted_metadata = None

    # Produto-ação pré-existente que NÃO deve ser reaproveitado.
    acao_existing = MagicMock(spec=["id", "name", "ticker", "product_type",
                                    "name_aliases", "status"])
    acao_existing.id = 999
    acao_existing.name = "Randon"
    acao_existing.ticker = "RAPT4"
    acao_existing.product_type = "acao"
    acao_existing.name_aliases = "[]"
    acao_existing.status = "ativo"

    created_products: list = []

    class _FakeDBQuery:
        """Mock de db.query(Model).filter(...).first()/all()/delete()."""
        def __init__(self, model):
            self.model = model

        def filter(self, *a, **kw):
            return self

        def first(self):
            if self.model is __import__("database.models", fromlist=["Material"]).Material:
                return mat
            if self.model is Product:
                # Lookup por id (acao_existing.id == 999) ou por ticker.
                return acao_existing
            return None

        def all(self):
            return []

        def delete(self, *a, **kw):
            return 0

    db = MagicMock()
    db.query.side_effect = lambda model: _FakeDBQuery(model)
    db.add.side_effect = lambda obj: created_products.append(obj)
    db.commit = MagicMock()
    db.refresh = MagicMock()

    # Request fake — só precisa do .json() async.
    class _Req:
        async def json(self):
            return {
                "confirmed_products": [
                    {
                        "product_id": 999,
                        "ticker": "RAPT4",
                        "name": "Randon",
                        "product_type": "Ação",
                        "underlying_ticker": None,
                    }
                ],
                "primary_product_id": 999,
                "is_conceptual_material": False,
            }

    user = MagicMock()
    user.role = "admin"
    user.id = 1

    # Patches: file existence + upload_queue.add (não queremos enfileirar de verdade).
    with patch("os.path.exists", return_value=True), \
         patch("services.upload_queue.upload_queue.add") as queue_add, \
         patch.object(products_mod, "_merge_key_info_into_product", MagicMock()), \
         patch.object(products_mod, "coerce_product_type",
                      side_effect=lambda raw=None, ticker=None, name=None: raw or "outro"):
        result = asyncio.run(products_mod.link_products_and_queue(
            material_id=42, request=_Req(), db=db, current_user=user,
        ))

    assert result.get("success") is True, f"endpoint deveria retornar success=True, veio {result}"
    # A guarda deve ter forçado a criação de um produto NOVO (db.add chamado
    # com um Product), em vez de reusar o ação RAPT4 (id=999).
    assert created_products, "esperava db.add(novo Product), nada foi adicionado"
    new_prod = next((p for p in created_products if isinstance(p, Product)), None)
    assert new_prod is not None, "deveria ter criado um Product novo"
    assert (new_prod.product_type or "").lower() == "estruturada", (
        f"novo produto deveria ser product_type='estruturada', veio {new_prod.product_type!r}"
    )
    # upload_queue.add deve ter sido chamado.
    assert queue_add.called, "upload_queue.add deveria ter sido chamado"
    # E o nome do produto novo deve refletir a estrutura (não o nome da ação).
    assert (new_prod.category or "").lower() in ("estruturada", ""), (
        f"category esperada 'estruturada' (ou vazia), veio {new_prod.category!r}"
    )


# =========================================================================== #
# Camada 3 — Worker: _detect_structure_in_name + _auto_create_product
# =========================================================================== #

def test_detect_structure_via_filename():
    from services.upload_queue import UploadQueue
    assert UploadQueue._detect_structure_in_name(None, None, "POP RAPT4 dez28.pdf") == "pop"
    assert UploadQueue._detect_structure_in_name(None, None, "Collar PETR4.pdf") == "collar"
    assert UploadQueue._detect_structure_in_name(None, None, "Fence VALE3.pdf") == "fence"


def test_detect_structure_via_material_name():
    from services.upload_queue import UploadQueue
    assert UploadQueue._detect_structure_in_name(None, None, None, "POP sobre RAPT4") == "pop"
    # COE deve ser detectado independente da posição.
    assert UploadQueue._detect_structure_in_name(None, None, None, "Nota estruturada COE") == "coe"


def test_detect_structure_via_fund_name_and_doc_type():
    from services.upload_queue import UploadQueue
    assert UploadQueue._detect_structure_in_name("POP sobre VALE3", None) == "pop"
    assert UploadQueue._detect_structure_in_name(None, "Collar 6m PETR4") == "collar"


def test_detect_structure_negative_cases():
    from services.upload_queue import UploadQueue
    # Não deve dar falso positivo em nomes normais.
    assert UploadQueue._detect_structure_in_name("Petrobras PN", "research", "PETR4_research.pdf") is None
    assert UploadQueue._detect_structure_in_name("RAPT4", None, "rapt4_4t25.pdf") is None
    # 'estrutura' / 'estruturado' soltos não disparam (evita falso positivo
    # com "estrutura de capital", "estrutura a termo").
    assert UploadQueue._detect_structure_in_name(
        "Análise da estrutura de capital", None, None
    ) is None


def test_auto_create_product_signature_accepts_filename_hint():
    """Sem filename_hint/material_name na signature, o worker não consegue
    propagar o sinal de estrutura e o fallback por ticker reabre o bug."""
    from services.upload_queue import UploadQueue
    sig = inspect.signature(UploadQueue._auto_create_product)
    assert "filename_hint" in sig.parameters
    assert "material_name" in sig.parameters


def test_auto_create_product_creates_estruturada_when_filename_signals_pop():
    """Behavioral: filename_hint='POP_RAPT4.pdf' + ticker='RAPT4' (já cadastrado
    como ação) → resolver retorna a ação, mas guarda força criação de novo
    Product com product_type='estruturada'."""
    from database.models import Product, ProductStatus
    from services.upload_queue import UploadQueue

    db = _sqlite_session()
    try:
        # Pré-existe a ação RAPT4 no banco.
        existing_acao = Product(
            name="Randon",
            ticker="RAPT4",
            product_type="acao",
            category="acao",
            status=ProductStatus.ACTIVE.value,
            name_aliases="[]",
        )
        db.add(existing_acao)
        db.commit()
        db.refresh(existing_acao)

        # Mocka ProductResolver pra retornar match na ação RAPT4 (cenário do bug).
        from services.product_resolver import ResolverResult

        def _fake_resolve(self, fund_name=None, ticker=None, gestora=None, **kw):
            return ResolverResult(
                matched_product_id=existing_acao.id,
                matched_product_name=existing_acao.name,
                matched_product_ticker=existing_acao.ticker,
                match_type="ticker_exact",
                match_confidence=1.0,
            )

        queue = UploadQueue.__new__(UploadQueue)  # bypass __init__
        with patch("services.product_resolver.ProductResolver.resolve", _fake_resolve):
            new_product = queue._auto_create_product(
                db=db,
                fund_name="POP sobre RAPT4",
                ticker="RAPT4",
                gestora=None,
                document_type=None,
                filename_hint="POP_RAPT4.pdf",
                material_name="POP sobre RAPT4 dez28",
            )

        assert new_product is not None, "deveria ter criado/retornado um produto"
        assert new_product.id != existing_acao.id, (
            f"NÃO deve reaproveitar a ação RAPT4 (id={existing_acao.id}); "
            f"deveria ter criado um produto novo. Got id={new_product.id}"
        )
        assert (new_product.product_type or "").lower() == "estruturada", (
            f"novo produto deveria ser 'estruturada', veio {new_product.product_type!r}"
        )
    finally:
        db.close()


def test_auto_create_product_reuses_existing_estruturada():
    """Quando já existe produto estruturado (ex.: re-upload do mesmo POP),
    o resolver deve reaproveitar — não criar duplicata."""
    from database.models import Product, ProductStatus
    from services.upload_queue import UploadQueue

    db = _sqlite_session()
    try:
        existing_struct = Product(
            name="POP sobre PETR4",
            ticker=None,
            product_type="estruturada",
            category="estruturada",
            status=ProductStatus.ACTIVE.value,
            name_aliases="[]",
        )
        db.add(existing_struct)
        db.commit()
        db.refresh(existing_struct)

        from services.product_resolver import ResolverResult

        def _fake_resolve(self, fund_name=None, ticker=None, gestora=None, **kw):
            return ResolverResult(
                matched_product_id=existing_struct.id,
                matched_product_name=existing_struct.name,
                matched_product_ticker=None,
                match_type="name_exact",
                match_confidence=1.0,
            )

        queue = UploadQueue.__new__(UploadQueue)
        with patch("services.product_resolver.ProductResolver.resolve", _fake_resolve):
            result = queue._auto_create_product(
                db=db,
                fund_name="POP sobre PETR4",
                ticker="PETR4",
                gestora=None,
                document_type=None,
                filename_hint="POP_PETR4.pdf",
                material_name="POP sobre PETR4",
            )

        assert result is not None
        assert result.id == existing_struct.id, (
            "deveria reaproveitar o produto estruturado existente, não criar novo"
        )
    finally:
        db.close()


def test_worker_revalidation_block_present_in_source():
    """Source-level guard para a revalidação de mat.product_id no worker.
    Se alguém remover o bloco, este teste pega antes do bug voltar a produção."""
    src = (ROOT / "services" / "upload_queue.py").read_text(encoding="utf-8")
    assert "[STRUCTURE_GUARD] layer=worker" in src, (
        "worker precisa logar guard estruturado para auditoria"
    )
    assert "preexisting_struct_kw = self._detect_structure_in_name" in src, (
        "worker precisa revalidar mat.product_id contra _detect_structure_in_name"
    )
    assert "mat.product_id = None" in src, (
        "worker precisa zerar mat.product_id quando match é estrutura vs ação"
    )


# =========================================================================== #
# Sanity — script de remediação contra drift de model
# =========================================================================== #

def test_remediation_script_imports_and_uses_correct_model_fields():
    """Smoke test contra drift de campos: o script de remediação referencia
    ProductStatus.ACTIVE e Product.manager (não .gestora). Se o model mudar,
    o script quebra silenciosamente — este teste pega cedo."""
    import importlib
    from database.models import Product, ProductStatus

    mod = importlib.import_module("scripts.fix_misrouted_structure_material")
    assert hasattr(mod, "_find_or_create_structure_product")
    assert hasattr(mod, "_process_material")
    assert hasattr(mod, "_scan_all")
    assert hasattr(ProductStatus, "ACTIVE")
    assert hasattr(Product, "manager"), "Product.manager removido — atualize o script"
    assert not hasattr(Product, "gestora"), (
        "Product.gestora reapareceu — script ainda usa .manager"
    )


# =========================================================================== #
# Suite SWAP — guarda anti-captura para troca/rotação de ativos.
#
# Mesmo padrão da suite de estrutura, mas para o cenário "Trocar PETR4 por
# VALE3.pdf": NÃO devemos vincular o material à ação PETR4 nem à ação VALE3
# já cadastradas — o material descreve UMA operação tática (swap), não duas
# análises individuais. Ele deve ir para um único produto-swap.
# =========================================================================== #


def test_swap_keyword_helper_finds_canonical_terms():
    """Sanity da fonte da verdade compartilhada (services/swap_keywords)."""
    from services.swap_keywords import find_swap_keyword
    assert find_swap_keyword("Troca PETR4 por VALE3") is not None
    assert find_swap_keyword("Sugestão de rotação setorial") is not None
    assert find_swap_keyword("Pair trade entre ITUB4 e BBDC4") is not None
    assert find_swap_keyword("Análise fundamentalista de PETR4") is None
    assert find_swap_keyword(None, None) is None


def test_matcher_rejects_swap_against_acao_via_filename():
    """Filename "Troca PETR4 por VALE3.pdf" + IA disse "Ação" para PETR4 +
    PETR4 ação cadastrada. Deve rejeitar o match para a ação e marcar como
    candidato swap."""
    from api.endpoints.products import _match_products_to_db

    db, _ = _make_db_with_product({
        "id": 555, "ticker": "PETR4", "name": "Petrobras",
        "product_type": "acao", "name_aliases": "[]",
    })
    ai = [{"ticker": "PETR4", "name": "Petrobras", "product_type": "Ação",
           "underlying_ticker": None}]
    res = _match_products_to_db(db, ai, filename="Troca PETR4 por VALE3.pdf")
    assert res, "deve devolver pelo menos 1 candidato"
    # O matcher fez merge pós-processamento ou rejeitou — em ambos os casos
    # o resultado NÃO pode estar vinculado à ação PETR4.
    for entry in res:
        assert not entry.get("exists_in_db"), (
            f"swap NÃO deve vincular à ação PETR4 cadastrada; entry={entry}"
        )
    # Pelo menos um dos resultados deve estar marcado como swap.
    assert any(
        e.get("is_swap_candidate")
        or (e.get("product_type") or "").lower() == "swap"
        for e in res
    ), f"nenhum candidato marcado como swap; res={res}"


def test_matcher_merges_two_acoes_into_one_swap_when_filename_signals_troca():
    """IA devolveu 2 entradas separadas (PETR4 e VALE3) mas filename indica
    troca. O merge pós-processamento deve consolidar em UM produto-swap único
    com underlying_tickers=[PETR4, VALE3]."""
    from api.endpoints.products import _match_products_to_db

    mock_db = MagicMock()
    # Sem produtos pré-existentes — força o caminho "criar novo" para ambos.
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_db.query.return_value.filter.return_value.all.return_value = []

    ai = [
        {"ticker": "PETR4", "name": "Petrobras", "product_type": "Ação"},
        {"ticker": "VALE3", "name": "Vale", "product_type": "Ação"},
    ]
    res = _match_products_to_db(mock_db, ai, filename="Troca PETR4 por VALE3.pdf")
    assert len(res) == 1, (
        f"merge deveria consolidar 2 entradas em 1 produto-swap; got {len(res)}: {res}"
    )
    swap_entry = res[0]
    assert (swap_entry.get("product_type") or "").lower() == "swap", (
        f"produto consolidado deveria ser tipo swap; got {swap_entry.get('product_type')!r}"
    )
    assert swap_entry.get("ticker") is None, (
        f"produto-swap NÃO deve carregar ticker individual; got {swap_entry.get('ticker')!r}"
    )
    ut = swap_entry.get("underlying_tickers") or []
    assert "PETR4" in ut and "VALE3" in ut, (
        f"underlying_tickers deve listar ambos os ativos; got {ut!r}"
    )
    assert swap_entry.get("is_swap_candidate") is True


def test_auto_create_product_creates_swap_without_ticker():
    """Worker behavioral: filename "Troca PETR4 por VALE3.pdf" deve criar
    UM produto-swap com ticker=NULL, mesmo que o resolver tenha matched a
    ação PETR4 (cenário do bug)."""
    from database.models import Product, ProductStatus
    from services.upload_queue import UploadQueue

    db = _sqlite_session()
    try:
        existing_acao = Product(
            name="Petrobras",
            ticker="PETR4",
            product_type="acao",
            category="acao",
            status=ProductStatus.ACTIVE.value,
            name_aliases="[]",
        )
        db.add(existing_acao)
        db.commit()
        db.refresh(existing_acao)

        from services.product_resolver import ResolverResult

        def _fake_resolve(self, fund_name=None, ticker=None, gestora=None, **kw):
            return ResolverResult(
                matched_product_id=existing_acao.id,
                matched_product_name=existing_acao.name,
                matched_product_ticker=existing_acao.ticker,
                match_type="ticker_exact",
                match_confidence=1.0,
            )

        queue = UploadQueue.__new__(UploadQueue)
        with patch("services.product_resolver.ProductResolver.resolve", _fake_resolve):
            new_product = queue._auto_create_product(
                db=db,
                fund_name="Troca PETR4 por VALE3",
                ticker="PETR4",
                gestora=None,
                document_type=None,
                filename_hint="Troca_PETR4_por_VALE3.pdf",
                material_name="Troca PETR4 por VALE3",
            )

        assert new_product is not None
        assert new_product.id != existing_acao.id, (
            "não pode reaproveitar a ação PETR4; deveria ter criado produto-swap novo"
        )
        assert (new_product.product_type or "").lower() == "swap", (
            f"produto deveria ter product_type='swap'; got {new_product.product_type!r}"
        )
        assert new_product.ticker is None, (
            f"produto-swap NÃO deve persistir ticker (evita captura futura); "
            f"got ticker={new_product.ticker!r}"
        )
    finally:
        db.close()


def test_swap_guard_log_present_in_source():
    """Source-level: o log [SWAP_GUARD] precisa existir no worker (auditoria
    paralela ao [STRUCTURE_GUARD]). Pega regressão se alguém remover o bloco."""
    src = (ROOT / "services" / "upload_queue.py").read_text(encoding="utf-8")
    assert "[SWAP_GUARD] layer=worker" in src, (
        "worker precisa logar guard de swap para auditoria/observabilidade"
    )
    src_api = (ROOT / "api" / "endpoints" / "products.py").read_text(encoding="utf-8")
    assert "[SWAP_GUARD] layer=pre_analyze" in src_api, (
        "pre-analyze precisa logar guard de swap"
    )
    assert "[SWAP_GUARD] layer=link_and_queue" in src_api, (
        "link_and_queue precisa logar guard de swap"
    )


# --------------------------------------------------------------------------- #
# Standalone runner (para ambientes sem pytest)
# --------------------------------------------------------------------------- #

def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")
             and isinstance(v, types.FunctionType)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  OK  {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
