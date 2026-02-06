"""
Gera conteúdo técnico detalhado para cada estrutura de derivativos usando GPT-4.
Como os PDFs da XPI não estão acessíveis para download programático,
geramos conteúdo técnico equivalente via IA especializada em derivativos.

O conteúdo gerado inclui:
- Componentes da estrutura (quais opções compra/vende)
- Gráfico de payoff descritivo (cenários de lucro/prejuízo)
- Exemplos numéricos
- Riscos e considerações
- Quando usar vs quando evitar
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from openai import OpenAI
from core.config import get_settings
from scripts.xpi_derivatives.derivatives_dataset import get_all_structures

settings = get_settings()

CACHE_DIR = os.path.join(os.path.dirname(__file__), "vision_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

TECHNICAL_PROMPT = """Você é um especialista em derivativos de renda variável no mercado brasileiro.
Gere conteúdo técnico detalhado sobre a seguinte estrutura de derivativos:

ESTRUTURA: {name}
ABA: {tab}
ESTRATÉGIA: {strategy}
DESCRIÇÃO BASE: {description}

Gere o conteúdo nos seguintes tópicos, de forma DETALHADA e PRECISA:

1. **DEFINIÇÃO E CONCEITO**
   - O que é esta estrutura
   - Objetivo principal
   - Em que contexto de mercado é utilizada

2. **COMPONENTES DA ESTRUTURA**
   - Quais instrumentos são combinados (calls, puts, futuros, etc.)
   - Strikes típicos (ATM, OTM, ITM)
   - Relação entre os componentes
   - Custo da montagem (zero-cost, débito, crédito)

3. **GRÁFICO DE PAYOFF (DESCRIÇÃO DETALHADA)**
   - Descreva o formato do gráfico de resultado no vencimento
   - Eixo X: preço do ativo-objeto
   - Eixo Y: resultado (lucro/prejuízo)
   - Pontos-chave: breakeven, ganho máximo, perda máxima
   - Zonas de lucro e prejuízo
   - Formato da curva em cada região

4. **EXEMPLO NUMÉRICO**
   - Use um ativo fictício com preço de R$ 100
   - Monte a estrutura com strikes realistas
   - Calcule o resultado em 3 cenários: ativo a R$ 80, R$ 100 e R$ 120
   - Mostre o prêmio pago/recebido

5. **QUANDO USAR**
   - Cenários de mercado ideais
   - Perfil do investidor adequado
   - Horizonte de tempo recomendado

6. **QUANDO NÃO USAR**
   - Cenários desfavoráveis
   - Riscos principais
   - Armadilhas comuns

7. **COMPARAÇÃO COM ESTRUTURAS SIMILARES**
   - Diferenças em relação a estruturas parecidas
   - Vantagens e desvantagens comparativas

Escreva em português brasileiro formal, como um material educacional para assessores de investimentos.
NÃO faça recomendações de compra/venda. Explique o funcionamento conceitual e técnico.
Seja MUITO detalhado - este conteúdo será usado por um agente de IA para responder dúvidas de assessores."""


def generate_technical_content(structure: dict, client: OpenAI) -> str:
    """Gera conteúdo técnico detalhado para uma estrutura."""
    prompt = TECHNICAL_PROMPT.format(
        name=structure["name"],
        tab=structure["tab"],
        strategy=structure["strategy"],
        description=structure["description"]
    )
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
        temperature=0.3
    )
    
    return response.choices[0].message.content


def main():
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    structures = get_all_structures()
    
    print(f"Gerando conteúdo técnico para {len(structures)} estruturas...")
    
    generated = 0
    cached = 0
    
    for s in structures:
        cache_path = os.path.join(CACHE_DIR, f"{s['slug']}.txt")
        
        if os.path.exists(cache_path):
            print(f"  [CACHE] {s['name']}")
            cached += 1
            continue
        
        print(f"  [GENERATING] {s['name']}...")
        try:
            content = generate_technical_content(s, client)
            with open(cache_path, "w") as f:
                f.write(content)
            generated += 1
            print(f"    OK ({len(content)} chars)")
        except Exception as e:
            print(f"    ERRO: {e}")
        
        time.sleep(1)
    
    print(f"\nConcluído: {generated} gerados, {cached} em cache")


if __name__ == "__main__":
    main()
