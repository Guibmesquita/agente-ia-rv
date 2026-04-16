"""
Serviço de extração GPT para importação automática de recomendações do Comitê a partir de materiais.

Melhorias v2 (Task #105):
- Pré-varredura de tickers do banco para guiar o GPT
- Chunking com sobreposição (12k chars / 1.5k overlap) — sem limite de 30k chars
- Modelo gpt-4o + max_tokens=8000 por chunk
- Prompt ampliado com vocabulário de recomendação expandido
- Deduplicação robusta por ticker após agregação de múltiplos chunks
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Configuração de chunking ───────────────────────────────────────────────────
CHUNK_SIZE = 12_000    # chars por chunk
CHUNK_OVERLAP = 1_500  # chars de sobreposição entre chunks

# ── Padrão de ticker brasileiro/ação (case-insensitive, normalizado em seguida) ──
TICKER_PATTERN = re.compile(r'\b([A-Za-z]{4}\d{1,2})\b')

# ── Prompt do sistema — versão ampliada ───────────────────────────────────────
EXTRACT_SYSTEM_PROMPT = """Você é um analista sênior especializado em extrair recomendações de investimento de relatórios financeiros brasileiros do mercado de capitais.

Sua missão é identificar TODOS os produtos financeiros mencionados neste trecho de documento que possuam qualquer indicação de recomendação, rating ou posicionamento de investimento.

Para cada produto identificado, extraia os seguintes campos:
- ticker: código do ativo (ex: MXRF11, PETR4, HGLG11, ITSA4). Use null se não houver ticker explícito.
- nome: nome completo do fundo ou ativo conforme aparece no documento.
- rating: mapeie para EXATAMENTE um de: "Compra", "Manutenção", "Venda".
  Mapeamentos aceitos:
  - → "Compra": Compra, Buy, Adicionar, Sobreponderar, Overweight, Recomendamos, Reiteramos Compra, Posição, Adicionar à carteira, Recomendação de Compra
  - → "Manutenção": Manutenção, Manter, Hold, Neutro, Neutra, Ponderar, Market Perform, Monitorar, Reiteramos Manutenção
  - → "Venda": Venda, Sell, Reduzir, Subponderar, Underweight, Realizar lucros, Reiteramos Venda
  Se não for possível mapear com segurança, use null (não invente).
- preco_alvo: número do preço-alvo ou valor justo (apenas o número, ex: 12.50). Use null se não mencionado.
- vigencia: data de vigência da recomendação no formato YYYY-MM-DD. Use null se não mencionada.
- racional: resumo da tese de investimento em no máximo 350 caracteres. Use null se não houver.

REGRAS CRÍTICAS:
1. Inclua produtos mesmo que o rating não esteja 100% explícito — se houver linguagem de posicionamento (ex: "reiteramos nossa recomendação", "mantemos posição", "adicionamos à carteira"), extraia com o rating mapeado.
2. Se um produto aparecer sem rating mas com preço-alvo, inclua com rating null.
3. Leia TODAS as tabelas do documento com atenção especial. Tabelas de carteira recomendada geralmente contêm múltiplos produtos em linhas consecutivas — extraia CADA linha como um produto separado.
4. NÃO omita produtos por achá-los já conhecidos ou por aparecerem em tabela compacta.
5. Se o mesmo produto aparecer múltiplas vezes, use a entrada com mais informação.
6. Responda APENAS com JSON válido, sem texto adicional.

