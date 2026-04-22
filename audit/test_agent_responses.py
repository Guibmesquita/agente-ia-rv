"""
PHASE 3 — FULL AGENT RESPONSE QUALITY TESTS (subset)
Chama generate_response_v2() programaticamente. Não envia WhatsApp.
Subset reduzido para controlar custo OpenAI durante a auditoria.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.database import SessionLocal
from services.openai_agent import OpenAIAgent

QUESTIONS = [
    # 3.1 — KB questions (numeric / thesis / risk / table / chart)
    {"id": "KB_NUM_DY",      "category": "kb_numeric",      "q": "qual o dividend yield do BTLG11?"},
    {"id": "KB_NUM_GARE_GUID","category": "kb_numeric",     "q": "qual o guidance de dividendos do GARE11?"},
    {"id": "KB_THESIS_MANA", "category": "kb_thesis",       "q": "qual a tese de investimento do MANA11?"},
    {"id": "KB_RISK_BTLG",   "category": "kb_risk",         "q": "quais os riscos do BTLG11?"},
    {"id": "KB_COMPARE",     "category": "kb_comparative",  "q": "compara BTLG11 com MANA11 — qual tem melhor DY?"},
    {"id": "KB_TABLE_CRI",   "category": "kb_table",        "q": "qual a taxa do CRI II do BTLG11?"},

    # 3.2 — Web search
    {"id": "WEB_PRICE",      "category": "web_quote",       "q": "qual a cotação atual do BTLG11?"},
    {"id": "WEB_FII_PUB",    "category": "web_fii_public",  "q": "qual o DY atual do BTLG11 segundo a FundsExplorer?"},

    # 3.3 — Hybrid
    {"id": "HYB_BTLG",       "category": "hybrid",          "q": "vale a pena comprar BTLG11 agora? me dá a tese e o DY atual"},

    # 3.4 — Edge
    {"id": "EDGE_NEG",       "category": "edge_no_data",    "q": "me fala do TEST11"},
    {"id": "EDGE_XPTO",      "category": "edge_unknown",    "q": "me fala do XPTO99"},
    {"id": "EDGE_BROAD",     "category": "edge_broad",      "q": "me compara todos os FIIs da carteira"},
]

async def run_one(agent, db, q_obj):
    t0 = time.time()
    try:
        text, should_ticket, ctx = await agent.generate_response_v2(
            user_message=q_obj["q"],
            conversation_history=[],
            sender_phone="+5500000000000",
            identified_assessor=None,
            db=db,
            conversation_id=f"audit-{q_obj['id']}",
            allow_tools=True,
        )
        elapsed = round((time.time() - t0) * 1000)
        return {
            "id": q_obj["id"], "category": q_obj["category"], "query": q_obj["q"],
            "elapsed_ms": elapsed, "ticket": bool(should_ticket),
            "response": text,
            "context_keys": list((ctx or {}).keys()) if isinstance(ctx, dict) else None,
            "tools_used": (ctx or {}).get("tools_used") if isinstance(ctx, dict) else None,
        }
    except Exception as e:
        return {"id": q_obj["id"], "category": q_obj["category"], "query": q_obj["q"],
                "error": f"{type(e).__name__}: {e}"}

async def main():
    db = SessionLocal()
    agent = OpenAIAgent()
    out = []
    for q in QUESTIONS:
        print(f"[{q['id']}] {q['q']}")
        r = await run_one(agent, db, q)
        out.append(r)
        if "error" in r:
            print(f"   ERROR: {r['error']}")
        else:
            print(f"   {r['elapsed_ms']}ms | tools={r.get('tools_used')} | resp[:120]={r['response'][:120]!r}")
    db.close()
    Path("audit/results").mkdir(parents=True, exist_ok=True)
    with open("audit/results/phase_3.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Wrote audit/results/phase_3.json")

if __name__ == "__main__":
    asyncio.run(main())
