"""Sanity tests para a guarda anti-captura de estrutura (Task #164).

Cobre as 3 camadas:
  1. _match_products_to_db (pre-analyze) — rejeita match de candidato estrutura
     contra produto-ação cadastrado, com ou sem product_type vindo da IA.
  2. _detect_structure_in_name (worker/script) — detecta via filename, material.name,
     fund_name e document_type.
  3. _auto_create_product (worker) — aceita filename_hint/material_name na
     signature para propagar sinal de estrutura.

Roda standalone: `python tests/test_structure_guard.py` ou via pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_db_with_product(product_attrs: dict) -> MagicMock:
    """Mock de Session que retorna um único Product no .first() e [] em .all()."""
    mock_product = MagicMock()
    for k, v in product_attrs.items():
        setattr(mock_product, k, v)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_product
    mock_db.query.return_value.filter.return_value.all.return_value = []
    return mock_db, mock_product


# ---------- Camada 1: _match_products_to_db ---------- #

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
    print("  OK matcher_rejects_structure_against_acao_via_filename")


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
    print("  OK matcher_rejects_structure_via_underlying_ticker")


def test_matcher_keeps_match_when_both_are_structure():
    """Quando candidato é estrutura e produto cadastrado também é estrutura,
    o match deve ser aceito (caso normal — re-upload de POP existente)."""
    from api.endpoints.products import _match_products_to_db

    db, _ = _make_db_with_product({
        "id": 2002, "ticker": None, "name": "POP sobre PETR4",
        "product_type": "estruturada", "name_aliases": "[]",
    })
    ai = [{"ticker": None, "name": "POP sobre PETR4",
           "product_type": "Estruturada", "underlying_ticker": "PETR4"}]
    res = _match_products_to_db(db, ai, filename="POP PETR4.pdf")
    # Aqui é OK casar; o ponto é que NÃO rejeite por ser estrutura vs estrutura.
    assert res[0]["is_structure_candidate"] is True
    # Não checamos exists_in_db=True porque o mock não cobre todo o lookup,
    # mas garantimos que rejected_match_reason está vazio.
    assert not res[0].get("rejected_match_reason"), (
        "não deve rejeitar quando ambos são estrutura"
    )
    print("  OK matcher_keeps_match_when_both_are_structure")


# ---------- Camada 2: _detect_structure_in_name ---------- #

def test_detect_structure_via_filename():
    from services.upload_queue import UploadQueue
    assert UploadQueue._detect_structure_in_name(None, None, "POP RAPT4 dez28.pdf") == "pop"
    assert UploadQueue._detect_structure_in_name(None, None, "Collar PETR4.pdf") == "collar"
    assert UploadQueue._detect_structure_in_name(None, None, "Fence VALE3.pdf") == "fence"
    print("  OK detect_structure_via_filename")


def test_detect_structure_via_material_name():
    from services.upload_queue import UploadQueue
    assert UploadQueue._detect_structure_in_name(None, None, None, "POP sobre RAPT4") == "pop"
    assert UploadQueue._detect_structure_in_name(None, None, None, "Estrutura COE") == "coe"
    print("  OK detect_structure_via_material_name")


def test_detect_structure_via_fund_name_and_doc_type():
    from services.upload_queue import UploadQueue
    assert UploadQueue._detect_structure_in_name("POP sobre VALE3", None) == "pop"
    assert UploadQueue._detect_structure_in_name(None, "Collar 6m PETR4") == "collar"
    print("  OK detect_structure_via_fund_name_and_doc_type")


def test_detect_structure_negative_cases():
    from services.upload_queue import UploadQueue
    # Não deve dar falso positivo em nomes normais.
    assert UploadQueue._detect_structure_in_name("Petrobras PN", "research", "PETR4_research.pdf") is None
    assert UploadQueue._detect_structure_in_name("RAPT4", None, "rapt4_4t25.pdf") is None
    print("  OK detect_structure_negative_cases")


# ---------- Camada 3: _auto_create_product signature ---------- #

def test_auto_create_product_accepts_filename_hint():
    """Sem isso, o worker não consegue propagar o sinal de estrutura via filename
    e o fallback por ticker reabre o bug."""
    import inspect
    from services.upload_queue import UploadQueue
    sig = inspect.signature(UploadQueue._auto_create_product)
    assert "filename_hint" in sig.parameters
    assert "material_name" in sig.parameters
    print("  OK auto_create_product_accepts_filename_hint")


# ---------- Camada link-and-queue: força product_type=estruturada ---------- #

def test_link_and_queue_force_estruturada_in_source():
    """Verifica via leitura do source que `link_products_and_queue` força
    product_type_db='estruturada' quando cp_is_structure_flag é True."""
    src = (ROOT / "api" / "endpoints" / "products.py").read_text(encoding="utf-8")
    assert "if cp_is_structure_flag and product_type_db != \"estruturada\"" in src, (
        "link_and_queue precisa coercir product_type para 'estruturada' "
        "quando candidato é estrutura"
    )
    assert "force_create_as_estruturada" in src, (
        "deve logar a coerção para auditoria"
    )
    print("  OK link_and_queue_force_estruturada_in_source")


def main() -> int:
    tests = [
        test_matcher_rejects_structure_against_acao_via_filename,
        test_matcher_rejects_structure_via_underlying_ticker,
        test_matcher_keeps_match_when_both_are_structure,
        test_detect_structure_via_filename,
        test_detect_structure_via_material_name,
        test_detect_structure_via_fund_name_and_doc_type,
        test_detect_structure_negative_cases,
        test_auto_create_product_accepts_filename_hint,
        test_link_and_queue_force_estruturada_in_source,
    ]
    failed = 0
    for t in tests:
        try:
            t()
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