Formato de resposta:
{
  "recommendations": [
    {
      "ticker": "MXRF11",
      "nome": "Maxi Renda FII",
      "rating": "Compra",
      "preco_alvo": 12.50,
      "vigencia": "2025-12-31",
      "racional": "FII com DY consistente e gestão ativa. Cota com desconto frente ao VP."
    }
  ]
}
"""


# ── Helpers de extração e chunking ────────────────────────────────────────────

def _extract_text_from_blocks(blocks) -> str:
    """
    Concatena o conteúdo dos ContentBlocks em texto plano.
    Tabelas JSON (headers+rows) são convertidas para formato legível pelo GPT.
    """
    parts = []
    for block in blocks:
        if not block.content:
            continue
        content = block.content.strip()
        if not content:
            continue

        is_table_block = block.block_type in ('table', 'tabular', 'tabela')
        looks_like_json = content.startswith('{') or content.startswith('[')

        if is_table_block or looks_like_json:
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and 'headers' in parsed and 'rows' in parsed:
                    headers = parsed.get('headers', [])
                    rows = parsed.get('rows', [])
                    lines = ['TABELA: ' + ' | '.join(str(h) for h in headers)]
                    for row in rows:
                        if isinstance(row, list):
                            lines.append(' | '.join(str(v) for v in row))
                        elif isinstance(row, dict):
                            lines.append(' | '.join(str(v) for v in row.values()))
                    content = '\n'.join(lines)
            except (json.JSONDecodeError, TypeError):
                pass

        if block.title:
            parts.append(f"[{block.title}]\n{content}")
        else:
            parts.append(content)

    return '\n\n'.join(parts)


def _split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Divide o texto em chunks com sobreposição para não perder informações no limite.
    Tenta quebrar em parágrafos (\\n\\n) quando possível para não cortar no meio de uma frase.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end >= len(text):
            chunks.append(text[start:])
            break

        # Tenta quebrar no parágrafo mais próximo antes do fim do chunk
        break_pos = text.rfind('\n\n', start, end)
        if break_pos == -1 or break_pos <= start + chunk_size // 2:
            # Sem parágrafo bom — quebra na última quebra de linha
            break_pos = text.rfind('\n', start, end)
        if break_pos == -1 or break_pos <= start + chunk_size // 2:
            # Sem quebra de linha — corta no limite mesmo
            break_pos = end

        chunks.append(text[start:break_pos])
        start = max(start + 1, break_pos - overlap)

    return chunks


def _scan_tickers_in_db(db: Session, text: str) -> Dict[str, Any]:
    """
    Varredura regex no texto completo para identificar tickers que existem no banco.
    Normaliza todos os matches para MAIÚSCULAS antes da consulta (suporta OCR misto).
    Retorna dict {ticker_upper: product} para uso como hint e lookup.
    """
    from database.models import Product

    # Normaliza para maiúsculas para lidar com OCR que retorna "mxrf11" ou "Mxrf11"
    raw_tickers = set(t.upper() for t in TICKER_PATTERN.findall(text))
    if not raw_tickers:
        return {}

    products = db.query(Product).filter(
        Product.ticker.in_(list(raw_tickers)),
        Product.status == 'ativo'
    ).all()

    return {p.ticker.upper(): p for p in products if p.ticker}


def _call_gpt_for_chunk(client, chunk_text: str, ticker_hint: str) -> tuple[List[Dict], bool]:
    """
    Envia um chunk de texto ao GPT-4o e retorna (lista_de_recomendações, sucesso).
    Retorna ([], False) em caso de erro, para que o chamador possa contabilizar falhas.
    """
    user_content = ""
    if ticker_hint:
        user_content += (
            "ATENÇÃO — Os seguintes tickers foram identificados neste documento E existem "
            "em nossa base de dados. Certifique-se de extrair a recomendação de CADA UM "
            f"deles se estiverem neste trecho:\n{ticker_hint}\n\n"
        )
    user_content += f"Trecho do documento:\n\n{chunk_text}"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=8000,
        )
        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        return parsed.get("recommendations", []), True
    except json.JSONDecodeError as e:
        logger.warning(f"[committee_importer] Chunk retornou JSON inválido: {e}")
        return [], False
    except Exception as e:
        logger.error(f"[committee_importer] Erro GPT no chunk: {e}")
        return [], False


def _merge_raw_recommendations(raw_list: List[Dict]) -> List[Dict]:
    """
    Agrega recomendações de múltiplos chunks, deduplicando por ticker.
    Mantém a entrada com mais campos preenchidos para cada ticker.
    Entradas sem ticker são agrupadas por nome normalizado.
    """
    by_ticker: Dict[str, Dict] = {}
    by_name: Dict[str, Dict] = {}

    def _score(rec: Dict) -> int:
        return sum(1 for k in ('rating', 'preco_alvo', 'vigencia', 'racional') if rec.get(k) is not None)

    for rec in raw_list:
        ticker = (rec.get("ticker") or "").strip().upper() or None
        nome_raw = rec.get("nome") or ""
        nome_key = nome_raw.strip().lower()

        if ticker:
            existing = by_ticker.get(ticker)
            if existing is None or _score(rec) > _score(existing):
                by_ticker[ticker] = rec
        elif nome_key and len(nome_key) >= 3:
            existing = by_name.get(nome_key)
            if existing is None or _score(rec) > _score(existing):
                by_name[nome_key] = rec

    return list(by_ticker.values()) + list(by_name.values())


# ── Resolução de produto ───────────────────────────────────────────────────────

def _resolve_product(db: Session, ticker: Optional[str], nome: Optional[str], db_ticker_map: Dict[str, Any] = None):
    """
    Resolve um produto identificado pelo GPT para um registro na tabela products.
    Prioridade: hint map (ticker pré-varrido) → ticker ILIKE → name ILIKE → alias.
    Retorna (product, match_type) ou (None, None).
    """
    from database.models import Product

    if ticker:
        ticker_clean = ticker.strip().upper()

        # 1. Hint map (mais rápido — já pré-varrido no início)
        if db_ticker_map and ticker_clean in db_ticker_map:
            return db_ticker_map[ticker_clean], 'ticker_hint'

        # 2. Busca ILIKE no banco
        p = db.query(Product).filter(
            Product.ticker.ilike(ticker_clean),
            Product.status == 'ativo'
        ).first()
        if p:
            return p, 'ticker_exact'

    if nome and len(nome.strip()) >= 3:
        nome_clean = nome.strip()

        # 3. Name ILIKE
        p = db.query(Product).filter(
            Product.name.ilike(f"%{nome_clean}%"),
            Product.status == 'ativo'
        ).first()
        if p:
            return p, 'name_ilike'

        # 4. Alias match
        all_products = db.query(Product).filter(Product.status == 'ativo').all()
        nome_lower = nome_clean.lower()
        for prod in all_products:
            try:
                aliases = json.loads(prod.name_aliases or "[]")
            except (json.JSONDecodeError, TypeError):
                aliases = []
            for alias in aliases:
                if nome_lower in alias.lower() or alias.lower() in nome_lower:
                    return prod, 'alias'

    return None, None


# ── Função principal ───────────────────────────────────────────────────────────

def extract_committee_from_material(db: Session, material_id: int) -> list:
    """
    Extrai recomendações do Comitê de um material pelo ID.

    Pipeline v2:
    1. Lê todos os ContentBlocks e monta texto completo (sem limite de chars)
    2. Varre tickers no texto e compara com o banco (hint para o GPT)
    3. Divide o texto em chunks de ~12k chars com sobreposição de ~1.5k
    4. Processa cada chunk via gpt-4o (max_tokens=8000)
    5. Agrega e deduplica resultados de todos os chunks
    6. Resolve cada produto extraído para registro no banco
    7. Sinaliza produtos já no Comitê ativo

    Returns:
        Lista de dicts com: ticker, nome, rating, target_price, valid_until,
        rationale, product_id, product_name, product_ticker, unresolved,
        already_in_committee, match_type
    """
    from database.models import Material, ContentBlock, RecommendationEntry
    from openai import OpenAI
    import os

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise ValueError(f"Material id={material_id} não encontrado")

    blocks = db.query(ContentBlock).filter(
        ContentBlock.material_id == material_id
    ).order_by(ContentBlock.order, ContentBlock.id).all()

    if not blocks:
        logger.info(f"[committee_importer] Material {material_id} não tem ContentBlocks extraídos")
        return []

    full_text = _extract_text_from_blocks(blocks)

    if not full_text.strip():
        return []

    # ── Pré-varredura de tickers ─────────────────────────────────────────────
    db_ticker_map = _scan_tickers_in_db(db, full_text)
    ticker_hint = ""
    if db_ticker_map:
        ticker_hint = ", ".join(sorted(db_ticker_map.keys()))
        logger.info(f"[committee_importer] Tickers da base identificados no documento: {ticker_hint}")

    # ── Chunking ─────────────────────────────────────────────────────────────
    chunks = _split_into_chunks(full_text)
    total_chars = len(full_text)
    logger.info(
        f"[committee_importer] Material {material_id}: {total_chars} chars → {len(chunks)} chunk(s) "
        f"({len(db_ticker_map)} tickers da base identificados)"
    )

    # ── Chamadas GPT por chunk ────────────────────────────────────────────────
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não configurada")

    client = OpenAI(api_key=api_key)

    all_raw: List[Dict] = []
    failed_chunks = 0

    for idx, chunk in enumerate(chunks):
        logger.info(f"[committee_importer] Processando chunk {idx + 1}/{len(chunks)} ({len(chunk)} chars)")
        raw, ok = _call_gpt_for_chunk(client, chunk, ticker_hint)
        if ok:
            logger.info(f"[committee_importer] Chunk {idx + 1}: {len(raw)} item(s) extraído(s)")
            all_raw.extend(raw)
        else:
            failed_chunks += 1
            logger.warning(f"[committee_importer] Chunk {idx + 1} falhou (total de falhas: {failed_chunks}/{len(chunks)})")

    if failed_chunks == len(chunks):
        raise RuntimeError(
            f"Todos os {len(chunks)} chunks falharam ao chamar o GPT. Verifique a chave de API e os logs."
        )
    if failed_chunks > 0:
        logger.warning(
            f"[committee_importer] {failed_chunks}/{len(chunks)} chunk(s) falharam — resultado pode estar incompleto"
        )

    # ── Agregação e deduplicação ──────────────────────────────────────────────
    merged = _merge_raw_recommendations(all_raw)
    logger.info(
        f"[committee_importer] Total bruto: {len(all_raw)} → após dedup: {len(merged)}"
    )

    # ── Resolução no banco + enriquecimento ───────────────────────────────────
    now = datetime.utcnow()
    result = []
    seen_product_ids = set()

    for rec in merged:
        ticker = rec.get("ticker") or None
        nome = rec.get("nome") or None
        rating_raw = rec.get("rating") or None
        preco_alvo_raw = rec.get("preco_alvo")
        vigencia_raw = rec.get("vigencia")
        racional = rec.get("racional") or None

        if not ticker and not nome:
            continue

        # Normaliza ticker (remove espaços)
        if ticker:
            ticker = re.sub(r'\s+', '', ticker.strip().upper())

        # Valida rating
        rating = None
        if rating_raw and rating_raw in ("Compra", "Manutenção", "Venda"):
            rating = rating_raw

        # Normaliza preço-alvo
        target_price = None
        if preco_alvo_raw is not None:
            try:
                target_price = float(str(preco_alvo_raw).replace(',', '.').replace('R$', '').strip())
            except (ValueError, TypeError):
                pass

        # Normaliza vigência
        valid_until = None
        if vigencia_raw:
            try:
                valid_until = datetime.strptime(str(vigencia_raw)[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        # Resolve produto no banco
        product, match_type = _resolve_product(db, ticker, nome, db_ticker_map)

        # Deduplica por product_id (mantém o primeiro ocorrido, que já é o de maior score)
        if product and product.id in seen_product_ids:
            continue
        if product:
            seen_product_ids.add(product.id)

        # Verifica se já está no Comitê ativo
        already_in_committee = False
        if product:
            active_entry = db.query(RecommendationEntry).filter(
                RecommendationEntry.product_id == product.id,
                RecommendationEntry.is_active == True,
            ).filter(
                (RecommendationEntry.valid_until == None) |
                (RecommendationEntry.valid_until >= now)
            ).first()
            already_in_committee = active_entry is not None

        result.append({
            "ticker": ticker,
            "nome": nome,
            "rating": rating,
            "target_price": target_price,
            "valid_until": valid_until.isoformat() if valid_until else None,
            "rationale": racional,
            "product_id": product.id if product else None,
            "product_name": product.name if product else None,
            "product_ticker": product.ticker if product else None,
            "unresolved": product is None,
            "already_in_committee": already_in_committee,
            "match_type": match_type,
        })

    resolved_count = sum(1 for r in result if not r['unresolved'])
    logger.info(
        f"[committee_importer] Material {material_id}: {len(result)} recomendações finais "
        f"({resolved_count} resolvidas, {len(result) - resolved_count} não cadastradas)"
    )
    return result
