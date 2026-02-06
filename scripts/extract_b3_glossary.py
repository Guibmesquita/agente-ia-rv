#!/usr/bin/env python3
"""
Script para extrair termos do glossário B3 (Bora Investir) e adicionar
ao arquivo services/financial_concepts.py como novos conceitos.

Inclui sanitização automática:
- Remove abreviações malformadas (parênteses quebrados)
- Remove abreviações de 1-2 caracteres (muito ambíguas)
- Extrai siglas standalone de padrões "Nome (SIGLA)"
- Evita duplicatas semânticas com conceitos existentes
"""

import asyncio
import re
import sys
import unicodedata
from pathlib import Path

import httpx

BASE_URL = "https://borainvestir.b3.com.br/glossario/letra/{letter}/"
PAGE_URL = "https://borainvestir.b3.com.br/glossario/letra/{letter}/page/{page}/"
LETTERS = "abcdefghijklmnopqrstuvwxyz"

FINANCIAL_CONCEPTS_PATH = Path(__file__).parent.parent / "services" / "financial_concepts.py"


def to_snake_case(text: str) -> str:
    nfkd = unicodedata.normalize('NFKD', text)
    ascii_text = nfkd.encode('ascii', 'ignore').decode('ascii')
    ascii_text = re.sub(r'[^a-zA-Z0-9\s]', '', ascii_text)
    ascii_text = re.sub(r'\s+', '_', ascii_text.strip())
    return ascii_text.lower()


def extract_terms_from_html(html: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r'<p class="card-glossary__title">(.*?)</p>\s*(.*?)\s*<p class="card-glossary__footer">',
        re.DOTALL
    )
    terms = []
    for match in pattern.finditer(html):
        name = match.group(1).strip()
        description = match.group(2).strip()
        description = re.sub(r'<[^>]+>', '', description).strip()
        description = re.sub(r'\s+', ' ', description)
        if name and description:
            terms.append((name, description))
    return terms


def has_next_page(html: str, letter: str, current_page: int) -> bool:
    next_page = current_page + 1
    return f'/glossario/letra/{letter}/page/{next_page}/' in html


async def fetch_letter(client: httpx.AsyncClient, letter: str) -> list[tuple[str, str]]:
    all_terms = []
    page = 1

    while True:
        if page == 1:
            url = BASE_URL.format(letter=letter)
        else:
            url = PAGE_URL.format(letter=letter, page=page)

        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            break
        except httpx.RequestError as e:
            print(f"  Erro ao acessar {url}: {e}")
            break

        html = resp.text
        terms = extract_terms_from_html(html)
        if not terms:
            break

        all_terms.extend(terms)

        if has_next_page(html, letter, page):
            page += 1
        else:
            break

    return all_terms


def get_existing_terms() -> set[str]:
    sys.path.insert(0, str(FINANCIAL_CONCEPTS_PATH.parent.parent))
    from services.financial_concepts import FINANCIAL_CONCEPTS

    existing = set()
    for concept in FINANCIAL_CONCEPTS:
        existing.add(concept['id'].lower().strip())
        for term in concept.get("termos_usuario", []):
            existing.add(term.lower().strip())
        for term in concept.get("termos_busca", []):
            existing.add(term.lower().strip())
    return existing


