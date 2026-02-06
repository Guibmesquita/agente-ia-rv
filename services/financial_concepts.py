"""
Glossário de Conceitos Financeiros de Renda Variável.

Este módulo fornece:
1. Um dicionário abrangente de conceitos financeiros organizados em categorias
2. Expansão de query: converte termos do usuário em termos de busca mais amplos
3. Contexto para o agente: fornece descrições que ajudam o GPT a entender o que procurar

Usado pelo pipeline de busca (VectorStore) e pelo agente (OpenAIAgent) para
melhorar a recuperação semântica e a qualidade das respostas.
"""

import re
from typing import Dict, List, Optional, Set, Tuple


FINANCIAL_CONCEPTS = [
    # =========================================================================
    # CATEGORIA 1: ESTRUTURA E ESTRATÉGIA DE FUNDOS
    # =========================================================================
    {
        "id": "estrategia_investimento",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "tese", "estratégia", "filosofia", "posicionamento", "como investe",
            "o que faz", "como funciona o fundo", "qual a tese", "tipo de investimento",
            "abordagem", "mandato", "foco do fundo"
        ],
        "termos_busca": [
            "estratégia", "posicionamento", "investimento", "alocação",
            "objetivo do fundo", "hedge fund", "incorporação", "tese",
            "filosofia de investimento", "mandato", "foco"
        ],
        "descricao": "A estratégia ou tese de investimento define como o fundo aloca seus recursos, quais tipos de ativos prioriza, em quais setores atua e qual sua filosofia de gestão. Inclui posicionamento de mercado, tipos de operações e objetivos de retorno.",
        "temas_relacionados": ["composicao_carteira", "gestao_fundo", "alocacao"]
    },
    {
        "id": "gestao_fundo",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "gestão", "gestora", "gestor", "quem gere", "quem administra",
            "gestão ativa", "gestão passiva", "equipe de gestão"
        ],
        "termos_busca": [
            "gestão", "gestor", "gestora", "administrador", "gestão ativa",
            "gestão passiva", "equipe", "management"
        ],
        "descricao": "A gestão do fundo refere-se a quem toma as decisões de investimento. Gestão ativa permite comprar e vender ativos sem aprovação dos cotistas. Gestão passiva segue o regulamento e requer aprovação em assembleia para mudanças.",
        "temas_relacionados": ["estrategia_investimento", "administrador"]
    },
    {
        "id": "objetivo_fundo",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "objetivo", "pra que serve", "qual o objetivo", "finalidade",
            "propósito", "meta do fundo"
        ],
        "termos_busca": [
            "objetivo", "auferir rendimentos", "aplicação de recursos",
            "finalidade", "propósito", "meta"
        ],
        "descricao": "O objetivo do fundo define sua finalidade principal, como auferir rendimentos, valorização de capital ou geração de renda recorrente.",
        "temas_relacionados": ["estrategia_investimento", "regulamento"]
    },
    {
        "id": "regulamento",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "regulamento", "regras", "prazo do fundo", "público alvo",
            "classificação", "anbima"
        ],
        "termos_busca": [
            "regulamento", "prazo do fundo", "público alvo", "classificação",
            "anbima", "condomínio fechado"
        ],
        "descricao": "O regulamento define as regras do fundo: prazo de duração, público-alvo, classificação ANBIMA, política de investimento e direitos dos cotistas.",
        "temas_relacionados": ["objetivo_fundo", "gestao_fundo"]
    },
    {
        "id": "benchmark",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "benchmark", "referência", "índice de referência", "comparação",
            "contra o que compara", "IFIX", "CDI", "Ibovespa"
        ],
        "termos_busca": [
            "benchmark", "IFIX", "CDI", "Ibovespa", "referência",
            "comparação", "índice"
        ],
        "descricao": "Benchmark é o índice de referência usado para avaliar o desempenho de um fundo. Para FIIs, normalmente é o IFIX. Para ações, o Ibovespa. Para renda fixa, o CDI.",
        "temas_relacionados": ["rentabilidade", "performance"]
    },
    {
        "id": "tipo_fii",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "tipo de fundo", "fundo de tijolo", "fundo de papel", "fundo de fundos",
            "FoF", "híbrido", "multiestratégia"
        ],
        "termos_busca": [
            "tijolo", "papel", "fundo de fundos", "FoF", "híbrido",
            "multiestratégia", "hedge fund", "recebíveis"
        ],
        "descricao": "FIIs podem ser de tijolo (imóveis físicos), papel (CRIs, LCIs), fundo de fundos (investe em outros FIIs) ou multiestratégia/híbrido (combina vários tipos).",
        "temas_relacionados": ["estrategia_investimento", "composicao_carteira"]
    },
    {
        "id": "dados_cadastrais",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "CNPJ", "código", "ticker", "início", "data de início",
            "quando começou", "código de negociação"
        ],
        "termos_busca": [
            "CNPJ", "código de negociação", "início do fundo", "ticker",
            "data de início"
        ],
        "descricao": "Dados cadastrais do fundo incluem CNPJ, código de negociação (ticker), data de início, administrador e gestor.",
        "temas_relacionados": ["gestao_fundo", "regulamento"]
    },
    {
        "id": "administrador",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "administrador", "quem administra", "administração do fundo",
            "escriturador", "custodiante"
        ],
        "termos_busca": [
            "administrador", "administração", "escriturador", "custodiante"
        ],
        "descricao": "O administrador é a instituição responsável pela parte burocrática e regulatória do fundo, diferente do gestor que toma decisões de investimento.",
        "temas_relacionados": ["gestao_fundo", "dados_cadastrais"]
    },
    # =========================================================================
    # CATEGORIA 2: PERFORMANCE E INDICADORES
    # =========================================================================
    {
        "id": "rentabilidade",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "rentabilidade", "retorno", "rendimento", "performance",
            "quanto rendeu", "quanto deu", "valorização", "resultado",
            "desempenho", "ganho"
        ],
        "termos_busca": [
            "rentabilidade", "retorno", "valorização", "performance",
            "desempenho", "resultado", "rendimento", "cota patrimonial ajustada",
            "cota de mercado ajustada"
        ],
        "descricao": "Rentabilidade mede o retorno total do investimento, incluindo valorização da cota e dividendos distribuídos. Pode ser expressa em termos absolutos ou relativos a um benchmark.",
        "temas_relacionados": ["benchmark", "dividend_yield", "cota"]
    },
    {
        "id": "dividend_yield",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "dividend yield", "DY", "yield", "rendimento percentual",
            "quanto paga", "quanto rende por mês", "retorno em dividendos"
        ],
        "termos_busca": [
            "dividend yield", "DY", "rendimento", "dividendo",
            "distribuição", "payout"
        ],
        "descricao": "Dividend Yield (DY) é a relação percentual entre os dividendos pagos e o preço da cota. DY = (Dividendos / Preço da cota) × 100. Usado para comparar retorno passivo entre fundos.",
        "temas_relacionados": ["dividendo", "cota", "rentabilidade"]
    },
    {
        "id": "cota",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "cota", "valor da cota", "preço da cota", "cota patrimonial",
            "valor patrimonial", "VP", "cota de mercado", "P/VP",
            "quanto vale", "preço"
        ],
        "termos_busca": [
            "cota", "cota patrimonial", "cota de mercado", "valor patrimonial",
            "P/VP", "preço", "valor", "patrimônio líquido"
        ],
        "descricao": "A cota é a fração do patrimônio do fundo. Cota patrimonial = patrimônio líquido / número de cotas. Cota de mercado = preço negociado na bolsa. P/VP compara as duas: abaixo de 1 = desconto.",
        "temas_relacionados": ["rentabilidade", "patrimonio"]
    },
    {
        "id": "patrimonio",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "patrimônio", "patrimônio líquido", "PL", "tamanho do fundo",
            "quanto tem", "valor de mercado", "market cap"
        ],
        "termos_busca": [
            "patrimônio líquido", "PL", "valor de mercado", "market cap",
            "patrimônio"
        ],
        "descricao": "Patrimônio líquido (PL) é o valor total dos ativos do fundo menos suas obrigações. O valor de mercado é o preço da cota × número de cotas.",
        "temas_relacionados": ["cota", "rentabilidade"]
    },
    {
        "id": "cap_rate",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "cap rate", "taxa de capitalização", "retorno do imóvel",
            "capitalization rate"
        ],
        "termos_busca": [
            "cap rate", "taxa de capitalização", "NOI", "aluguel",
            "valor do imóvel"
        ],
        "descricao": "Cap Rate = (Receita operacional líquida anual / Valor do imóvel) × 100. Mede o retorno anual de um imóvel baseado na receita de aluguel.",
        "temas_relacionados": ["noi", "rentabilidade", "vacancia"]
    },
    {
        "id": "noi",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "NOI", "resultado operacional", "receita líquida",
            "net operating income", "lucro operacional"
        ],
        "termos_busca": [
            "NOI", "resultado operacional", "receita", "despesa",
            "lucro operacional"
        ],
        "descricao": "NOI (Net Operating Income) é a receita bruta de aluguel menos despesas operacionais. É a base para calcular o Cap Rate.",
        "temas_relacionados": ["cap_rate", "resultado_operacional"]
    },
    {
        "id": "pvp",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "P/VP", "preço sobre valor patrimonial", "está caro",
            "está barato", "desconto", "ágio", "deságio"
        ],
        "termos_busca": [
            "P/VP", "valor patrimonial", "deságio", "ágio", "desconto",
            "prêmio"
        ],
        "descricao": "P/VP = Preço de mercado / Valor patrimonial. Abaixo de 1,0 = cota negociada com desconto (deságio). Acima de 1,0 = ágio (prêmio).",
        "temas_relacionados": ["cota", "patrimonio"]
    },
    {
        "id": "pl_ratio",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "P/L", "preço sobre lucro", "múltiplo", "valuation",
            "está caro ou barato"
        ],
        "termos_busca": [
            "P/L", "preço sobre lucro", "múltiplo", "valuation",
            "lucro por ação"
        ],
        "descricao": "P/L (Preço/Lucro) indica quantos anos de lucro são necessários para recuperar o investimento. P/L baixo pode indicar ação barata.",
        "temas_relacionados": ["roe", "rentabilidade"]
    },
    {
        "id": "roe",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "ROE", "retorno sobre patrimônio", "return on equity",
            "eficiência da empresa"
        ],
        "termos_busca": [
            "ROE", "retorno sobre patrimônio", "return on equity",
            "eficiência"
        ],
        "descricao": "ROE (Return on Equity) mede a rentabilidade do patrimônio líquido da empresa. ROE alto indica boa capacidade de gerar lucro com o capital dos sócios.",
        "temas_relacionados": ["pl_ratio", "rentabilidade"]
    },
    # =========================================================================
    # CATEGORIA 3: DISTRIBUIÇÃO E PROVENTOS
    # =========================================================================
    {
        "id": "dividendo",
        "categoria": "DISTRIBUICAO",
        "termos_usuario": [
            "dividendo", "dividendos", "provento", "proventos",
            "quanto paga", "quanto distribui", "rendimento mensal",
            "quanto recebo", "pagamento", "distribuição"
        ],
        "termos_busca": [
            "dividendo", "distribuição", "rendimento", "provento",
            "por cota", "pagamento", "R$"
        ],
        "descricao": "Dividendos são a parcela dos lucros distribuída aos cotistas/acionistas. Em FIIs, a distribuição é geralmente mensal e isenta de IR para pessoa física.",
        "temas_relacionados": ["dividend_yield", "guidance", "payout"]
    },
    {
        "id": "guidance",
        "categoria": "DISTRIBUICAO",
        "termos_usuario": [
            "guidance", "projeção", "estimativa de dividendo",
            "quanto vai pagar", "previsão", "expectativa de dividendo"
        ],
        "termos_busca": [
            "guidance", "projeção", "estimativa", "expectativa",
            "previsão", "dividendo futuro"
        ],
        "descricao": "Guidance é a projeção de dividendos futuros divulgada pela gestão do fundo. Indica quanto o fundo espera distribuir nos próximos meses.",
        "temas_relacionados": ["dividendo", "perspectivas"]
    },
    {
        "id": "payout",
        "categoria": "DISTRIBUICAO",
        "termos_usuario": [
            "payout", "taxa de distribuição", "quanto do lucro distribui",
            "percentual distribuído"
        ],
        "termos_busca": [
            "payout", "distribuição", "percentual", "lucro distribuído"
        ],
        "descricao": "Payout é o percentual dos lucros que o fundo distribui como dividendos. FIIs são obrigados a distribuir pelo menos 95% dos lucros.",
        "temas_relacionados": ["dividendo", "resultado_operacional"]
    },
    {
        "id": "amortizacao",
        "categoria": "DISTRIBUICAO",
        "termos_usuario": [
            "amortização", "devolução de capital", "redução de cota",
            "amortizar"
        ],
        "termos_busca": [
            "amortização", "devolução de capital", "redução", "resgate"
        ],
        "descricao": "Amortização é a devolução de parte do capital investido aos cotistas, além dos dividendos. Geralmente ocorre após venda de ativos.",
        "temas_relacionados": ["dividendo", "cota"]
    },
    {
        "id": "jcp",
        "categoria": "DISTRIBUICAO",
        "termos_usuario": [
            "JCP", "juros sobre capital próprio", "juros sobre capital",
            "JSCP"
        ],
        "termos_busca": [
            "JCP", "juros sobre capital próprio", "JSCP"
        ],
        "descricao": "Juros sobre Capital Próprio (JCP) é uma forma de remuneração dos acionistas similar aos dividendos, mas com tratamento fiscal diferente (dedutível como despesa para a empresa).",
        "temas_relacionados": ["dividendo"]
    },
    # =========================================================================
    # CATEGORIA 4: COMPOSIÇÃO E CARTEIRA
    # =========================================================================
    {
        "id": "composicao_carteira",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "carteira", "composição", "alocação", "em que investe",
            "onde está investido", "portfólio", "ativos do fundo",
            "o que tem na carteira", "exposição"
        ],
        "termos_busca": [
            "carteira", "composição", "alocação", "exposição", "portfólio",
            "ativos", "investimento", "percentual", "% PL", "setor"
        ],
        "descricao": "A composição da carteira mostra em quais ativos o fundo está investido e em qual proporção. Inclui tipo de ativo, setor, indexador, prazo e concentração.",
        "temas_relacionados": ["estrategia_investimento", "cri", "diversificacao"]
    },
    {
        "id": "cri",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "CRI", "certificado de recebíveis", "recebíveis imobiliários",
            "papel", "crédito imobiliário", "operação estruturada"
        ],
        "termos_busca": [
            "CRI", "certificado de recebíveis", "operação estruturada",
            "recebíveis", "securitização", "emissor"
        ],
        "descricao": "CRI (Certificado de Recebíveis Imobiliários) é um título de crédito lastreado em recebíveis do mercado imobiliário. Usado por FIIs de papel como principal investimento.",
        "temas_relacionados": ["composicao_carteira", "ltv", "duration_conceito"]
    },
    {
        "id": "lci",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "LCI", "letra de crédito imobiliário", "LH",
            "letra hipotecária"
        ],
        "termos_busca": [
            "LCI", "letra de crédito", "LH", "letra hipotecária"
        ],
        "descricao": "LCI (Letra de Crédito Imobiliário) e LH (Letra Hipotecária) são títulos de renda fixa lastreados em créditos imobiliários. Isentos de IR para pessoa física.",
        "temas_relacionados": ["cri", "composicao_carteira"]
    },
    {
        "id": "indexador",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "indexador", "índice", "CDI+", "IPCA+", "prefixado",
            "taxa", "remuneração"
        ],
        "termos_busca": [
            "indexador", "CDI", "IPCA", "prefixado", "taxa",
            "remuneração", "spread"
        ],
        "descricao": "O indexador define como a remuneração de um título é calculada. CDI+ = juro pós-fixado + spread. IPCA+ = inflação + taxa real. Prefixado = taxa fixa definida na compra.",
        "temas_relacionados": ["cri", "duration_conceito"]
    },
    {
        "id": "duration_conceito",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "duration", "prazo médio", "vencimento médio",
            "quando recebe de volta", "prazo"
        ],
        "termos_busca": [
            "duration", "prazo médio", "vencimento", "prazo remanescente"
        ],
        "descricao": "Duration é o prazo médio ponderado para o investidor receber de volta o capital investido e juros. Duration maior = maior sensibilidade a mudanças nas taxas de juros.",
        "temas_relacionados": ["cri", "indexador"]
    },
    {
        "id": "vacancia",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "vacância", "ocupação", "taxa de ocupação", "vazio",
            "desocupado", "inquilino"
        ],
        "termos_busca": [
            "vacância", "ocupação", "ABL", "locação", "inquilino",
            "desocupado"
        ],
        "descricao": "Vacância é o percentual de área não locada de um imóvel. Vacância alta = menos receita de aluguel. Vacância pode ser física (área vazia) ou financeira (sem receita).",
        "temas_relacionados": ["abl", "cap_rate"]
    },
    {
        "id": "abl",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "ABL", "área bruta locável", "área do imóvel",
            "tamanho", "metros quadrados"
        ],
        "termos_busca": [
            "ABL", "área bruta locável", "m²", "metros quadrados",
            "área"
        ],
        "descricao": "ABL (Área Bruta Locável) é a área total de um empreendimento disponível para locação, medida em metros quadrados.",
        "temas_relacionados": ["vacancia", "cap_rate"]
    },
    {
        "id": "bts",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "BTS", "built to suit", "construção sob medida",
            "contrato atípico"
        ],
        "termos_busca": [
            "BTS", "built to suit", "contrato atípico", "construção sob medida"
        ],
        "descricao": "Built-to-Suit (BTS) é um contrato em que o imóvel é construído sob medida para um inquilino específico, com prazo longo e multas de rescisão elevadas.",
        "temas_relacionados": ["composicao_carteira", "vacancia"]
    },
    {
        "id": "subscricao",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "subscrição", "oferta", "emissão de cotas", "follow-on",
            "captação", "novas cotas", "direito de subscrição"
        ],
        "termos_busca": [
            "subscrição", "oferta", "emissão", "captação", "novas cotas",
            "direito de subscrição", "preço de subscrição"
        ],
        "descricao": "Subscrição é o processo de emissão de novas cotas para captar recursos. Cotistas existentes têm direito de preferência (direito de subscrição) para manter sua participação.",
        "temas_relacionados": ["cota", "patrimonio"]
    },
    # =========================================================================
    # CATEGORIA 5: RISCO E GARANTIAS
    # =========================================================================
    {
        "id": "ltv",
        "categoria": "RISCO",
        "termos_usuario": [
            "LTV", "loan to value", "endividamento", "alavancagem do CRI",
            "nível de garantia"
        ],
        "termos_busca": [
            "LTV", "loan to value", "garantia", "endividamento",
            "cobertura"
        ],
        "descricao": "LTV (Loan-to-Value) = Valor da dívida / Valor do imóvel em garantia. LTV de 60% significa que a dívida é 60% do valor do imóvel. Quanto menor o LTV, mais segura a operação.",
        "temas_relacionados": ["cri", "garantias", "risco_credito"]
    },
    {
        "id": "garantias",
        "categoria": "RISCO",
        "termos_usuario": [
            "garantia", "garantias", "colateral", "alienação fiduciária",
            "fiança", "cobertura", "segurança"
        ],
        "termos_busca": [
            "garantia", "alienação fiduciária", "colateral", "cobertura",
            "fiança", "cessão fiduciária"
        ],
        "descricao": "Garantias são os ativos dados como segurança em operações de crédito (CRIs). Incluem alienação fiduciária de imóveis, cessão fiduciária de recebíveis e fianças.",
        "temas_relacionados": ["ltv", "cri", "risco_credito"]
    },
    {
        "id": "risco_credito",
        "categoria": "RISCO",
        "termos_usuario": [
            "risco de crédito", "inadimplência", "calote", "default",
            "risco do emissor", "rating"
        ],
        "termos_busca": [
            "risco de crédito", "inadimplência", "default", "rating",
            "classificação de risco"
        ],
        "descricao": "Risco de crédito é a possibilidade de o devedor não pagar suas obrigações. Em FIIs de papel, refere-se ao risco dos emissores dos CRIs.",
        "temas_relacionados": ["ltv", "garantias"]
    },
    {
        "id": "diversificacao",
        "categoria": "RISCO",
        "termos_usuario": [
            "diversificação", "concentração", "risco de concentração",
            "quantos ativos", "pulverizado"
        ],
        "termos_busca": [
            "diversificação", "concentração", "exposição", "setor",
            "pulverizado", "distribuição"
        ],
        "descricao": "Diversificação é a estratégia de distribuir investimentos entre diferentes ativos, setores e regiões para reduzir o risco. Menor concentração = menor risco específico.",
        "temas_relacionados": ["composicao_carteira", "risco_credito"]
    },
    {
        "id": "hedge",
        "categoria": "RISCO",
        "termos_usuario": [
            "hedge", "proteção", "proteger a carteira", "travar preço",
            "seguro", "cobertura de risco"
        ],
        "termos_busca": [
            "hedge", "proteção", "cobertura", "seguro", "travar"
        ],
        "descricao": "Hedge é uma estratégia de proteção contra riscos de mercado, usando instrumentos financeiros (opções, futuros) para limitar perdas potenciais.",
        "temas_relacionados": ["opcoes_basico", "collar", "volatilidade"]
    },
    {
        "id": "volatilidade",
        "categoria": "RISCO",
        "termos_usuario": [
            "volatilidade", "oscilação", "instabilidade", "risco de mercado",
            "variação", "sobe e desce", "IV", "volatilidade implícita"
        ],
        "termos_busca": [
            "volatilidade", "oscilação", "variação", "risco", "IV",
            "volatilidade implícita"
        ],
        "descricao": "Volatilidade mede a intensidade das oscilações de preço de um ativo. Alta volatilidade = maiores oscilações. Volatilidade implícita (IV) é usada na precificação de opções.",
        "temas_relacionados": ["hedge", "gregas_vega"]
    },
    # =========================================================================
    # CATEGORIA 6: MERCADO E NEGOCIAÇÃO
    # =========================================================================
    {
        "id": "liquidez",
        "categoria": "MERCADO",
        "termos_usuario": [
            "liquidez", "volume", "giro", "fácil de vender",
            "negociação", "quanto negocia"
        ],
        "termos_busca": [
            "liquidez", "volume", "giro", "negociação", "transação",
            "compra e venda"
        ],
        "descricao": "Liquidez é a facilidade de comprar ou vender um ativo sem afetar significativamente seu preço. Maior volume de negociação = maior liquidez.",
        "temas_relacionados": ["spread_mercado", "cotacao"]
    },
    {
        "id": "spread_mercado",
        "categoria": "MERCADO",
        "termos_usuario": [
            "spread", "diferença de preço", "bid ask", "compra e venda",
            "book de ofertas"
        ],
        "termos_busca": [
            "spread", "bid", "ask", "book de ofertas", "compra e venda"
        ],
        "descricao": "Spread é a diferença entre o melhor preço de compra (bid) e o melhor preço de venda (ask). Spread menor = mercado mais líquido.",
        "temas_relacionados": ["liquidez"]
    },
    {
        "id": "cotacao",
        "categoria": "MERCADO",
        "termos_usuario": [
            "cotação", "preço atual", "quanto está", "quanto custa",
            "valor de mercado", "preço de tela"
        ],
        "termos_busca": [
            "cotação", "preço", "valor de mercado", "cota de mercado"
        ],
        "descricao": "Cotação é o preço de um ativo no mercado em determinado momento, definido pela oferta e demanda.",
        "temas_relacionados": ["cota", "liquidez"]
    },
    {
        "id": "mercado_secundario",
        "categoria": "MERCADO",
        "termos_usuario": [
            "mercado secundário", "negociação em bolsa", "comprar na bolsa",
            "vender na bolsa"
        ],
        "termos_busca": [
            "mercado secundário", "bolsa", "B3", "negociação"
        ],
        "descricao": "Mercado secundário é onde os investidores negociam cotas/ações entre si após a emissão inicial. As transações ocorrem na B3.",
        "temas_relacionados": ["liquidez", "cotacao"]
    },
    {
        "id": "cotistas",
        "categoria": "MERCADO",
        "termos_usuario": [
            "cotistas", "investidores", "base de cotistas", "quantos investidores",
            "número de cotistas", "acionistas"
        ],
        "termos_busca": [
            "cotistas", "investidores", "base de cotistas", "número de cotistas",
            "crescimento"
        ],
        "descricao": "Cotistas são os investidores que detêm cotas de um fundo. O crescimento da base de cotistas indica popularidade e demanda pelo fundo.",
        "temas_relacionados": ["cota", "liquidez"]
    },
    # =========================================================================
    # CATEGORIA 7: DERIVATIVOS E OPÇÕES
    # =========================================================================
    {
        "id": "opcoes_basico",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "opção", "opções", "mercado de opções", "derivativo",
            "derivativos"
        ],
        "termos_busca": [
            "opção", "opções", "derivativo", "contrato", "direito",
            "obrigação"
        ],
        "descricao": "Opção é um contrato que dá ao comprador o direito (não a obrigação) de comprar ou vender um ativo a um preço predeterminado até uma data específica. Pode ser de compra (call) ou de venda (put).",
        "temas_relacionados": ["call", "put", "strike", "premio"]
    },
    {
        "id": "call",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "call", "opção de compra", "compra de call", "venda de call",
            "direito de comprar"
        ],
        "termos_busca": [
            "call", "opção de compra", "direito de comprar", "strike"
        ],
        "descricao": "Call (opção de compra) dá ao titular o direito de comprar um ativo pelo preço de exercício (strike). O comprador paga um prêmio. O vendedor (lançador) assume a obrigação de vender se exercido.",
        "temas_relacionados": ["put", "strike", "premio", "covered_call"]
    },
    {
        "id": "put",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "put", "opção de venda", "compra de put", "venda de put",
            "direito de vender", "proteção com put"
        ],
        "termos_busca": [
            "put", "opção de venda", "direito de vender", "strike",
            "proteção"
        ],
        "descricao": "Put (opção de venda) dá ao titular o direito de vender um ativo pelo preço de exercício (strike). Usada frequentemente como proteção (hedge) contra quedas.",
        "temas_relacionados": ["call", "strike", "premio", "hedge"]
    },
    {
        "id": "strike",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "strike", "preço de exercício", "exercício", "preço strike",
            "a quanto pode comprar/vender"
        ],
        "termos_busca": [
            "strike", "preço de exercício", "exercício"
        ],
        "descricao": "Strike (preço de exercício) é o preço predeterminado pelo qual o ativo pode ser comprado (call) ou vendido (put) ao exercer a opção.",
        "temas_relacionados": ["call", "put", "moneyness"]
    },
    {
        "id": "premio",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "prêmio", "prêmio da opção", "custo da opção",
            "quanto custa a opção", "valor do prêmio"
        ],
        "termos_busca": [
            "prêmio", "custo", "valor intrínseco", "valor extrínseco",
            "valor temporal"
        ],
        "descricao": "Prêmio é o valor pago pelo comprador da opção ao vendedor. Composto de valor intrínseco (diferença entre preço do ativo e strike) + valor extrínseco (tempo + volatilidade).",
        "temas_relacionados": ["call", "put", "gregas_theta"]
    },
    {
        "id": "moneyness",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "ITM", "OTM", "ATM", "no dinheiro", "fora do dinheiro",
            "dentro do dinheiro", "in the money", "out of the money",
            "at the money"
        ],
        "termos_busca": [
            "ITM", "OTM", "ATM", "in the money", "out of the money",
            "at the money", "no dinheiro"
        ],
        "descricao": "Moneyness classifica opções: ITM (in the money) = com valor intrínseco; ATM (at the money) = strike ≈ preço do ativo; OTM (out of the money) = sem valor intrínseco.",
        "temas_relacionados": ["strike", "premio"]
    },
    {
        "id": "vencimento_opcao",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "vencimento", "expiração", "data de vencimento",
            "quando vence", "série"
        ],
        "termos_busca": [
            "vencimento", "expiração", "série", "data de exercício"
        ],
        "descricao": "Vencimento é a data em que a opção expira. Após essa data, o direito deixa de existir. Opções americanas podem ser exercidas a qualquer momento até o vencimento; europeias apenas no vencimento.",
        "temas_relacionados": ["gregas_theta", "premio"]
    },
    # --- Gregas ---
    {
        "id": "gregas_delta",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "delta", "sensibilidade ao preço", "quanto a opção muda",
            "probabilidade de exercício"
        ],
        "termos_busca": [
            "delta", "sensibilidade", "variação", "preço do ativo"
        ],
        "descricao": "Delta mede quanto o preço da opção muda quando o ativo subjacente muda R$1. Call: delta entre 0 e 1. Put: delta entre -1 e 0. ATM ≈ 0,50. Delta também aproxima a probabilidade de exercício.",
        "temas_relacionados": ["gregas_gamma", "call", "put"]
    },
    {
        "id": "gregas_gamma",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "gamma", "aceleração do delta", "segunda derivada",
            "como delta muda"
        ],
        "termos_busca": [
            "gamma", "aceleração", "delta", "variação"
        ],
        "descricao": "Gamma mede a taxa de variação do delta. É maior para opções ATM próximas do vencimento. Alto gamma = delta muda rapidamente, bom para compradores, arriscado para vendedores.",
        "temas_relacionados": ["gregas_delta"]
    },
    {
        "id": "gregas_theta",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "theta", "decaimento temporal", "time decay",
            "perda de valor por tempo", "erosão"
        ],
        "termos_busca": [
            "theta", "decaimento temporal", "time decay", "valor extrínseco"
        ],
        "descricao": "Theta mede quanto a opção perde de valor por dia devido à passagem do tempo. Negativo para compradores (perdem valor), positivo para vendedores (ganham com o tempo). Acelera perto do vencimento.",
        "temas_relacionados": ["premio", "vencimento_opcao"]
    },
    {
        "id": "gregas_vega",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "vega", "sensibilidade à volatilidade", "volatilidade implícita",
            "IV crush"
        ],
        "termos_busca": [
            "vega", "volatilidade implícita", "IV", "sensibilidade"
        ],
        "descricao": "Vega mede quanto o preço da opção muda quando a volatilidade implícita (IV) muda 1%. Maior para opções ATM e de prazo mais longo. IV crush = queda brusca de volatilidade após eventos.",
        "temas_relacionados": ["volatilidade", "premio"]
    },
    {
        "id": "gregas_rho",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "rho", "sensibilidade a juros", "taxa de juros",
            "impacto da selic"
        ],
        "termos_busca": [
            "rho", "taxa de juros", "selic", "juros"
        ],
        "descricao": "Rho mede a sensibilidade do preço da opção a mudanças na taxa de juros. Mais relevante para opções de longo prazo (LEAPS). Calls se beneficiam de juros altos; puts de juros baixos.",
        "temas_relacionados": ["premio"]
    },
    # --- Estruturas de Opções ---
    {
        "id": "collar",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "collar", "fence", "cerca", "colar", "proteção com collar",
            "estratégia collar"
        ],
        "termos_busca": [
            "collar", "fence", "compra de put", "venda de call",
            "proteção", "corredor de preços"
        ],
        "descricao": "Collar (ou Fence/Cerca) combina: ações + compra de put (proteção contra queda) + venda de call (gera receita mas limita alta). Cria um 'corredor' de preços. Custo geralmente baixo ou zero (zero-cost collar).",
        "temas_relacionados": ["call", "put", "hedge"]
    },
    {
        "id": "call_spread",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "call spread", "trava de alta", "bull call spread",
            "spread de alta com call"
        ],
        "termos_busca": [
            "call spread", "trava de alta", "bull call", "spread vertical"
        ],
        "descricao": "Call Spread (trava de alta): compra call com strike menor + vende call com strike maior. Aposta em alta moderada com risco limitado. Lucro máximo = diferença entre strikes - prêmio pago.",
        "temas_relacionados": ["call", "put_spread"]
    },
    {
        "id": "put_spread",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "put spread", "trava de baixa", "bear put spread",
            "spread de baixa com put"
        ],
        "termos_busca": [
            "put spread", "trava de baixa", "bear put", "spread vertical"
        ],
        "descricao": "Put Spread (trava de baixa): compra put com strike maior + vende put com strike menor. Aposta em queda moderada com risco limitado.",
        "temas_relacionados": ["put", "call_spread"]
    },
    {
        "id": "butterfly",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "butterfly", "borboleta", "estratégia borboleta",
            "butterfly spread"
        ],
        "termos_busca": [
            "butterfly", "borboleta", "3 strikes", "compra e vende calls"
        ],
        "descricao": "Butterfly usa 4 opções com 3 strikes: compra 1 call baixo + vende 2 calls no meio + compra 1 call alto. Lucro máximo quando ativo fica no strike médio. Risco limitado, zona de lucro estreita.",
        "temas_relacionados": ["condor", "opcoes_basico"]
    },
    {
        "id": "condor",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "condor", "iron condor", "estratégia condor",
            "condor de ferro"
        ],
        "termos_busca": [
            "condor", "iron condor", "4 strikes", "venda de put e call"
        ],
        "descricao": "Condor usa 4 opções com 4 strikes diferentes. Iron Condor: vende put OTM + vende call OTM + compra put mais OTM + compra call mais OTM. Lucro quando ativo fica entre os strikes vendidos. Zona de lucro mais ampla que butterfly.",
        "temas_relacionados": ["butterfly", "opcoes_basico"]
    },
    {
        "id": "straddle",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "straddle", "compra de straddle", "venda de straddle",
            "aposta na volatilidade"
        ],
        "termos_busca": [
            "straddle", "compra call e put", "mesmo strike",
            "volatilidade"
        ],
        "descricao": "Straddle: compra call + put no MESMO strike. Long straddle lucra com movimento grande em qualquer direção. Short straddle lucra quando ativo fica parado. Ideal antes de eventos de alta volatilidade.",
        "temas_relacionados": ["strangle", "volatilidade"]
    },
    {
        "id": "strangle",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "strangle", "compra de strangle", "venda de strangle"
        ],
        "termos_busca": [
            "strangle", "compra call OTM e put OTM", "strikes diferentes"
        ],
        "descricao": "Strangle: compra call OTM + put OTM com strikes DIFERENTES. Mais barato que straddle mas precisa de movimento maior para lucrar. Long strangle = aposta em volatilidade. Short strangle = aposta em mercado lateral.",
        "temas_relacionados": ["straddle", "volatilidade"]
    },
    {
        "id": "covered_call",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "covered call", "venda coberta", "lançamento coberto",
            "renda com opções", "vender call coberta"
        ],
        "termos_busca": [
            "covered call", "venda coberta", "lançamento coberto",
            "renda", "prêmio"
        ],
        "descricao": "Covered Call (venda coberta): possui ações + vende call OTM. Gera renda extra com o prêmio recebido. Se exercida, vende as ações pelo strike. Ideal para gerar renda em mercado lateral ou ligeiramente altista.",
        "temas_relacionados": ["call", "premio"]
    },
    {
        "id": "cash_secured_put",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "cash secured put", "venda de put coberta", "put cash secured",
            "comprar ação mais barata"
        ],
        "termos_busca": [
            "cash secured put", "venda de put", "caixa reservado",
            "aquisição"
        ],
        "descricao": "Cash-Secured Put: vende put com dinheiro reservado para comprar as ações se exercida. Gera renda com o prêmio. Se exercida, compra ações a um preço efetivo menor (strike - prêmio). Estratégia para 'ser pago enquanto espera'.",
        "temas_relacionados": ["put", "premio"]
    },
    {
        "id": "contrato_futuro",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "futuro", "contrato futuro", "mercado futuro",
            "mini índice", "mini dólar", "ajuste diário"
        ],
        "termos_busca": [
            "futuro", "contrato futuro", "mercado futuro", "ajuste diário",
            "margem de garantia"
        ],
        "descricao": "Contrato futuro é um acordo de compra/venda de um ativo em data futura a preço fixado hoje. Possui ajuste diário de lucros e prejuízos. Exige margem de garantia. Usado para hedge ou especulação.",
        "temas_relacionados": ["hedge", "alavancagem"]
    },
    {
        "id": "swap",
        "categoria": "DERIVATIVOS",
        "termos_usuario": [
            "swap", "troca de rendimentos", "swap cambial",
            "swap de juros"
        ],
        "termos_busca": [
            "swap", "troca", "câmbio", "CDI", "juros"
        ],
        "descricao": "Swap é um acordo de troca de rendimentos entre dois ativos diferentes (ex: câmbio por CDI). Usado para hedge cambial ou para trocar indexadores de dívidas.",
        "temas_relacionados": ["hedge", "contrato_futuro"]
    },
    # =========================================================================
    # CATEGORIA 8: OPERACIONAL E TRIBUTAÇÃO
    # =========================================================================
    {
        "id": "taxa_administracao",
        "categoria": "OPERACIONAL",
        "termos_usuario": [
            "taxa de administração", "quanto cobra", "custo do fundo",
            "taxa de gestão", "fee"
        ],
        "termos_busca": [
            "taxa de administração", "administração", "custo", "fee",
            "% ao ano"
        ],
        "descricao": "Taxa de administração é o percentual cobrado anualmente sobre o patrimônio líquido do fundo para remunerar gestor e administrador.",
        "temas_relacionados": ["taxa_performance", "resultado_operacional"]
    },
    {
        "id": "taxa_performance",
        "categoria": "OPERACIONAL",
        "termos_usuario": [
            "taxa de performance", "performance fee", "taxa sobre lucro",
            "taxa de desempenho"
        ],
        "termos_busca": [
            "taxa de performance", "performance", "benchmark", "excedente"
        ],
        "descricao": "Taxa de performance é cobrada sobre o retorno que excede o benchmark. Ex: 20% sobre o que exceder o IFIX. Nem todos os fundos cobram.",
        "temas_relacionados": ["taxa_administracao", "benchmark"]
    },
    {
        "id": "resultado_operacional",
        "categoria": "OPERACIONAL",
        "termos_usuario": [
            "resultado operacional", "receita", "despesa", "DRE",
            "demonstrativo", "balanço", "lucro do fundo", "quanto lucrou"
        ],
        "termos_busca": [
            "resultado operacional", "receita", "despesa", "lucro",
            "resultado por cota", "DRE"
        ],
        "descricao": "Resultado operacional mostra as receitas (aluguéis, juros de CRIs) menos despesas (administração, operacionais) do fundo. O resultado por cota indica quanto cada cota gerou de lucro.",
        "temas_relacionados": ["taxa_administracao", "dividendo"]
    },
    {
        "id": "ir_renda_variavel",
        "categoria": "OPERACIONAL",
        "termos_usuario": [
            "imposto", "IR", "imposto de renda", "tributação",
            "quanto pago de imposto", "isento", "isenção"
        ],
        "termos_busca": [
            "IR", "imposto", "tributação", "isenção", "isento",
            "DARF", "ganho de capital"
        ],
        "descricao": "Tributação em RV: Ações swing trade 15%, day trade 20%. FIIs: rendimentos isentos (PF, mín 50 cotistas), ganho de capital 20%. Opções: 15% swing, 20% day trade. IR é pago via DARF até último dia útil do mês seguinte.",
        "temas_relacionados": ["dividendo"]
    },
    {
        "id": "emolumentos",
        "categoria": "OPERACIONAL",
        "termos_usuario": [
            "emolumentos", "custos de transação", "taxa da B3",
            "custódia", "corretagem"
        ],
        "termos_busca": [
            "emolumentos", "custódia", "corretagem", "taxa", "B3"
        ],
        "descricao": "Emolumentos são taxas cobradas pela B3 nas operações. Taxa de custódia pela guarda dos ativos. Corretagem pela execução das ordens (muitas corretoras oferecem taxa zero).",
        "temas_relacionados": ["mercado_secundario"]
    },
    # =========================================================================
    # CONCEITOS ADICIONAIS DE MERCADO
    # =========================================================================
    {
        "id": "ipo",
        "categoria": "MERCADO",
        "termos_usuario": [
            "IPO", "abertura de capital", "oferta pública inicial",
            "estreia na bolsa"
        ],
        "termos_busca": [
            "IPO", "abertura de capital", "oferta pública", "estreia"
        ],
        "descricao": "IPO (Initial Public Offering) é a oferta pública inicial de ações quando uma empresa abre capital na bolsa pela primeira vez.",
        "temas_relacionados": ["subscricao", "mercado_secundario"]
    },
    {
        "id": "etf",
        "categoria": "MERCADO",
        "termos_usuario": [
            "ETF", "fundo de índice", "exchange traded fund",
            "réplica de índice"
        ],
        "termos_busca": [
            "ETF", "fundo de índice", "réplica", "Ibovespa", "S&P 500"
        ],
        "descricao": "ETF (Exchange Traded Fund) é um fundo que replica um índice e é negociado na bolsa como uma ação. Permite diversificação instantânea com baixo custo.",
        "temas_relacionados": ["benchmark", "diversificacao"]
    },
    {
        "id": "bdr",
        "categoria": "MERCADO",
        "termos_usuario": [
            "BDR", "ação estrangeira", "ação americana",
            "Brazilian Depositary Receipt", "investir no exterior"
        ],
        "termos_busca": [
            "BDR", "depositary receipt", "estrangeira", "exterior"
        ],
        "descricao": "BDR (Brazilian Depositary Receipt) é um certificado que representa ações de empresas estrangeiras negociadas na B3. Permite investir em empresas globais sem conta no exterior.",
        "temas_relacionados": ["mercado_secundario"]
    },
    {
        "id": "analise_fundamentalista",
        "categoria": "MERCADO",
        "termos_usuario": [
            "análise fundamentalista", "fundamentos", "balanço",
            "demonstrações financeiras", "valor justo", "valuation"
        ],
        "termos_busca": [
            "fundamentalista", "balanço", "demonstrações", "valor justo",
            "valuation", "fundamentos"
        ],
        "descricao": "Análise fundamentalista avalia o valor intrínseco de uma empresa/fundo usando dados financeiros, contábeis e setoriais para determinar se está barato ou caro.",
        "temas_relacionados": ["pl_ratio", "roe", "pvp"]
    },
    {
        "id": "analise_tecnica",
        "categoria": "MERCADO",
        "termos_usuario": [
            "análise técnica", "gráfico", "grafista", "suporte",
            "resistência", "tendência", "candle"
        ],
        "termos_busca": [
            "análise técnica", "gráfico", "suporte", "resistência",
            "tendência", "candle", "média móvel"
        ],
        "descricao": "Análise técnica estuda padrões de preço e volume em gráficos para prever movimentos futuros. Usa indicadores como médias móveis, suporte/resistência e padrões de candle.",
        "temas_relacionados": ["cotacao", "volatilidade"]
    },
    {
        "id": "alavancagem",
        "categoria": "MERCADO",
        "termos_usuario": [
            "alavancagem", "alavancado", "margem", "operar alavancado",
            "margem de garantia"
        ],
        "termos_busca": [
            "alavancagem", "margem", "margem de garantia", "capital de terceiros"
        ],
        "descricao": "Alavancagem é o uso de capital de terceiros ou margem para ampliar o potencial de retorno (e risco). Permite operar volumes maiores que o capital disponível.",
        "temas_relacionados": ["contrato_futuro", "volatilidade"]
    },
    {
        "id": "stop_loss_gain",
        "categoria": "MERCADO",
        "termos_usuario": [
            "stop loss", "stop gain", "stop", "ordem automática",
            "proteger lucro", "limitar perda"
        ],
        "termos_busca": [
            "stop loss", "stop gain", "ordem", "automática", "limite"
        ],
        "descricao": "Stop Loss é uma ordem automática de venda quando o ativo atinge preço de perda máxima. Stop Gain vende ao atingir o preço-alvo de lucro. Essenciais para gestão de risco.",
        "temas_relacionados": ["hedge", "volatilidade"]
    },
    {
        "id": "day_trade",
        "categoria": "MERCADO",
        "termos_usuario": [
            "day trade", "scalp", "swing trade", "position",
            "operação de curto prazo", "intraday"
        ],
        "termos_busca": [
            "day trade", "swing trade", "position", "scalp", "intraday"
        ],
        "descricao": "Day trade = compra e venda no mesmo dia. Swing trade = operações de dias a semanas. Position = operações de meses a anos. Cada tipo tem tributação diferente.",
        "temas_relacionados": ["ir_renda_variavel", "analise_tecnica"]
    },
    {
        "id": "acoes_on_pn",
        "categoria": "MERCADO",
        "termos_usuario": [
            "ação ordinária", "ação preferencial", "ON", "PN",
            "direito a voto", "tipo de ação"
        ],
        "termos_busca": [
            "ordinária", "preferencial", "ON", "PN", "voto",
            "dividendo preferencial"
        ],
        "descricao": "Ações ordinárias (ON, terminam em 3) dão direito a voto. Ações preferenciais (PN, terminam em 4) têm prioridade no recebimento de dividendos mas geralmente sem voto.",
        "temas_relacionados": ["dividendo", "ipo"]
    },
    {
        "id": "blue_chip",
        "categoria": "MERCADO",
        "termos_usuario": [
            "blue chip", "large cap", "small cap", "mid cap",
            "empresa grande", "empresa pequena"
        ],
        "termos_busca": [
            "blue chip", "large cap", "small cap", "mid cap",
            "capitalização"
        ],
        "descricao": "Blue chips são ações de grandes empresas com alta liquidez (Petrobras, Vale). Small caps são de empresas menores com maior potencial de crescimento mas maior risco.",
        "temas_relacionados": ["liquidez", "volatilidade"]
    },
    # =========================================================================
    # CONCEITOS ESPECÍFICOS DE FIIs
    # =========================================================================
    {
        "id": "incorporacao",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "incorporação", "incorporação residencial", "desenvolvimento",
            "projeto imobiliário", "construção", "VGV"
        ],
        "termos_busca": [
            "incorporação", "residencial", "desenvolvimento", "projeto",
            "construção", "VGV", "obra", "lançamento"
        ],
        "descricao": "Incorporação imobiliária é o desenvolvimento de novos empreendimentos. VGV (Valor Geral de Vendas) é o valor total estimado das unidades. Inclui acompanhamento de obras, vendas e lançamentos.",
        "temas_relacionados": ["estrategia_investimento", "composicao_carteira"]
    },
    {
        "id": "recebimento_preferencial",
        "categoria": "COMPOSICAO",
        "termos_usuario": [
            "recebimento preferencial", "preferencial", "estrutura preferencial",
            "sênior", "mezanino", "subordinação"
        ],
        "termos_busca": [
            "preferencial", "sênior", "mezanino", "subordinação",
            "estrutura", "recebimento"
        ],
        "descricao": "Recebimento preferencial é uma estrutura onde o investidor tem prioridade no recebimento de retornos antes dos demais. Similar à subordinação em CRIs (sênior recebe primeiro).",
        "temas_relacionados": ["estrategia_investimento", "cri"]
    },
    {
        "id": "perspectivas",
        "categoria": "ESTRUTURA_FUNDO",
        "termos_usuario": [
            "perspectiva", "perspectivas", "outlook", "futuro",
            "o que esperar", "projeção", "cenário", "comentário do gestor"
        ],
        "termos_busca": [
            "perspectiva", "outlook", "projeção", "cenário", "futuro",
            "expectativa", "comentário do gestor", "balanço do ano"
        ],
        "descricao": "Perspectivas são as projeções e expectativas da gestão do fundo para o futuro, incluindo cenário macroeconômico, estratégia e projeções de dividendos.",
        "temas_relacionados": ["guidance", "estrategia_investimento"]
    },
]


