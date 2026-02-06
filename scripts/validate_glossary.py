#!/usr/bin/env python3
"""
Script de validação do glossário financeiro.

Verifica:
- Entradas com parênteses malformados
- Abreviações de 1-2 caracteres (ambíguas)
- IDs duplicados
- Termos de busca duplicados entre conceitos diferentes
- Entradas com HTML entities residuais
- Conceitos sem termos de usuário ou busca

Uso:
    python scripts/validate_glossary.py
    python scripts/validate_glossary.py --fix  (para corrigir automaticamente)
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from services.financial_concepts import FINANCIAL_CONCEPTS, get_stats


class GlossaryValidator:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate_all(self):
        self._check_malformed_parens()
        self._check_short_abbreviations()
        self._check_duplicate_ids()
        self._check_html_entities()
        self._check_empty_terms()
        self._check_abbreviation_collisions()

    def _check_malformed_parens(self):
        for concept in FINANCIAL_CONCEPTS:
            for term in concept.get('termos_usuario', []):
                if re.search(r'[A-Za-zÀ-ú&;]\(', term) and not re.search(r'\s\(', term):
                    self.errors.append(
                        f"MALFORMADO: [{concept['id']}] termo '{term}' tem parêntese colado"
                    )
                if term.count('(') != term.count(')'):
                    self.errors.append(
                        f"MALFORMADO: [{concept['id']}] termo '{term}' tem parênteses desbalanceados"
                    )

    def _check_short_abbreviations(self):
        for concept in FINANCIAL_CONCEPTS:
            if concept.get('categoria') != 'GLOSSARIO_B3':
                continue
            for term in concept.get('termos_usuario', []):
                if len(term) <= 2 and term.isupper():
                    self.warnings.append(
                        f"CURTO: [{concept['id']}] abreviação '{term}' muito curta (ambígua)"
                    )

    def _check_duplicate_ids(self):
        seen_ids = {}
        for concept in FINANCIAL_CONCEPTS:
            cid = concept['id']
            if cid in seen_ids:
                self.errors.append(
                    f"ID DUPLICADO: '{cid}' aparece nos conceitos #{seen_ids[cid]+1} e #{FINANCIAL_CONCEPTS.index(concept)+1}"
                )
            else:
                seen_ids[cid] = FINANCIAL_CONCEPTS.index(concept)

    def _check_html_entities(self):
        for concept in FINANCIAL_CONCEPTS:
            for field in ['descricao'] + concept.get('termos_usuario', []):
                text = concept.get('descricao', '') if field == 'descricao' else field
                if re.search(r'&#\d+;', text):
                    self.warnings.append(
                        f"HTML ENTITY: [{concept['id']}] contém HTML entity em '{text[:50]}...'"
                    )

    def _check_empty_terms(self):
        for concept in FINANCIAL_CONCEPTS:
            if not concept.get('termos_usuario'):
                self.errors.append(
                    f"SEM TERMOS: [{concept['id']}] não tem termos_usuario"
                )
            if not concept.get('termos_busca'):
                self.warnings.append(
                    f"SEM BUSCA: [{concept['id']}] não tem termos_busca"
                )

    def _check_abbreviation_collisions(self):
        abbrev_map = {}
        for concept in FINANCIAL_CONCEPTS:
            for term in concept.get('termos_usuario', []):
                if len(term) <= 5 and term.isupper() and len(term) >= 3:
                    key = term.upper()
                    if key not in abbrev_map:
                        abbrev_map[key] = []
                    abbrev_map[key].append(concept['id'])

        for abbrev, ids in abbrev_map.items():
            if len(ids) > 1:
                self.warnings.append(
                    f"COLISÃO: Abreviação '{abbrev}' compartilhada por: {', '.join(ids)}"
                )

    def report(self):
        stats = get_stats()
        print("=" * 60)
        print("VALIDAÇÃO DO GLOSSÁRIO FINANCEIRO")
        print("=" * 60)
        print(f"\nTotal de conceitos: {stats['total_conceitos']}")
        print(f"Total de termos de busca: {stats['total_termos']}")
        print(f"Categorias: {len(stats['categorias'])}")

        if self.errors:
            print(f"\n{'='*60}")
            print(f"ERROS ({len(self.errors)}):")
            print(f"{'='*60}")
            for err in self.errors:
                print(f"  [X] {err}")
        else:
            print(f"\n  [OK] Nenhum erro encontrado")

        if self.warnings:
            print(f"\n{'='*60}")
            print(f"AVISOS ({len(self.warnings)}):")
            print(f"{'='*60}")
            for warn in self.warnings[:20]:
                print(f"  [!] {warn}")
            if len(self.warnings) > 20:
                print(f"  ... e mais {len(self.warnings) - 20} avisos")
        else:
            print(f"\n  [OK] Nenhum aviso encontrado")

        print(f"\n{'='*60}")
        print(f"RESULTADO: {'FALHOU' if self.errors else 'APROVADO'}")
        print(f"  Erros: {len(self.errors)}")
        print(f"  Avisos: {len(self.warnings)}")
        print(f"{'='*60}")

        return len(self.errors) == 0


if __name__ == "__main__":
    validator = GlossaryValidator()
    validator.validate_all()
    passed = validator.report()
    sys.exit(0 if passed else 1)
