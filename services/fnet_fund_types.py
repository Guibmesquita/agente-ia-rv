"""
Mapeamento de tipos de fundo do FNET/B3.

A API pública do FNET (`pesquisarGerenciadorDocumentosDados` e o autocomplete
`listarFundos`) usa o parâmetro inteiro `idTipoFundo` / `tipoFundo` para
distinguir as categorias listadas no select "Tipo do Fundo" do gerenciador
de documentos CVM. Os códigos abaixo foram observados na própria UI da B3
(o `<select>` do gerenciador), que é a única fonte oficial.

| código | sigla  | nome                                                    |
|--------|--------|---------------------------------------------------------|
|   1    | FII    | Fundos de Investimento Imobiliário                      |
|   2    | FIP    | Fundos de Investimento em Participações                 |
|   3    | FIDC   | Fundos de Investimento em Direitos Creditórios          |
|   4    | ETF    | Fundos de Índice (ETF — renda variável)                 |

`PREFIX_BY_TIPO_FUNDO` é usado pelo `FnetClient._resolve_fund` para
desambiguar o autocomplete: quando vários candidatos voltam (fundo-pai +
classes/subsidiárias), preferimos a entrada cujo `text` começa com o
prefixo correspondente ao tipo (ex.: "FIDC " para `tipo_fundo=3`). Sem
essa heurística, um CNPJ de FIDC pode acabar resolvido para uma classe
listada antes na lista, fazendo o sync baixar documentos do fundo errado.
"""
from __future__ import annotations

from typing import Final

FII: Final[int] = 1
FIP: Final[int] = 2
FIDC: Final[int] = 3
ETF: Final[int] = 4

PREFIX_BY_TIPO_FUNDO: Final[dict[int, str]] = {
    FII: "FII ",
    FIP: "FIP ",
    FIDC: "FIDC ",
    ETF: "ETF ",
}

LABEL_BY_TIPO_FUNDO: Final[dict[int, str]] = {
    FII: "FII — Fundo de Investimento Imobiliário",
    FIP: "FIP — Fundo de Investimento em Participações",
    FIDC: "FIDC — Fundo de Investimento em Direitos Creditórios",
    ETF: "ETF — Fundo de Índice",
}

DEFAULT_TIPO_FUNDO: Final[int] = FII


def is_valid_tipo_fundo(value: int) -> bool:
    return value in PREFIX_BY_TIPO_FUNDO


def prefix_for(tipo_fundo: int) -> str:
    """Retorna o prefixo esperado no autocomplete `listarFundos` (ex.: 'FII ')."""
    return PREFIX_BY_TIPO_FUNDO.get(tipo_fundo, "")


def label_for(tipo_fundo: int) -> str:
    return LABEL_BY_TIPO_FUNDO.get(tipo_fundo, f"tipo_fundo={tipo_fundo}")
