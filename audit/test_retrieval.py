"""
PHASE 2 — RETRIEVAL QUALITY TESTS
Chama EnhancedSearch.search() diretamente para isolar a qualidade
de retrieval da geração. Não modifica nenhum dado.
"""
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.database import SessionLocal
from services.semantic_search import EnhancedSearch, EntityResolver
from services.openai_agent import get_vector_store
from audit.fact_bank import FACT_BANK


def chunk_contains_fact(chunk_content: str, fact_keywords: list) -> bool:
    """Considera que um chunk 'contém' o fato se cobre >=60% das keywords (case-insensitive)."""
    txt = (chunk_content or "").lower()
    hits = sum(1 for k in fact_keywords if k.lower() in txt)
    return hits / max(1, len(fact_keywords)) >= 0.6


def fact_keywords(fact_id: str, fact_text: str, ticker: str | None) -> list:
    """Extrai âncoras de matching para um fato."""
    base = {
        "BTLG_DY":   ["9,2", "dividend"],
        "BTLG_VAC":  ["2,9", "vacância"],
        "BTLG_LTV":  ["3,3", "ltv"],
        "BTLG_LOG":  ["95%", "logístic"],
        "BTLG_CRI":  ["5,90", "ipca", "cri"],
        "BTLG_TAXA": ["0,90", "administra"],
        "GARE_GUID": ["0,083", "0,090", "guidance"],
        "GARE_COTA": ["9,24", "novembro"],
        "GARE_XPRI": ["xpri", "145", "356"],
        "MANA_DY":   ["15,2", "dividend"],
        "MANA_RENT": ["37,4", "ifix"],
        "MANA_DIV":  ["0,11", "1,30"],
        "MANA_COTI": ["34.3", "cotistas"],
    }
    return base.get(fact_id, [ticker.lower()] if ticker else [])


def run_phase_2_1(es: EnhancedSearch, db) -> dict:
    """2.1 — Direct fact retrieval tests."""
    results_per_fact = []
    layer_counter = defaultdict(int)
    rrs = []  # reciprocal ranks

    for fact in FACT_BANK:
        if fact["block_id"] is None:  # skip negatives/comparatives here
            continue
        kws = fact_keywords(fact["id"], fact["fact"], fact["ticker"])
        for variant_label, query in fact["queries"]:
            t0 = time.time()
            try:
                results = es.search(query=query, n_results=8, similarity_threshold=0.3, db=db)
            except Exception as e:
                results_per_fact.append({
                    "fact_id": fact["id"], "variant": variant_label, "query": query,
                    "error": str(e), "found": False,
                })
                continue
            elapsed = (time.time() - t0) * 1000

            found_rank = None
            found_score = None
            top_score = results[0].composite_score if results else None
            top_content_preview = (results[0].content[:120] if results else "")

            for idx, r in enumerate(results, 1):
                if chunk_contains_fact(r.content, kws):
                    found_rank = idx
                    found_score = r.composite_score
                    break

            if found_rank:
                rrs.append(1.0 / found_rank)
                layer_counter["found"] += 1
            else:
                rrs.append(0.0)
                layer_counter["miss"] += 1

            results_per_fact.append({
                "fact_id": fact["id"],
                "ticker": fact["ticker"],
                "block_type": fact["block_type"],
                "category": fact["category"],
                "variant": variant_label,
                "query": query,
                "n_returned": len(results),
                "found_rank": found_rank,
                "found_score": round(found_score, 3) if found_score else None,
                "top_score": round(top_score, 3) if top_score else None,
                "top_preview": top_content_preview,
                "elapsed_ms": round(elapsed),
            })

    found = sum(1 for r in results_per_fact if r.get("found_rank"))
    total = len(results_per_fact)
    recall_at_3 = sum(1 for r in results_per_fact if r.get("found_rank") and r["found_rank"] <= 3) / max(1, total)
    recall_at_6 = sum(1 for r in results_per_fact if r.get("found_rank") and r["found_rank"] <= 6) / max(1, total)
    mrr = sum(rrs) / max(1, len(rrs))

    return {
        "total_queries": total,
        "found": found,
        "miss": total - found,
        "recall@3": round(recall_at_3, 3),
        "recall@6": round(recall_at_6, 3),
        "mrr": round(mrr, 3),
        "details": results_per_fact,
    }


def run_phase_2_3(db) -> dict:
    """2.3 — Entity resolution tests."""
    cases = [
        ("exact_ticker", "BTLG11"),
        ("informal_name", "TG Renda"),
        ("partial_ticker", "MANA"),
        ("gestora", "BTG Pactual"),
        ("unknown", "XPTO99"),
        ("ambiguous", "fundo"),
        ("multi_entity", "compare BTLG11 com MANA11"),
    ]
    out = []
    for label, q in cases:
        t0 = time.time()
        try:
            resolved = EntityResolver.resolve(q, db=db)
        except Exception as e:
            out.append({"case": label, "query": q, "error": str(e)})
            continue
        elapsed_ms = round((time.time() - t0) * 1000)
        out.append({
            "case": label, "query": q,
            "resolved_count": len(resolved),
            "resolved": [{"name": p.get("name"), "ticker": p.get("ticker"),
                          "confidence": p.get("confidence"),
                          "match_type": p.get("match_type")} for p in resolved[:5]],
            "elapsed_ms": elapsed_ms,
        })
    return {"cases": out}


def run_phase_2_2_chunking(db) -> dict:
    """2.2 — Chunking quality (length distribution + tabela block sample retrieval)."""
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT material_id, block_type, LENGTH(content) AS clen
        FROM content_blocks
        WHERE material_id IN (26, 28, 36, 32, 39)
    """)).fetchall()
    by_mat = defaultdict(lambda: {"counts": defaultdict(int), "lens": []})
    for r in rows:
        by_mat[r[0]]["counts"][r[1]] += 1
        by_mat[r[0]]["lens"].append(r[2])
    summary = {}
    for mid, d in by_mat.items():
        lens = d["lens"]
        summary[str(mid)] = {
            "blocks_total": len(lens),
            "by_type": dict(d["counts"]),
            "len_min": min(lens), "len_max": max(lens),
            "len_avg": round(sum(lens) / len(lens)),
            "len_under_100": sum(1 for x in lens if x < 100),
            "len_over_2000": sum(1 for x in lens if x > 2000),
        }
    return summary


def main():
    db = SessionLocal()
    vs = get_vector_store()
    es = EnhancedSearch(vs)
    out = {}
    print("[2.1] Direct fact retrieval...")
    out["phase_2_1_retrieval"] = run_phase_2_1(es, db)
    print(f"   recall@3={out['phase_2_1_retrieval']['recall@3']}  "
          f"recall@6={out['phase_2_1_retrieval']['recall@6']}  "
          f"MRR={out['phase_2_1_retrieval']['mrr']}")
    print("[2.2] Chunking quality...")
    out["phase_2_2_chunking"] = run_phase_2_2_chunking(db)
    print("[2.3] Entity resolution...")
    out["phase_2_3_entity"] = run_phase_2_3(db)
    db.close()

    Path("audit/results").mkdir(parents=True, exist_ok=True)
    with open("audit/results/phase_2.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Wrote audit/results/phase_2.json")


if __name__ == "__main__":
    main()