def generate_search_terms(name: str, description: str) -> list[str]:
    stop_words = {
        'a', 'o', 'e', 'é', 'de', 'do', 'da', 'dos', 'das', 'em', 'no', 'na',
        'nos', 'nas', 'um', 'uma', 'uns', 'umas', 'por', 'para', 'com', 'sem',
        'que', 'se', 'ou', 'ao', 'aos', 'à', 'às', 'sua', 'seu', 'seus', 'suas',
        'como', 'mais', 'mas', 'entre', 'sobre', 'já', 'são', 'ser', 'ter',
        'foi', 'tem', 'há', 'não', 'nos', 'pode', 'este', 'essa', 'esse',
        'esta', 'isso', 'isto', 'aqui', 'ali', 'pela', 'pelo', 'pelos', 'pelas',
        'ele', 'ela', 'eles', 'elas', 'muito', 'também', 'quando', 'onde',
        'qual', 'quais', 'todo', 'toda', 'todos', 'todas', 'cada', 'outro',
        'outra', 'outros', 'outras', 'mesmo', 'mesma', 'ainda', 'até',
        'após', 'antes', 'só', 'sob', 'parte', 'forma', 'tipo', 'caso',
        'vez', 'vezes', 'dia', 'ano', 'exemplo',
    }
    words = re.findall(r'[a-záàâãéèêíïóôõúüç]+', description.lower())
    significant = []
    seen = set()
    for w in words:
        if len(w) > 3 and w not in stop_words and w not in seen:
            seen.add(w)
            significant.append(w)
        if len(significant) >= 6:
            break

    name_words = re.findall(r'[a-záàâãéèêíïóôõúüç]+', name.lower())
    for w in name_words:
        if w not in seen and len(w) > 2:
            significant.insert(0, w)
            seen.add(w)

    return significant[:8]


def sanitize_term(term: str) -> bool:
    """Retorna True se o termo é válido, False se deve ser removido."""
    if not term or len(term.strip()) <= 1:
        return False
    if len(term) <= 2 and term.isupper():
        return False
    if re.search(r'[A-Za-zÀ-ú&;]\(', term) and not re.search(r'\s\(', term):
        return False
    if term.count('(') != term.count(')'):
        return False
    if re.search(r'&#\d+;', term):
        return False
    return True


def generate_user_terms(name: str) -> list[str]:
    """Gera termos de busca do usuário com sanitização e extração de siglas."""
    raw_terms = [name]

    lower = name.lower()
    if lower != name:
        raw_terms.append(lower)

    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = nfkd.encode('ascii', 'ignore').decode('ascii')
    if ascii_name != name and ascii_name:
        raw_terms.append(ascii_name)

    abbrev_match = re.match(r'^(.+?)\s+\(([A-Za-zÀ-ú\-\s,]+)\)$', name)
    if abbrev_match:
        full_name = abbrev_match.group(1).strip()
        abbreviation = abbrev_match.group(2).strip()
        if len(abbreviation) >= 3:
            raw_terms.append(abbreviation)
        if len(full_name) >= 3:
            raw_terms.append(full_name)
            full_lower = full_name.lower()
            if full_lower != full_name:
                raw_terms.append(full_lower)
            full_ascii = unicodedata.normalize('NFKD', full_name).encode('ascii', 'ignore').decode('ascii')
            if full_ascii != full_name and full_ascii:
                raw_terms.append(full_ascii)
    else:
        words = name.split()
        if len(words) > 1:
            initials = ''.join(w[0].upper() for w in words if len(w) > 2)
            if len(initials) >= 3:
                raw_terms.append(initials)

    seen = set()
    unique = []
    for t in raw_terms:
        if not sanitize_term(t):
            continue
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            unique.append(t)

    return unique


def generate_concept_entry(name: str, description: str, concept_id: str) -> str:
    user_terms = generate_user_terms(name)
    search_terms = generate_search_terms(name, description)

    desc_escaped = description.replace('\\', '\\\\').replace('"', '\\"')

    user_terms_str = ', '.join(f'"{t}"' for t in user_terms)
    search_terms_str = ', '.join(f'"{t}"' for t in search_terms)

    return (
        f'    {{\n'
        f'        "id": "{concept_id}",\n'
        f'        "categoria": "GLOSSARIO_B3",\n'
        f'        "termos_usuario": [{user_terms_str}],\n'
        f'        "termos_busca": [{search_terms_str}],\n'
        f'        "descricao": "{desc_escaped}",\n'
        f'        "temas_relacionados": []\n'
        f'    }}'
    )