# Índice invertido: termo → lista de conceitos
_TERM_INDEX: Dict[str, List[dict]] = {}
_INITIALIZED = False


def _build_index():
    """Constrói o índice invertido para busca rápida por termos."""
    global _TERM_INDEX, _INITIALIZED
    if _INITIALIZED:
        return
    
    for concept in FINANCIAL_CONCEPTS:
        for term in concept["termos_usuario"]:
            term_lower = term.lower()
            if term_lower not in _TERM_INDEX:
                _TERM_INDEX[term_lower] = []
            _TERM_INDEX[term_lower].append(concept)
    
    _INITIALIZED = True


def expand_query(user_message: str) -> Dict[str, any]:
    """
    Analisa a mensagem do usuário e retorna:
    - termos_busca_adicionais: termos extras para melhorar a busca vetorial
    - conceitos_detectados: lista de conceitos financeiros identificados
    - contexto_agente: texto descritivo para ajudar o GPT a entender a pergunta
    
    Args:
        user_message: Mensagem original do usuário
    
    Returns:
        Dict com termos_busca_adicionais, conceitos_detectados e contexto_agente
    """
    _build_index()
    
    msg_lower = user_message.lower()
    
    matched_concepts: Dict[str, dict] = {}
    matched_terms: Set[str] = set()
    
    sorted_terms = sorted(_TERM_INDEX.keys(), key=len, reverse=True)
    
    for term in sorted_terms:
        pattern = r'\b' + re.escape(term) + r'\b'
        if re.search(pattern, msg_lower):
            for concept in _TERM_INDEX[term]:
                if concept["id"] not in matched_concepts:
                    matched_concepts[concept["id"]] = concept
                    matched_terms.add(term)
    
    if not matched_concepts:
        return {
            "termos_busca_adicionais": [],
            "conceitos_detectados": [],
            "contexto_agente": "",
            "categorias": []
        }
    
    termos_busca = set()
    categorias = set()
    contexto_parts = []
    
    for concept_id, concept in matched_concepts.items():
        for t in concept["termos_busca"]:
            termos_busca.add(t)
        
        categorias.add(concept["categoria"])
        
        contexto_parts.append(
            f"- {concept['id'].upper()}: {concept['descricao']}"
        )
        
        for related_id in concept.get("temas_relacionados", []):
            for c in FINANCIAL_CONCEPTS:
                if c["id"] == related_id and related_id not in matched_concepts:
                    for t in c["termos_busca"][:3]:
                        termos_busca.add(t)
                    break
    
    contexto_agente = (
        "CONCEITOS FINANCEIROS DETECTADOS NA PERGUNTA:\n" +
        "\n".join(contexto_parts)
    )
    
    return {
        "termos_busca_adicionais": list(termos_busca),
        "conceitos_detectados": list(matched_concepts.keys()),
        "contexto_agente": contexto_agente,
        "categorias": list(categorias)
    }


def get_concept_by_id(concept_id: str) -> Optional[dict]:
    """Retorna um conceito pelo seu ID."""
    for concept in FINANCIAL_CONCEPTS:
        if concept["id"] == concept_id:
            return concept
    return None


def get_concepts_by_category(category: str) -> List[dict]:
    """Retorna todos os conceitos de uma categoria."""
    return [c for c in FINANCIAL_CONCEPTS if c["categoria"] == category]


def get_all_categories() -> List[str]:
    """Retorna todas as categorias disponíveis."""
    return list(set(c["categoria"] for c in FINANCIAL_CONCEPTS))


def get_stats() -> dict:
    """Retorna estatísticas do glossário."""
    categories = {}
    total_terms = 0
    for c in FINANCIAL_CONCEPTS:
        cat = c["categoria"]
        categories[cat] = categories.get(cat, 0) + 1
        total_terms += len(c["termos_usuario"])
    
    return {
        "total_conceitos": len(FINANCIAL_CONCEPTS),
        "total_termos": total_terms,
        "categorias": categories
    }
