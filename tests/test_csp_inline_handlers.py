import re
import pathlib

TEMPLATE = pathlib.Path(__file__).parent.parent / "frontend" / "templates" / "integrations.html"

FORBIDDEN = re.compile(r'\b(onclick|oninput|onchange)\s*=\s*["\']', re.IGNORECASE)

ALLOWED_CONTEXTS = {
    "<!-- CSP-safe note",
}


def _inline_handler_lines(text: str) -> list[tuple[int, str]]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if FORBIDDEN.search(line):
            stripped = line.strip()
            if any(ctx in stripped for ctx in ALLOWED_CONTEXTS):
                continue
            hits.append((lineno, stripped[:120]))
    return hits


def test_no_inline_event_handlers_in_integrations():
    """Regressão Task #253: nenhum onclick/oninput/onchange inline deve existir
    em integrations.html — todos os handlers devem usar addEventListener."""
    assert TEMPLATE.exists(), f"Template não encontrado: {TEMPLATE}"
    hits = _inline_handler_lines(TEMPLATE.read_text(encoding="utf-8"))
    assert hits == [], (
        "Handlers inline (onclick/oninput/onchange) detectados em integrations.html.\n"
        "Use data-* + addEventListener em vez de atributos inline.\n"
        "Ocorrências:\n" + "\n".join(f"  linha {ln}: {snippet}" for ln, snippet in hits)
    )