def write_concepts_to_file(new_concepts: list[str]):
    content = FINANCIAL_CONCEPTS_PATH.read_text(encoding='utf-8')

    closing_pattern = re.compile(r'^(\])\s*$', re.MULTILINE)
    matches = list(closing_pattern.finditer(content))

    target_match = None
    for m in matches:
        before = content[:m.start()]
        if 'FINANCIAL_CONCEPTS' in before and 'temas_relacionados' in before:
            target_match = m
            break

    if target_match is None:
        print("ERRO: Não foi possível encontrar o fechamento da lista FINANCIAL_CONCEPTS")
        return False

    insert_pos = target_match.start()

    category_header = (
        '    # =========================================================================\n'
        '    # CATEGORIA: GLOSSÁRIO B3 (Bora Investir)\n'
        '    # =========================================================================\n'
    )

    entries_text = ',\n'.join(new_concepts)
    new_content = (
        content[:insert_pos] +
        category_header +
        entries_text + ',\n' +
        content[insert_pos:]
    )

    new_content = re.sub(
        r'_INITIALIZED\s*=\s*True',
        '_INITIALIZED = False',
        new_content
    )
    new_content = re.sub(
        r'^(_INITIALIZED\s*=\s*)True\s*$',
        r'\g<1>False',
        new_content,
        flags=re.MULTILINE
    )

    FINANCIAL_CONCEPTS_PATH.write_text(new_content, encoding='utf-8')
    return True


async def main():
    print("=" * 60)
    print("Extração do Glossário B3 - Bora Investir")
    print("=" * 60)

    existing_terms = get_existing_terms()
    print(f"\nTermos existentes no sistema: {len(existing_terms)}")

    all_terms: list[tuple[str, str]] = []

    semaphore = asyncio.Semaphore(5)

    async def fetch_with_sem(client, letter):
        async with semaphore:
            return letter, await fetch_letter(client, letter)

    async with httpx.AsyncClient(
        timeout=30.0,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; B3GlossaryBot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
    ) as client:
        tasks = [fetch_with_sem(client, letter) for letter in LETTERS]
        results = await asyncio.gather(*tasks)
        for letter, terms in sorted(results, key=lambda x: x[0]):
            all_terms.extend(terms)
            print(f"  Letra '{letter.upper()}': {len(terms)} termos encontrados")

    print(f"\nTotal de termos encontrados no glossário B3: {len(all_terms)}")

    new_terms = []
    for name, description in all_terms:
        if name.lower().strip() not in existing_terms:
            new_terms.append((name, description))

    print(f"Termos já existentes (ignorados): {len(all_terms) - len(new_terms)}")
    print(f"Novos termos para adicionar: {len(new_terms)}")

    if not new_terms:
        print("\nNenhum termo novo para adicionar.")
        return

    seen_ids = set()
    concept_entries = []
    for name, description in new_terms:
        concept_id = to_snake_case(name)
        if not concept_id:
            concept_id = "termo_" + re.sub(r'\W+', '_', name.lower())[:30]
        if concept_id in seen_ids:
            concept_id = concept_id + "_b3"
        seen_ids.add(concept_id)
        entry = generate_concept_entry(name, description, concept_id)
        concept_entries.append(entry)

    print(f"\nEscrevendo {len(concept_entries)} novos conceitos em {FINANCIAL_CONCEPTS_PATH}...")

    success = write_concepts_to_file(concept_entries)
    if success:
        print(f"\n{len(concept_entries)} conceitos adicionados com sucesso!")
        print("Flag _INITIALIZED resetada para rebuild do índice")
    else:
        print("\nFalha ao escrever conceitos no arquivo")

    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"  Termos encontrados no B3:     {len(all_terms)}")
    print(f"  Termos já existentes:         {len(all_terms) - len(new_terms)}")
    print(f"  Novos termos adicionados:     {len(concept_entries)}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
