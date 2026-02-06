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
    # =========================================================================
    # CATEGORIA 8: OPÇÕES E DERIVATIVOS (ESTRATÉGIAS E CONCEITOS ADICIONAIS)
    # =========================================================================
    {
        "id": "put_seca",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "put seca", "put a seco", "compra de put", "comprar put",
            "venda a descoberto com put"
        ],
        "termos_busca": [
            "put seca", "put a seco", "compra de put", "opção de venda",
            "aposta na queda", "risco limitado ao prêmio"
        ],
        "descricao": "Compra de put a seco é a aquisição de uma opção de venda sem possuir o ativo-objeto. O investidor aposta na queda do ativo. O risco é limitado ao prêmio pago e o ganho potencial é alto se o ativo cair significativamente.",
        "temas_relacionados": ["put", "premio", "call_seca"]
    },
    {
        "id": "call_seca",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "call seca", "call a seco", "compra de call", "comprar call"
        ],
        "termos_busca": [
            "call seca", "call a seco", "compra de call", "opção de compra",
            "aposta na alta", "risco limitado ao prêmio"
        ],
        "descricao": "Compra de call a seco é a aquisição de uma opção de compra sem possuir o ativo-objeto. O investidor aposta na alta do ativo. O risco é limitado ao prêmio pago e o ganho potencial é ilimitado se o ativo subir.",
        "temas_relacionados": ["call", "premio", "put_seca"]
    },
    {
        "id": "venda_put",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "vender put", "venda de put", "lançar put", "lançamento de put"
        ],
        "termos_busca": [
            "venda de put", "lançamento de put", "obrigação de compra",
            "exercício", "prêmio recebido"
        ],
        "descricao": "Venda de put (lançamento) é quando o investidor vende uma opção de venda, recebendo o prêmio. Se exercido, tem a obrigação de comprar o ativo pelo preço de exercício. Estratégia usada para comprar ações com desconto ou gerar renda.",
        "temas_relacionados": ["put", "premio", "venda_call"]
    },
    {
        "id": "venda_call",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "vender call", "venda de call", "lançar call", "lançamento de call",
            "lançamento coberto", "lançamento descoberto", "venda coberta"
        ],
        "termos_busca": [
            "venda de call", "lançamento de call", "lançamento coberto",
            "lançamento descoberto", "venda coberta", "obrigação de vender"
        ],
        "descricao": "Venda de call (lançamento) é quando o investidor vende uma opção de compra, recebendo o prêmio. Lançamento coberto = possui o ativo (risco limitado). Lançamento descoberto = não possui o ativo (risco ilimitado). Se exercido, tem obrigação de vender.",
        "temas_relacionados": ["call", "premio", "covered_call", "venda_put"]
    },
    {
        "id": "premio_opcao",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "prêmio da opção", "custo da opção", "preço da opção",
            "valor do prêmio"
        ],
        "termos_busca": [
            "prêmio", "prêmio da opção", "valor intrínseco", "valor extrínseco",
            "custo da opção", "preço da opção"
        ],
        "descricao": "Prêmio da opção é o valor pago pelo comprador ao vendedor da opção. É composto de valor intrínseco (diferença entre preço do ativo e strike quando favorável) + valor extrínseco (tempo restante + volatilidade implícita).",
        "temas_relacionados": ["premio", "gregas_theta", "volatilidade_implicita"]
    },
    {
        "id": "exercicio_opcao",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "exercício", "exercer", "dia de exercício", "vencimento de opção",
            "expiração", "data de vencimento"
        ],
        "termos_busca": [
            "exercício", "exercer opção", "dia de exercício", "vencimento",
            "expiração", "ITM", "OTM", "ATM"
        ],
        "descricao": "Exercício de opção é quando o titular utiliza seu direito de comprar (call) ou vender (put) o ativo pelo preço de exercício. Só faz sentido exercer opções ITM (in the money). Opções OTM expiram sem valor.",
        "temas_relacionados": ["moneyness", "vencimento_opcao", "strike"]
    },
    {
        "id": "opcao_americana_europeia",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "opção americana", "opção europeia", "americana", "europeia",
            "estilo da opção"
        ],
        "termos_busca": [
            "opção americana", "opção europeia", "estilo americano",
            "estilo europeu", "exercício antecipado"
        ],
        "descricao": "Opção americana pode ser exercida a qualquer momento até o vencimento. Opção europeia só pode ser exercida na data de vencimento. No Brasil, opções de ações são geralmente americanas e opções sobre índice são europeias.",
        "temas_relacionados": ["exercicio_opcao", "vencimento_opcao"]
    },
    {
        "id": "trava_alta",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "trava de alta", "bull spread", "call spread",
            "trava de alta com call"
        ],
        "termos_busca": [
            "trava de alta", "bull spread", "call spread",
            "compra e venda de call", "spread de alta"
        ],
        "descricao": "Trava de alta (bull spread) combina compra de call com strike menor e venda de call com strike maior. Lucra com alta moderada do ativo. Risco e retorno são limitados. O custo é menor que comprar call seca.",
        "temas_relacionados": ["call", "trava_baixa", "call_seca"]
    },
    {
        "id": "trava_baixa",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "trava de baixa", "bear spread", "put spread",
            "trava de baixa com put"
        ],
        "termos_busca": [
            "trava de baixa", "bear spread", "put spread",
            "compra e venda de put", "spread de baixa"
        ],
        "descricao": "Trava de baixa (bear spread) combina compra de put com strike maior e venda de put com strike menor. Lucra com queda moderada do ativo. Risco e retorno são limitados.",
        "temas_relacionados": ["put", "trava_alta", "put_seca"]
    },
    {
        "id": "borboleta",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "borboleta", "butterfly", "butterfly spread"
        ],
        "termos_busca": [
            "borboleta", "butterfly", "butterfly spread",
            "faixa de preço", "aposta lateral"
        ],
        "descricao": "Borboleta (butterfly spread) é uma estratégia que aposta que o ativo ficará numa faixa de preço específica no vencimento. Combina compra e venda de opções em três strikes diferentes. Risco e retorno são limitados.",
        "temas_relacionados": ["condor", "trava_alta", "trava_baixa"]
    },
    {
        "id": "gregas_opcoes",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "gregas", "sensibilidade da opção", "rho"
        ],
        "termos_busca": [
            "gregas", "delta", "gamma", "theta", "vega", "rho",
            "sensibilidade", "precificação de opções"
        ],
        "descricao": "As gregas medem a sensibilidade do preço da opção a diferentes fatores: Delta (preço do ativo), Gamma (variação do delta), Theta (tempo), Vega (volatilidade) e Rho (taxa de juros). Essenciais para gestão de risco em opções.",
        "temas_relacionados": ["gregas_delta", "gregas_gamma", "gregas_theta", "gregas_vega"]
    },
    {
        "id": "volatilidade_implicita",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "volatilidade implícita", "vol implícita", "implied volatility",
            "smile de volatilidade", "skew"
        ],
        "termos_busca": [
            "volatilidade implícita", "IV", "implied volatility",
            "smile de volatilidade", "skew", "expectativa de oscilação"
        ],
        "descricao": "Volatilidade implícita (IV) reflete a expectativa do mercado sobre a oscilação futura do ativo, embutida no preço das opções. Smile de volatilidade mostra como a IV varia por strike. Skew mostra a assimetria. IV alta = opções mais caras.",
        "temas_relacionados": ["gregas_vega", "volatilidade", "premio"]
    },
    {
        "id": "mini_contratos",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "mini contrato", "mini índice", "mini dólar",
            "WIN", "WDO", "IND", "DOL"
        ],
        "termos_busca": [
            "mini contrato", "mini índice", "mini dólar",
            "WIN", "WDO", "IND", "DOL", "day trade", "B3 futuros"
        ],
        "descricao": "Mini contratos são versões menores dos contratos futuros, acessíveis a investidores pessoa física. Mini índice (WIN) = 20% do contrato cheio de Ibovespa. Mini dólar (WDO) = 20% do contrato cheio de dólar. Os mais negociados na B3 para day trade e hedge.",
        "temas_relacionados": ["contrato_futuro", "margem_garantia", "hedge"]
    },
    {
        "id": "termo",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "a termo", "operação a termo", "contrato a termo",
            "termo de ações"
        ],
        "termos_busca": [
            "operação a termo", "contrato a termo", "termo de ações",
            "compra a termo", "venda a termo", "balcão"
        ],
        "descricao": "Operação a termo é um contrato para comprar ou vender um ativo em data futura a preço acordado. Diferente dos futuros, é negociado em balcão e não tem ajuste diário. Usado para alavancar posições em ações.",
        "temas_relacionados": ["contrato_futuro", "margem_garantia"]
    },
    {
        "id": "coe",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "COE", "certificado de operações estruturadas", "nota estruturada",
            "structured note", "capital protegido"
        ],
        "termos_busca": [
            "COE", "certificado de operações estruturadas", "nota estruturada",
            "capital protegido", "proteção de capital", "derivativo estruturado"
        ],
        "descricao": "COE (Certificado de Operações Estruturadas) combina elementos de renda fixa com derivativos. Pode oferecer proteção total ou parcial do capital investido. Permite acesso a estratégias sofisticadas de forma simplificada.",
        "temas_relacionados": ["operacao_estruturada", "hedge"]
    },
    {
        "id": "margem_garantia",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "margem", "margem de garantia", "chamada de margem",
            "margin call", "garantia de operação"
        ],
        "termos_busca": [
            "margem de garantia", "chamada de margem", "margin call",
            "garantia", "depósito de margem", "colateral"
        ],
        "descricao": "Margem de garantia é o capital ou ativos depositados como garantia para operar derivativos (futuros, opções vendidas, termo). Chamada de margem (margin call) ocorre quando a garantia se torna insuficiente e o investidor precisa depositar mais recursos.",
        "temas_relacionados": ["contrato_futuro", "venda_call", "venda_put"]
    },
    {
        "id": "mercado_opcoes",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "mercado de opções", "calls e puts", "call e put",
            "compra e venda de opções"
        ],
        "termos_busca": [
            "mercado de opções", "calls e puts", "opções de ações",
            "derivativos", "B3 opções"
        ],
        "descricao": "O mercado de opções é o ambiente onde se negociam contratos que conferem o direito de comprar (call) ou vender (put) um ativo a preço predeterminado. Na B3, as opções mais negociadas são sobre ações como PETR4, VALE3 e BOVA11.",
        "temas_relacionados": ["call", "put", "opcoes_basico"]
    },
    {
        "id": "operacao_estruturada",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "operação estruturada", "estruturada", "estrutura com opções",
            "montagem de operação"
        ],
        "termos_busca": [
            "operação estruturada", "estrutura com opções", "combinação de opções",
            "perfil de risco-retorno", "montagem de estratégia"
        ],
        "descricao": "Operação estruturada é a combinação de dois ou mais instrumentos financeiros (ações, opções, futuros) para atingir um perfil de risco-retorno específico. Exemplos: collar, trava, borboleta, condor.",
        "temas_relacionados": ["collar", "trava_alta", "trava_baixa", "borboleta"]
    },
    {
        "id": "financiamento_opcoes",
        "categoria": "OPCOES_DERIVATIVOS",
        "termos_usuario": [
            "financiamento", "financiamento com opções", "venda coberta de call",
            "income strategy"
        ],
        "termos_busca": [
            "financiamento com opções", "venda coberta de call", "covered call",
            "income strategy", "geração de renda", "lançamento coberto"
        ],
        "descricao": "Financiamento com opções (covered call) é a estratégia de gerar renda vendendo calls sobre ações que o investidor já possui. Se exercido, vende as ações pelo strike. Se não exercido, fica com o prêmio recebido como renda extra.",
        "temas_relacionados": ["covered_call", "venda_call", "call"]
    },
    # =========================================================================
    # CATEGORIA 9: RENDA FIXA
    # =========================================================================
    {
        "id": "tesouro_direto",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "tesouro direto", "NTN-B", "NTN-F", "LFT", "tesouro IPCA",
            "tesouro selic", "tesouro prefixado", "título público"
        ],
        "termos_busca": [
            "tesouro direto", "NTN-B", "NTN-F", "LFT", "tesouro IPCA",
            "tesouro selic", "tesouro prefixado", "título público", "governo federal"
        ],
        "descricao": "Tesouro Direto é o programa de compra de títulos públicos federais. Tesouro Selic (LFT) = pós-fixado à Selic. Tesouro IPCA+ (NTN-B) = inflação + taxa real. Tesouro Prefixado (NTN-F/LTN) = taxa fixa. Considerados os investimentos mais seguros do Brasil.",
        "temas_relacionados": ["copom_selic", "ipca", "marcacao_mercado"]
    },
    {
        "id": "cdb",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "CDB", "certificado de depósito bancário", "CDB DI", "CDB pré"
        ],
        "termos_busca": [
            "CDB", "certificado de depósito bancário", "CDB DI",
            "CDB prefixado", "CDB IPCA", "renda fixa bancária"
        ],
        "descricao": "CDB (Certificado de Depósito Bancário) é um título de renda fixa emitido por bancos. Pode ser pós-fixado (% do CDI), prefixado ou atrelado à inflação. Conta com garantia do FGC até R$250 mil por CPF/instituição.",
        "temas_relacionados": ["fgc", "copom_selic", "indexador"]
    },
    {
        "id": "debenture",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "debênture", "debêntures", "debênture incentivada",
            "dívida corporativa", "crédito privado"
        ],
        "termos_busca": [
            "debênture", "debênture incentivada", "dívida corporativa",
            "crédito privado", "emissão de dívida", "rating corporativo"
        ],
        "descricao": "Debêntures são títulos de dívida emitidos por empresas para captar recursos. Debêntures incentivadas (Lei 12.431) são isentas de IR para pessoa física. Crédito privado envolve risco do emissor e spread sobre títulos públicos.",
        "temas_relacionados": ["spread_credito", "risco_credito", "indexador"]
    },
    {
        "id": "cra",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "CRA", "certificado de recebíveis do agronegócio", "agronegócio"
        ],
        "termos_busca": [
            "CRA", "certificado de recebíveis do agronegócio",
            "recebíveis agrícolas", "agronegócio", "securitização"
        ],
        "descricao": "CRA (Certificado de Recebíveis do Agronegócio) é um título de renda fixa lastreado em recebíveis do setor agrícola. Isento de IR para pessoa física. Similar ao CRI, mas voltado ao agronegócio.",
        "temas_relacionados": ["cri", "debenture", "indexador"]
    },
    {
        "id": "marcacao_mercado",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "marcação a mercado", "MtM", "mark to market", "precificação",
            "variação de preço do título"
        ],
        "termos_busca": [
            "marcação a mercado", "MtM", "mark to market", "precificação",
            "variação de preço", "PU", "preço unitário"
        ],
        "descricao": "Marcação a mercado (MtM) é a atualização diária do preço de um título de renda fixa de acordo com as condições de mercado. Se as taxas de juros sobem, o preço do título cai (e vice-versa). Afeta quem vende antes do vencimento.",
        "temas_relacionados": ["curva_juros", "duration_conceito", "carrego"]
    },
    {
        "id": "carrego",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "carrego", "carry", "levar até o vencimento", "carregar o título"
        ],
        "termos_busca": [
            "carrego", "carry", "vencimento", "carregar título",
            "retorno contratado", "taxa contratada"
        ],
        "descricao": "Carrego é o retorno obtido ao manter um título de renda fixa até o vencimento, recebendo a taxa contratada. Diferente de vender antes (marcação a mercado), no carrego o investidor recebe exatamente o combinado.",
        "temas_relacionados": ["marcacao_mercado", "duration_conceito"]
    },
    {
        "id": "spread_credito",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "spread de crédito", "prêmio de risco",
            "risco de crédito corporativo"
        ],
        "termos_busca": [
            "spread de crédito", "prêmio de risco", "risco corporativo",
            "spread sobre CDI", "spread sobre NTN-B"
        ],
        "descricao": "Spread de crédito é o prêmio de risco adicional que um título privado paga acima de um título público de referência. Quanto maior o risco do emissor, maior o spread exigido pelo mercado.",
        "temas_relacionados": ["debenture", "risco_credito", "cri"]
    },
    {
        "id": "curva_juros",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "curva de juros", "yield curve", "estrutura a termo",
            "DI futuro", "curva pré"
        ],
        "termos_busca": [
            "curva de juros", "yield curve", "estrutura a termo",
            "DI futuro", "curva pré", "taxa futura"
        ],
        "descricao": "Curva de juros mostra a relação entre taxas de juros e seus prazos de vencimento. Curva normal = taxas maiores para prazos maiores. Curva invertida = taxas curtas maiores que longas (sinal de recessão). DI futuro é o principal indicador no Brasil.",
        "temas_relacionados": ["copom_selic", "marcacao_mercado", "duration_conceito"]
    },
    {
        "id": "convexidade",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "convexidade", "convexity", "sensibilidade à taxa"
        ],
        "termos_busca": [
            "convexidade", "convexity", "sensibilidade à taxa de juros",
            "segunda derivada do preço", "duration modificada"
        ],
        "descricao": "Convexidade complementa a duration para medir a sensibilidade do preço de um título a variações nas taxas de juros. Quanto maior a convexidade, mais o título se beneficia de quedas nas taxas e menos sofre com altas.",
        "temas_relacionados": ["duration_conceito", "marcacao_mercado", "curva_juros"]
    },
    {
        "id": "copom_selic",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "Selic", "COPOM", "taxa básica", "taxa de juros",
            "reunião do COPOM", "meta Selic"
        ],
        "termos_busca": [
            "Selic", "COPOM", "taxa básica de juros", "meta Selic",
            "reunião do COPOM", "política monetária", "Banco Central"
        ],
        "descricao": "A Selic é a taxa básica de juros da economia brasileira, definida pelo COPOM (Comitê de Política Monetária) do Banco Central a cada 45 dias. Influencia todas as taxas de juros do mercado, câmbio e inflação.",
        "temas_relacionados": ["ipca", "curva_juros", "tesouro_direto"]
    },
    {
        "id": "ipca",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "IPCA", "inflação", "IGP-M", "deflação",
            "índice de preços", "CPI"
        ],
        "termos_busca": [
            "IPCA", "inflação", "IGP-M", "deflação", "índice de preços",
            "IBGE", "custo de vida"
        ],
        "descricao": "IPCA (Índice de Preços ao Consumidor Amplo) é o índice oficial de inflação do Brasil, medido pelo IBGE. IGP-M é outro índice, usado em contratos de aluguel. A inflação corrói o poder de compra e impacta diretamente os investimentos.",
        "temas_relacionados": ["copom_selic", "tesouro_direto", "indexador"]
    },
    {
        "id": "fgc",
        "categoria": "RENDA_FIXA",
        "termos_usuario": [
            "FGC", "fundo garantidor", "garantia do FGC",
            "seguro do investimento"
        ],
        "termos_busca": [
            "FGC", "fundo garantidor de créditos", "garantia",
            "R$250 mil", "proteção do investidor", "cobertura FGC"
        ],
        "descricao": "FGC (Fundo Garantidor de Créditos) garante até R$250 mil por CPF por instituição financeira em caso de quebra do banco. Cobre CDB, LCI, LCA, poupança e LC. Não cobre debêntures, CRI, CRA, ações ou fundos.",
        "temas_relacionados": ["cdb", "lci", "risco_credito"]
    },
    # =========================================================================
    # CATEGORIA 10: TRADING E OPERAÇÕES
    # =========================================================================
    {
        "id": "short_selling",
        "categoria": "TRADING",
        "termos_usuario": [
            "short", "venda a descoberto", "operar vendido",
            "short selling", "posição vendida", "apostar na queda"
        ],
        "termos_busca": [
            "short selling", "venda a descoberto", "posição vendida",
            "aluguel de ações", "operar vendido", "aposta na queda"
        ],
        "descricao": "Venda a descoberto (short selling) é a estratégia de vender ações emprestadas (alugadas) apostando na queda. O investidor aluga as ações, vende no mercado e recompra mais barato para devolver. Lucro = diferença de preço menos custos.",
        "temas_relacionados": ["aluguel_acoes", "short_squeeze", "margem_garantia"]
    },
    {
        "id": "short_squeeze",
        "categoria": "TRADING",
        "termos_usuario": [
            "short squeeze", "squeeze", "cobertura de short"
        ],
        "termos_busca": [
            "short squeeze", "squeeze", "cobertura de short",
            "alta forçada", "posições vendidas"
        ],
        "descricao": "Short squeeze é uma alta forçada no preço de um ativo quando muitos investidores vendidos (short) precisam recomprar simultaneamente para cobrir suas posições, gerando pressão compradora e elevando ainda mais o preço.",
        "temas_relacionados": ["short_selling", "aluguel_acoes"]
    },
    {
        "id": "circuit_breaker",
        "categoria": "TRADING",
        "termos_usuario": [
            "circuit breaker", "circuit", "parada de negociação",
            "queda brusca"
        ],
        "termos_busca": [
            "circuit breaker", "parada de negociação", "interrupção",
            "queda brusca", "proteção do mercado"
        ],
        "descricao": "Circuit breaker é a interrupção temporária das negociações na bolsa quando o índice Ibovespa cai além de limites pré-definidos (10%, 15%). Serve para evitar pânico e dar tempo ao mercado de se reorganizar.",
        "temas_relacionados": ["volatilidade", "fluxo_estrangeiro"]
    },
    {
        "id": "aluguel_acoes",
        "categoria": "TRADING",
        "termos_usuario": [
            "aluguel de ações", "empréstimo de ações", "BTC",
            "doador", "tomador"
        ],
        "termos_busca": [
            "aluguel de ações", "empréstimo de ações", "BTC",
            "doador", "tomador", "taxa de aluguel"
        ],
        "descricao": "Aluguel de ações permite que um investidor (doador) empreste suas ações a outro (tomador) mediante pagamento de uma taxa. O tomador usa as ações para operar vendido (short). O doador recebe renda extra sem vender suas ações.",
        "temas_relacionados": ["short_selling", "short_squeeze"]
    },
    {
        "id": "fluxo_estrangeiro",
        "categoria": "TRADING",
        "termos_usuario": [
            "fluxo estrangeiro", "gringo", "investidor estrangeiro",
            "fluxo de capital", "saída de capital"
        ],
        "termos_busca": [
            "fluxo estrangeiro", "investidor estrangeiro", "capital estrangeiro",
            "entrada de capital", "saída de capital", "fluxo gringo"
        ],
        "descricao": "Fluxo estrangeiro representa o capital entrando ou saindo da bolsa brasileira por investidores internacionais. Fluxo positivo (entrada) tende a valorizar ativos. Fluxo negativo (saída) tende a pressionar preços para baixo.",
        "temas_relacionados": ["liquidez", "volatilidade"]
    },
    {
        "id": "book_ofertas",
        "categoria": "TRADING",
        "termos_usuario": [
            "book", "book de ofertas", "livro de ofertas",
            "ordem de compra", "ordem de venda", "bid", "ask", "spread bid-ask"
        ],
        "termos_busca": [
            "book de ofertas", "livro de ofertas", "bid", "ask",
            "spread bid-ask", "profundidade de mercado"
        ],
        "descricao": "Book de ofertas (livro de ofertas) mostra todas as ordens de compra (bid) e venda (ask) pendentes para um ativo, organizadas por preço. O spread bid-ask é a diferença entre a melhor oferta de compra e a melhor oferta de venda.",
        "temas_relacionados": ["spread_mercado", "liquidez", "order_types"]
    },
    {
        "id": "after_market",
        "categoria": "TRADING",
        "termos_usuario": [
            "after market", "pós-mercado", "horário estendido"
        ],
        "termos_busca": [
            "after market", "pós-mercado", "horário estendido",
            "negociação fora do horário", "after hours"
        ],
        "descricao": "After market é o período adicional de negociação após o fechamento normal da bolsa (17h30-18h). Tem regras especiais: variação limitada a 2% do preço de fechamento e menor liquidez.",
        "temas_relacionados": ["liquidez", "order_types"]
    },
    {
        "id": "follow_on",
        "categoria": "TRADING",
        "termos_usuario": [
            "follow-on", "oferta subsequente", "re-IPO",
            "oferta secundária", "bookbuilding"
        ],
        "termos_busca": [
            "follow-on", "oferta subsequente", "oferta secundária",
            "bookbuilding", "emissão de ações", "oferta pública"
        ],
        "descricao": "Follow-on é uma nova emissão de ações por empresa já listada na bolsa. Pode ser primária (empresa emite novas ações e recebe os recursos) ou secundária (acionistas existentes vendem suas ações). O bookbuilding define o preço.",
        "temas_relacionados": ["subscricao", "free_float", "liquidez"]
    },
    {
        "id": "lote_padrao",
        "categoria": "TRADING",
        "termos_usuario": [
            "lote padrão", "lote fracionário", "mercado fracionário",
            "F na frente", "comprar fracionado"
        ],
        "termos_busca": [
            "lote padrão", "lote fracionário", "mercado fracionário",
            "100 ações", "fração"
        ],
        "descricao": "Lote padrão na B3 é de 100 ações. No mercado fracionário, é possível comprar de 1 a 99 ações, adicionando F ao ticker (ex: PETR4F). O fracionário pode ter menor liquidez e spread maior.",
        "temas_relacionados": ["liquidez", "book_ofertas"]
    },
    {
        "id": "order_types",
        "categoria": "TRADING",
        "termos_usuario": [
            "ordem a mercado", "ordem limitada", "ordem stop",
            "ordem casada", "ordem start", "tipo de ordem"
        ],
        "termos_busca": [
            "ordem a mercado", "ordem limitada", "ordem stop",
            "ordem casada", "ordem start", "tipo de ordem", "stop loss", "stop gain"
        ],
        "descricao": "Tipos de ordem: A mercado = executa no melhor preço disponível. Limitada = executa só no preço definido ou melhor. Stop = dispara quando atinge um preço gatilho. Casada = compra e venda simultâneas. Start = compra quando atinge preço de disparo.",
        "temas_relacionados": ["book_ofertas", "liquidez"]
    },
    # =========================================================================
    # CATEGORIA 11: JARGÃO DO ASSESSOR
    # =========================================================================
    {
        "id": "auc",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "AuC", "assets under custody", "patrimônio sob custódia",
            "custódia total"
        ],
        "termos_busca": [
            "AuC", "assets under custody", "patrimônio sob custódia",
            "custódia total", "volume sob gestão"
        ],
        "descricao": "AuC (Assets under Custody) é o volume total de recursos dos clientes sob custódia do assessor ou escritório de assessoria. É a principal métrica de tamanho e relevância de um assessor no mercado.",
        "temas_relacionados": ["captacao_liquida", "fee"]
    },
    {
        "id": "captacao_liquida",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "captação líquida", "captação", "NNM", "net new money",
            "entrada de recursos", "resgate líquido"
        ],
        "termos_busca": [
            "captação líquida", "NNM", "net new money", "entrada de recursos",
            "resgate líquido", "fluxo de clientes"
        ],
        "descricao": "Captação líquida (Net New Money) é a diferença entre recursos captados (novos investimentos) e resgatados pelos clientes. Captação positiva indica crescimento. É uma métrica-chave de desempenho do assessor.",
        "temas_relacionados": ["auc", "fee", "onboarding_cliente"]
    },
    {
        "id": "fee",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "fee", "fee fixo", "fee variável", "comissão",
            "receita do assessor", "rebate", "repasse", "RoA"
        ],
        "termos_busca": [
            "fee", "comissão", "rebate", "repasse", "RoA",
            "receita do assessor", "remuneração", "taxa de administração"
        ],
        "descricao": "Fee é a remuneração do assessor. Pode ser fixo (valor mensal) ou variável (% sobre produtos vendidos/rebate). RoA (Return on Assets) = receita anual / AuC. Rebate é a parcela da taxa de administração repassada ao assessor.",
        "temas_relacionados": ["auc", "captacao_liquida"]
    },
    {
        "id": "suitability",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "suitability", "adequação", "análise de perfil",
            "perfil do investidor", "perfil de risco", "conservador",
            "moderado", "agressivo", "arrojado"
        ],
        "termos_busca": [
            "suitability", "adequação", "perfil do investidor",
            "perfil de risco", "conservador", "moderado", "agressivo",
            "arrojado", "API"
        ],
        "descricao": "Suitability (adequação) é a avaliação do perfil do investidor para garantir que os produtos oferecidos são adequados ao seu perfil de risco. Perfis: conservador, moderado, agressivo/arrojado. Obrigatório por regulação da CVM.",
        "temas_relacionados": ["enquadramento", "onboarding_cliente"]
    },
    {
        "id": "cross_selling",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "cross-selling", "cross sell", "venda cruzada",
            "upselling", "oferta complementar"
        ],
        "termos_busca": [
            "cross-selling", "venda cruzada", "upselling",
            "oferta complementar", "produtos adicionais"
        ],
        "descricao": "Cross-selling é a prática de oferecer produtos financeiros adicionais a um cliente existente. Exemplo: cliente que tem renda fixa recebe oferta de fundos imobiliários ou previdência. Aumenta a receita e diversifica a carteira do cliente.",
        "temas_relacionados": ["fee", "suitability", "pipeline"]
    },
    {
        "id": "onboarding_cliente",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "onboarding", "cadastro de cliente", "abertura de conta",
            "transferência de custódia", "STVM", "portabilidade"
        ],
        "termos_busca": [
            "onboarding", "cadastro", "abertura de conta",
            "transferência de custódia", "STVM", "portabilidade"
        ],
        "descricao": "Onboarding é o processo de cadastro de um novo cliente: abertura de conta, análise de perfil (suitability), documentação. STVM é a transferência de custódia de outra corretora. Portabilidade é a transferência de investimentos.",
        "temas_relacionados": ["suitability", "captacao_liquida"]
    },
    {
        "id": "ipa",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "IPA", "AAI", "assessor de investimentos", "agente autônomo",
            "escritório de assessoria", "credenciado"
        ],
        "termos_busca": [
            "IPA", "AAI", "assessor de investimentos", "agente autônomo",
            "escritório de assessoria", "credenciado CVM"
        ],
        "descricao": "IPA (Intermediário de Produtos de Investimento) / AAI (Agente Autônomo de Investimentos) é o profissional credenciado pela CVM que atua como assessor de investimentos, intermediando a relação entre investidor e corretora.",
        "temas_relacionados": ["ancord", "suitability", "fee"]
    },
    {
        "id": "ancord",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "ANCORD", "CPA-10", "CPA-20", "CEA", "CFP",
            "certificação", "prova ANCORD", "certificado"
        ],
        "termos_busca": [
            "ANCORD", "CPA-10", "CPA-20", "CEA", "CFP",
            "certificação financeira", "habilitação profissional"
        ],
        "descricao": "Certificações profissionais do mercado financeiro: ANCORD (assessor de investimentos), CPA-10/CPA-20 (ANBIMA, para bancários), CEA (especialista ANBIMA), CFP (planejador financeiro). Obrigatórias para atuar no mercado.",
        "temas_relacionados": ["ipa", "suitability"]
    },
    {
        "id": "mesa_rv",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "mesa RV", "mesa de renda variável", "mesa de operações",
            "trader", "operador de mesa", "broker"
        ],
        "termos_busca": [
            "mesa de renda variável", "mesa de operações", "trader",
            "operador de mesa", "broker", "execução de ordens"
        ],
        "descricao": "Mesa de Renda Variável é a área da corretora responsável pela execução de ordens em ações, opções e derivativos. O trader/operador de mesa auxilia o assessor na execução de operações mais complexas.",
        "temas_relacionados": ["order_types", "operacao_estruturada", "ipa"]
    },
    {
        "id": "pipeline",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "pipeline", "pipe", "negócio em andamento",
            "oportunidade", "deal flow"
        ],
        "termos_busca": [
            "pipeline", "deal flow", "oportunidade de negócio",
            "funil de vendas", "prospecção"
        ],
        "descricao": "Pipeline é o conjunto de oportunidades de negócio em andamento do assessor: novos clientes em prospecção, transferências de custódia em processo, operações em análise. Deal flow é o fluxo de novas oportunidades.",
        "temas_relacionados": ["captacao_liquida", "onboarding_cliente", "cross_selling"]
    },
    {
        "id": "churning",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "churning", "giro excessivo", "overtrading",
            "excesso de operações"
        ],
        "termos_busca": [
            "churning", "giro excessivo", "overtrading",
            "prática irregular", "excesso de corretagem"
        ],
        "descricao": "Churning é a prática irregular de realizar giro excessivo na carteira do cliente para gerar comissões (corretagem) para o assessor. É vedado pela CVM e pode resultar em punições e ressarcimento ao cliente.",
        "temas_relacionados": ["fee", "suitability", "enquadramento"]
    },
    {
        "id": "enquadramento",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "enquadramento", "enquadrar carteira", "rebalanceamento",
            "adequação de carteira", "carteira adequada"
        ],
        "termos_busca": [
            "enquadramento", "adequação de carteira", "rebalanceamento",
            "perfil de risco", "carteira adequada"
        ],
        "descricao": "Enquadramento é o processo de ajustar a carteira do cliente ao seu perfil de risco (suitability). Inclui rebalanceamento de posições, substituição de ativos inadequados e adequação a limites regulatórios.",
        "temas_relacionados": ["suitability", "diversificacao"]
    },
    {
        "id": "come_cotas",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "come-cotas", "come cotas", "antecipação de IR",
            "tributação semestral"
        ],
        "termos_busca": [
            "come-cotas", "antecipação de IR", "tributação semestral",
            "maio e novembro", "imposto sobre fundos"
        ],
        "descricao": "Come-cotas é a antecipação do Imposto de Renda cobrada semestralmente (maio e novembro) sobre fundos de investimento abertos. Reduz o número de cotas do investidor. Alíquota de 15% (longo prazo) ou 20% (curto prazo).",
        "temas_relacionados": ["iof_ir", "dividendo"]
    },
    {
        "id": "iof_ir",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "IOF", "imposto de renda", "IR", "tributação",
            "tabela regressiva", "alíquota", "DARF",
            "IR sobre ganho de capital", "15%", "20%"
        ],
        "termos_busca": [
            "IOF", "imposto de renda", "IR", "tributação",
            "tabela regressiva", "alíquota", "DARF", "ganho de capital"
        ],
        "descricao": "IOF incide sobre resgates em menos de 30 dias. IR em renda fixa segue tabela regressiva: 22,5% (até 180 dias) a 15% (acima de 720 dias). Ações: 15% sobre ganho de capital (20% em day trade). DARF é a guia de pagamento do imposto.",
        "temas_relacionados": ["come_cotas", "dividendo"]
    },
    {
        "id": "pgbl_vgbl",
        "categoria": "ASSESSOR_JARGAO",
        "termos_usuario": [
            "PGBL", "VGBL", "previdência privada", "previdência",
            "aposentadoria", "plano de previdência"
        ],
        "termos_busca": [
            "PGBL", "VGBL", "previdência privada", "aposentadoria",
            "plano de previdência", "tabela regressiva", "tabela progressiva"
        ],
        "descricao": "PGBL permite deduzir até 12% da renda bruta no IR (indicado para quem faz declaração completa). VGBL não deduz, mas o IR incide só sobre os rendimentos (indicado para declaração simplificada). Ambos podem usar tabela regressiva ou progressiva.",
        "temas_relacionados": ["iof_ir", "come_cotas"]
    },
    # =========================================================================
    # CATEGORIA 12: CONCEITOS ADICIONAIS IMPORTANTES
    # =========================================================================
    {
        "id": "ebitda",
        "categoria": "PERFORMANCE",
        "termos_usuario": [
            "EBITDA", "lucro antes de juros", "resultado operacional",
            "LAJIDA"
        ],
        "termos_busca": [
            "EBITDA", "LAJIDA", "lucro operacional", "resultado operacional",
            "margem EBITDA"
        ],
        "descricao": "EBITDA (Lucro antes de Juros, Impostos, Depreciação e Amortização) mede a geração de caixa operacional de uma empresa. Margem EBITDA = EBITDA / Receita Líquida. Usado para comparar eficiência operacional entre empresas.",
        "temas_relacionados": ["pl_ratio", "roe", "noi"]
    },
    {
        "id": "free_float",
        "categoria": "MERCADO",
        "termos_usuario": [
            "free float", "ações em circulação", "percentual em circulação",
            "liquidez de mercado"
        ],
        "termos_busca": [
            "free float", "ações em circulação", "ações disponíveis",
            "liquidez", "percentual em circulação"
        ],
        "descricao": "Free float é o percentual de ações de uma empresa disponíveis para negociação no mercado, excluindo ações detidas por controladores e insiders. Maior free float = maior liquidez e facilidade de negociação.",
        "temas_relacionados": ["liquidez", "governanca", "follow_on"]
    },
    {
        "id": "tag_along",
        "categoria": "MERCADO",
        "termos_usuario": [
            "tag along", "proteção minoritário", "direito de saída",
            "100% tag along"
        ],
        "termos_busca": [
            "tag along", "proteção minoritário", "direito de saída",
            "mudança de controle", "oferta pública de aquisição"
        ],
        "descricao": "Tag along é o direito dos acionistas minoritários de vender suas ações por pelo menos 80% do preço pago ao controlador em caso de mudança de controle. No Novo Mercado, o tag along é de 100%.",
        "temas_relacionados": ["governanca", "free_float"]
    },
    {
        "id": "governanca",
        "categoria": "MERCADO",
        "termos_usuario": [
            "governança", "novo mercado", "nível 1", "nível 2",
            "segmento de listagem", "governança corporativa"
        ],
        "termos_busca": [
            "governança corporativa", "novo mercado", "nível 1", "nível 2",
            "segmento de listagem", "boas práticas"
        ],
        "descricao": "Governança corporativa são as práticas de gestão transparente e proteção aos acionistas. Na B3, os segmentos de listagem são: Novo Mercado (mais exigente, só ações ON, 100% tag along), Nível 2 e Nível 1 (menos exigentes).",
        "temas_relacionados": ["tag_along", "free_float"]
    },
    {
        "id": "split_grupamento",
        "categoria": "MERCADO",
        "termos_usuario": [
            "split", "desdobramento", "grupamento", "inplit",
            "ajuste de preço da ação"
        ],
        "termos_busca": [
            "split", "desdobramento", "grupamento", "inplit",
            "ajuste de preço", "proporção"
        ],
        "descricao": "Split (desdobramento) divide cada ação em várias, reduzindo o preço unitário sem alterar o valor total. Grupamento (inplit) é o inverso: junta várias ações em uma, aumentando o preço unitário. Não altera o patrimônio do investidor.",
        "temas_relacionados": ["cotacao", "liquidez"]
    },
    {
        "id": "bonificacao",
        "categoria": "DISTRIBUICAO",
        "termos_usuario": [
            "bonificação", "ações bonificadas", "bonificação em ações",
            "distribuição gratuita de ações"
        ],
        "termos_busca": [
            "bonificação", "ações bonificadas", "distribuição gratuita",
            "incorporação de reservas"
        ],
        "descricao": "Bonificação é a distribuição gratuita de novas ações aos acionistas, geralmente originada da incorporação de reservas de lucro ao capital social. O acionista recebe mais ações proporcionalmente à sua participação.",
        "temas_relacionados": ["dividendo", "provento_tipos"]
    },
    {
        "id": "provento_tipos",
        "categoria": "DISTRIBUICAO",
        "termos_usuario": [
            "rendimento isento", "rendimento tributável", "proventos em ações",
            "direito de preferência", "sobras"
        ],
        "termos_busca": [
            "rendimento isento", "rendimento tributável", "proventos em ações",
            "direito de preferência", "sobras", "tipos de provento"
        ],
        "descricao": "Tipos de proventos: dividendos (isentos de IR), JCP (tributados na fonte), bonificação em ações, direito de preferência em subscrição e sobras (frações não exercidas). Cada tipo tem tratamento fiscal diferente.",
        "temas_relacionados": ["dividendo", "jcp", "bonificacao", "subscricao"]
    },
    {
        "id": "beta",
        "categoria": "RISCO",
        "termos_usuario": [
            "beta", "beta da ação", "risco sistemático",
            "correlação com mercado", "coeficiente beta"
        ],
        "termos_busca": [
            "beta", "coeficiente beta", "risco sistemático",
            "sensibilidade ao mercado", "Ibovespa"
        ],
        "descricao": "Beta mede a sensibilidade de uma ação em relação ao mercado (Ibovespa). Beta = 1: se move igual ao mercado. Beta > 1: mais volátil que o mercado. Beta < 1: menos volátil. Beta negativo: se move na direção oposta.",
        "temas_relacionados": ["volatilidade", "diversificacao", "benchmark"]
    },
    # =========================================================================
    # CATEGORIA: GLOSSÁRIO B3 (Bora Investir)
    # =========================================================================
    {
        "id": "abertura",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Abertura"],
        "termos_busca": ["abertura", "primeiro", "preço", "determinado", "ativo", "negociou", "sessão"],
        "descricao": "Primeiro preço em que determinado ativo negociou em uma sessão de negociação, tanto nos mercados nacionais e internacionais.",
        "temas_relacionados": []
    },
    {
        "id": "acao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acao", "Ação"],
        "termos_busca": ["ação", "representa", "menor", "capital", "empresa"],
        "descricao": "Uma ação representa a menor parte do capital de uma empresa.",
        "temas_relacionados": []
    },
    {
        "id": "acao_cheia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acao Cheia", "Ação Cheia"],
        "termos_busca": ["ação", "cheia", "permite", "investidor", "receber", "dividendos"],
        "descricao": "Uma ação cheia é uma ação que permite ao investidor receber dividendos ou exercer subscrições",
        "temas_relacionados": []
    },
    {
        "id": "acao_em_tesouraria",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acao em Tesouraria", "Ação em Tesouraria"],
        "termos_busca": ["ação", "tesouraria", "título", "recomprado", "direitos", "econômicos"],
        "descricao": "Ação em tesouraria é título recomprado sem direitos econômicos, utilizado para valorização ou remuneração de executivos",
        "temas_relacionados": []
    },
    {
        "id": "acao_escritural",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acao Escritural", "Ação Escritural"],
        "termos_busca": ["ação", "escritural", "registrada", "eletronicamente", "certificado", "físico"],
        "descricao": "Ação escritural é registrada eletronicamente, sem certificado físico, o que garante mais segurança, agilidade e transparência no mercado financeiro",
        "temas_relacionados": []
    },
    {
        "id": "acao_fracionada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acao Fracionada", "Ação Fracionada"],
        "termos_busca": ["fracionada", "ação", "mercado", "fracionário", "simplifica", "acesso", "compra", "ações"],
        "descricao": "O mercado fracionário simplifica o acesso à compra de ações na bolsa de valores, possibilitando investimentos mais acessíveis e adaptados às possibilidades financeiras individuais.",
        "temas_relacionados": []
    },
    {
        "id": "acao_listada_em_bolsa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acao Listada em Bolsa", "Ação Listada em Bolsa", "ALB"],
        "termos_busca": ["listada", "ação", "negociada", "pregão", "bolsa", "valores"],
        "descricao": "Ação negociada no pregão de uma bolsa de valores.",
        "temas_relacionados": []
    },
    {
        "id": "acao_nominativa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acao Nominativa", "Ação Nominativa"],
        "termos_busca": ["ação", "nominativa", "registrada", "nome", "acionista", "oferece"],
        "descricao": "Ação nominativa é registrada no nome do acionista e oferece mais controle e segurança para empresas; saiba vantagens e desvantagens",
        "temas_relacionados": []
    },
    {
        "id": "acao_vazia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acao Vazia", "Ação Vazia"],
        "termos_busca": ["ação", "vazia", "cujos", "direitos", "foram", "exercidos"],
        "descricao": "Uma ação vazia é uma ação cujos direitos já foram exercidos.",
        "temas_relacionados": []
    },
    {
        "id": "acc_adiantamento_sobre_contratos_de_cambio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ACC – Adiantamento sobre Contratos de Câmbio", "ACC  Adiantamento sobre Contratos de Cambio", "AASCC"],
        "termos_busca": ["sobre", "acc", "funciona", "adiantamento", "contratos", "câmbio", "papel", "desse"],
        "descricao": "O que é ACC, como funciona o Adiantamento sobre Contratos de Câmbio e qual o papel desse instrumento no financiamento de exportações",
        "temas_relacionados": []
    },
    {
        "id": "ace_adiantamento_sobre_cambiais_entregues",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ACE (Adiantamento sobre Cambiais Entregues)", "Adiantamento sobre Cambiais Entregues", "ACE"],
        "termos_busca": ["entregues", "cambiais", "sobre", "adiantamento", "ace", "entenda", "funciona", "vantagens"],
        "descricao": "Entenda o que é ACE, como funciona, vantagens para exportadores e diferenças para ACC no comércio exterior",
        "temas_relacionados": []
    },
    {
        "id": "acionista",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acionista"],
        "termos_busca": ["acionista", "investidor", "possui", "ações", "determinada", "empresa"],
        "descricao": "Investidor que possui ações de uma determinada empresa",
        "temas_relacionados": []
    },
    {
        "id": "acionista_controlador",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acionista Controlador"],
        "termos_busca": ["acionista", "controlador", "quem", "influência", "decisiva", "empresa"],
        "descricao": "O acionista controlador é quem tem influência decisiva sobre a empresa, com poder de eleger administradores e definir estratégias corporativas",
        "temas_relacionados": []
    },
    {
        "id": "acionista_dissidente",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acionista Dissidente"],
        "termos_busca": ["dissidente", "acionista", "investidor", "exerce", "direito", "recesso", "discordar", "decisões"],
        "descricao": "Investidor que exerce o direito de recesso ao discordar das decisões tomadas em assembleias, protegendo seus interesses e impactando a governança corporativa.",
        "temas_relacionados": []
    },
    {
        "id": "acionista_majoritario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acionista Majoritario", "Acionista Majoritário"],
        "termos_busca": ["majoritário", "acionista", "aquele", "possui", "poder", "ações", "direito", "voto"],
        "descricao": "É aquele que possui em seu poder mais de 50% das ações com direito a voto de uma companhia.",
        "temas_relacionados": []
    },
    {
        "id": "acionista_minoritario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acionista Minoritario", "Acionista Minoritário"],
        "termos_busca": ["minoritário", "acionista", "acionistas", "minoritários", "representam", "parcela", "significativa", "investidores"],
        "descricao": "Os acionistas minoritários representam uma parcela significativa de investidores no mercado de ações e possuem direitos legais que garantem sua participação e proteção em sociedades anônimas; entenda",
        "temas_relacionados": []
    },
    {
        "id": "acoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acoes", "Ações"],
        "termos_busca": ["ações", "funcionam", "tributação", "formas", "investir"],
        "descricao": "O que são ações, como funcionam, qual é a tributação e as formas de investir",
        "temas_relacionados": []
    },
    {
        "id": "acoes_adicionais",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acoes Adicionais", "Ações Adicionais"],
        "termos_busca": ["quantidade", "ações", "adicionais", "relação", "inicialmente", "ofertada"],
        "descricao": "Quantidade de Ações adicionais em relação à quantidade de ações inicialmente ofertada (sem considerar as Ações do Lote Suplementar) que, conforme dispõe o artigo 14, parágrafo 2º da Instrução CVM 400, poderá ser acrescida à Oferta, a critério da Companhia...",
        "temas_relacionados": []
    },
    {
        "id": "acoes_do_lote_suplementar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acoes do Lote Suplementar", "Ações do Lote Suplementar", "ALS"],
        "termos_busca": ["suplementar", "ações", "ofertadas", "adicionalmente", "oferta", "lote", "inicial"],
        "descricao": "Ações ofertadas adicionalmente, após a oferta do lote inicial, visando atender a um excesso de demanda.",
        "temas_relacionados": []
    },
    {
        "id": "acordo_de_cooperacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Acordo de Cooperacao", "Acordo de Cooperação"],
        "termos_busca": ["cooperação", "acordo", "colaboração", "diferentes", "organizações", "resulta", "constituição", "nova"],
        "descricao": "Forma de colaboração entre diferentes organizações, e que não resulta na constituição de nova entidade",
        "temas_relacionados": []
    },
    {
        "id": "administracao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Administracao", "Administração"],
        "termos_busca": ["conselho", "administração", "diretoria", "companhia"],
        "descricao": "Conselho de Administração e Diretoria da Companhia.",
        "temas_relacionados": []
    },
    {
        "id": "administracao_ativa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Administracao Ativa", "Administração Ativa"],
        "termos_busca": ["ativa", "geral", "expressão", "usada", "definir", "estratégia", "administração"],
        "descricao": "Em geral essa expressão é usada para definir o tipo de estratégia de administração de um fundo de investimento. Nesse tipo de estratégia o administrador compra e vende ações, sem replicar nenhum índice, mas sempre tentando obter uma rentabilidade acima...",
        "temas_relacionados": []
    },
    {
        "id": "administracao_fiduciaria",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Administracao Fiduciaria", "Administração Fiduciária"],
        "termos_busca": ["fiduciária", "administração", "compreende", "conjunto", "serviços", "prestados", "direta", "indiretamente"],
        "descricao": "Compreende o conjunto de serviços prestados, direta ou indiretamente, ao funcionamento de fundos de investimento, de acordo com a Resolução CVM 21, de 25/02/21 e demais dispositivos legais aplicáveis.",
        "temas_relacionados": []
    },
    {
        "id": "administracao_passiva",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Administracao Passiva", "Administração Passiva"],
        "termos_busca": ["passiva", "estratégia", "administração", "fundos", "investimento", "busca", "replicar"],
        "descricao": "Estratégia de administração de fundos de investimento, que busca replicar o retorno da carteira de um índice previamente definido, também chamado de benchmark.",
        "temas_relacionados": []
    },
    {
        "id": "administrador_de_fundo_imobiliario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Administrador de Fundo Imobiliario", "Administrador de Fundo Imobiliário", "AFI"],
        "termos_busca": ["imobiliário", "fundo", "administrador", "instituição", "financeira", "autorizada", "responsável", "serviços"],
        "descricao": "É a instituição financeira autorizada pela CVM responsável pelos serviços, direta ou indiretamente, relacionados as atividades de administração, obrigações legais e regulamentares, e gestão de patrimônio que irão compor as atividades dos fundos imobiliários.",
        "temas_relacionados": []
    },
    {
        "id": "adr_american_depositary_receipt",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ADR (American Depositary Receipt)", "American Depositary Receipt", "ADR"],
        "termos_busca": ["receipt", "depositary", "american", "adr", "mecanismo", "permite", "investidores", "americanos"],
        "descricao": "Mecanismo permite que investidores americanos negociem ações de empresas estrangeiras em bolsas dos EUA",
        "temas_relacionados": []
    },
    {
        "id": "adx",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ADX"],
        "termos_busca": ["adx", "average", "directional", "index", "índice", "movimento", "direcional"],
        "descricao": "ADX (Average Directional Index) ou Índice de Movimento Direcional Médio é um índice de análise técnica criado por J. Welles Wilder com objetivo de medir a intensidade de uma tendência, sinalizando as movimentações futuras dos preços dos ativos.",
        "temas_relacionados": []
    },
    {
        "id": "agencia_bancaria",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agencia Bancaria", "Agência Bancária"],
        "termos_busca": ["bancária", "agência", "segundo", "banco", "central", "brasil", "dependência", "instituições"],
        "descricao": "Segundo o Banco Central do Brasil, é a dependência de instituições financeiras e demais instituições, autorizadas a funcionar destinada à prática das atividades para as quais a instituição esteja regularmente habilitada (vide Resolução CMN 2.212/1995)",
        "temas_relacionados": []
    },
    {
        "id": "agencia_de_classificacao_de_risco",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agencia de classificacao de risco", "Agência de classificação de risco", "ACR"],
        "termos_busca": ["entenda", "agência", "classificação", "risco", "saiba", "funcionam"],
        "descricao": "Entenda o que é uma agência de classificação de risco, saiba como funcionam os ratings de crédito e qual é a influência desse sistema no mercado financeiro",
        "temas_relacionados": []
    },
    {
        "id": "agencia_de_fomento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agencia de Fomento", "Agência de Fomento"],
        "termos_busca": ["entenda", "agência", "fomento", "apoia", "empresas", "desenvolvimento"],
        "descricao": "Entenda o que é uma agência de fomento e como ela apoia empresas e o desenvolvimento econômico",
        "temas_relacionados": []
    },
    {
        "id": "agente_autonomo_de_investimento_aai",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agente Autonomo de Investimento (AAI)", "Agente Autônomo de Investimento (AAI)", "Agente Autonomo de Investimento", "Agente Autônomo de Investimento", "AAI"],
        "termos_busca": ["aai", "saiba", "agente", "autônomo", "investimento", "atua", "limites"],
        "descricao": "Saiba o que é Agente Autônomo de Investimento (AAI), como atua, quais são os limites e a importância para investidores iniciantes",
        "temas_relacionados": []
    },
    {
        "id": "agente_de_compensacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agente de Compensacao", "Agente de Compensação"],
        "termos_busca": ["compensação", "agente", "instituição", "habilitada", "prestar", "serviços", "ligados", "liquidação"],
        "descricao": "É a instituição habilitada para prestar serviços ligados à liquidação de operações e oferta de garantias na venda e na compra de ações e demais valores mobiliários",
        "temas_relacionados": []
    },
    {
        "id": "agente_de_custodia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agente de Custodia", "Agente de Custódia"],
        "termos_busca": ["agente", "custódia", "quem", "guarda", "registra", "ativos"],
        "descricao": "Agente de custódia é quem guarda e registra ativos financeiros, para garantir segurança, controle e recebimento de proventos",
        "temas_relacionados": []
    },
    {
        "id": "agente_fiduciario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agente Fiduciario", "Agente Fiduciário"],
        "termos_busca": ["conheça", "papel", "fundamental", "agente", "fiduciário", "proteção"],
        "descricao": "Conheça o papel fundamental do agente fiduciário na proteção de investidores, as atribuições e quem pode atuar nessa função",
        "temas_relacionados": []
    },
    {
        "id": "agente_financeiro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agente Financeiro"],
        "termos_busca": ["financeiro", "agente", "instituição", "garantidora", "atua", "operações", "financeiras", "mercado"],
        "descricao": "É a instituição garantidora que atua com operações financeiras no mercado. Tais instituições são responsáveis pela análise e aprovação do financiamento, bem como pela negociação de garantias com o cliente, assumindo o risco de crédito junto a instituição financiadora.",
        "temas_relacionados": []
    },
    {
        "id": "agressao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agressao", "Agressão"],
        "termos_busca": ["agressão", "jargão", "mencionado", "lado", "mercado", "vendedor", "comprador"],
        "descricao": "Jargão mencionado quando um lado do mercado (vendedor ou comprador) executa ofertas na ponta oposta do mercado, aceitando o preço proposto, e perfazendo assim um negócio.",
        "temas_relacionados": []
    },
    {
        "id": "agulhada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Agulhada"],
        "termos_busca": ["agulhada", "movimento", "preço", "brusco", "rápido", "durante", "pregão"],
        "descricao": "Movimento de preço brusco e rápido durante o mesmo pregão, para baixo ou para cima, com retorno das cotações à condição anterior de forma igualmente rápida.",
        "temas_relacionados": []
    },
    {
        "id": "alavancagem_de_fundos_de_invest",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Alavancagem de Fundos de Invest.", "AFI"],
        "termos_busca": ["invest", "fundos", "alavancagem", "ação", "exposição", "financeira", "maior", "patrimônio"],
        "descricao": "É a ação de exposição financeira maior do que o patrimônio líquido do fundo de investimento, ocorrendo principalmente por operações com derivativos.",
        "temas_relacionados": []
    },
    {
        "id": "alavancagem_de_investimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Alavancagem de investimento"],
        "termos_busca": ["investimento", "alavancagem", "investir", "mercado", "financeiro", "além", "seria", "possível"],
        "descricao": "Investir no mercado financeiro além do que seria possível apenas com capital próprio",
        "temas_relacionados": []
    },
    {
        "id": "alavancagem_em_empresas",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Alavancagem em Empresas"],
        "termos_busca": ["empresas", "alavancagem", "estratégia", "utilizada", "potencializar", "retorno", "investimento", "projeto"],
        "descricao": "É uma estratégia utilizada para potencializar o retorno de um investimento ou projeto, utilizando-se de recursos externos, como empréstimos, financiamentos, ou mesmo derivativos.",
        "temas_relacionados": []
    },
    {
        "id": "alfa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Alfa"],
        "termos_busca": ["alfa", "termo", "utilizado", "descrever", "retorno", "superior", "índice"],
        "descricao": "Termo utilizado para descrever um retorno superior ao de um índice de referência, obtido por um investimento.",
        "temas_relacionados": []
    },
    {
        "id": "alianca_estrategica",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Alianca Estrategica", "Aliança Estratégica"],
        "termos_busca": ["estratégica", "aliança", "acordo", "estabelecido", "companhias", "buscando", "benefícios", "mútuos"],
        "descricao": "É um acordo estabelecido entre companhias buscando benefícios mútuos a partir da união de recursos disponíveis. Nesse caso, as empresas envolvidas se mantêm independentes usufruindo da sinergia produzida pela aliança estabelecida.",
        "temas_relacionados": []
    },
    {
        "id": "alienacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Alienacao", "Alienação"],
        "termos_busca": ["alienação", "transferência", "cessão", "bens"],
        "descricao": "Transferência ou cessão de bens.",
        "temas_relacionados": []
    },
    {
        "id": "alocacao_da_carteira",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Alocacao da Carteira", "Alocação da Carteira"],
        "termos_busca": ["alocação", "estratégia", "objetivo", "principal", "proporcionar", "carteira", "estável"],
        "descricao": "É a estratégia que tem o objetivo principal de proporcionar uma carteira mais estável, que protege contra riscos ao mesmo tempo em que almeja rentabilidade.",
        "temas_relacionados": []
    },
    {
        "id": "altcoin",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Altcoin"],
        "termos_busca": ["altcoin", "conheça", "criptomoedas", "prometem", "inovação", "além", "bitcoin"],
        "descricao": "Conheça criptomoedas que prometem inovação além do Bitcoin, com preços acessíveis e potencial de crescimento",
        "temas_relacionados": []
    },
    {
        "id": "analise_de_indicadores",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise de Indicadores", "Análise de Indicadores"],
        "termos_busca": ["indicadores", "análise", "desempenho", "empresa", "base", "resultado", "alguns"],
        "descricao": "Análise do desempenho de uma empresa com base no resultado de alguns indicadores, que podem ser agrupados como: indicadores de atividade, de estrutura de capital, de liquidez, e de rentabilidade. Em geral estes indicadores são calculados com base nos dados...",
        "temas_relacionados": []
    },
    {
        "id": "analise_de_risco",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise de Risco", "Análise de Risco"],
        "termos_busca": ["análise", "risco", "processo", "sistemático", "avalia", "probabilidade"],
        "descricao": "A análise de risco é o processo sistemático que avalia a probabilidade real de fenômenos adversos que possam apresentar não conformidade em um cenário socioeconômico durante a execução de projetos ou qualquer atividade.",
        "temas_relacionados": []
    },
    {
        "id": "analise_de_sensitividade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise de Sensitividade", "Análise de Sensitividade"],
        "termos_busca": ["sensitividade", "análise", "sensibilidade", "procura", "estimar", "efeitos", "mudanças"],
        "descricao": "Ou análise de sensibilidade, é a análise que procura estimar quais efeitos as mudanças de parâmetros podem ter sobre a projeção de resultado de uma empresa ou projeto",
        "temas_relacionados": []
    },
    {
        "id": "analise_de_viabilidade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise de Viabilidade", "Análise de Viabilidade"],
        "termos_busca": ["viabilidade", "análise", "estudo", "avalia", "possibilidade", "sucesso", "projeto", "utilizando"],
        "descricao": "Estudo que avalia a possibilidade de sucesso de um projeto utilizando determinadas premissas, e cuja finalidade é servir de apoio à decisão sobre implementação.",
        "temas_relacionados": []
    },
    {
        "id": "analise_do_ponto_de_equilibrio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise do Ponto de Equilibrio", "Análise do Ponto de Equilíbrio", "APE"],
        "termos_busca": ["equilíbrio", "ponto", "análise", "consiste", "indicador", "mostra", "quanto", "empresa"],
        "descricao": "Consiste em um indicador que mostra o quanto a empresa precisa vender para que possa ultrapassar o valor de seus custos indicando assim o valor mínimo necessário de seu faturamento.",
        "temas_relacionados": []
    },
    {
        "id": "analise_financeira",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise Financeira", "Análise Financeira"],
        "termos_busca": ["financeira", "análise", "metodologias", "usadas", "analistas", "verificar", "situação", "empresa"],
        "descricao": "Uma das metodologias usadas pelos analistas para verificar a situação de uma empresa. Esta metodologia se baseia na análise dos demonstrativos financeiros (balanço patrimonial, demonstrativo de resultado e demonstração de origens e recursos) de uma empresa, com o objetivo de...",
        "temas_relacionados": []
    },
    {
        "id": "analise_horizontal_ou_ah",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise Horizontal ou AH", "Análise Horizontal ou AH"],
        "termos_busca": ["horizontal", "análise", "variação", "período", "indicada", "porcentagem", "determinada", "linha"],
        "descricao": "Variação do período, indicada em porcentagem, de determinada linha do resultado ou do balanço patrimonial.",
        "temas_relacionados": []
    },
    {
        "id": "analise_marginal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise Marginal", "Análise Marginal"],
        "termos_busca": ["marginal", "análise", "relação", "custos", "empresa", "visando", "aumento", "lucratividade"],
        "descricao": "É a relação entre os custos de uma empresa visando o aumento de sua lucratividade",
        "temas_relacionados": []
    },
    {
        "id": "analise_vertical_ou_av",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Analise Vertical ou AV", "Análise Vertical ou AV"],
        "termos_busca": ["vertical", "análise", "feita", "demonstrativos", "contábeis", "empresa", "verificar"],
        "descricao": "Análise feita nos demonstrativos contábeis de uma empresa para se verificar a participação percentual de cada item em relação ao resultado total.",
        "temas_relacionados": []
    },
    {
        "id": "anbima_associacao_brasileira_das_entidades_dos_mercados_financeiro_e_de_capitais",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ANBIMA (Associacao Brasileira das Entidades dos Mercados Financeiro e de Capitais)", "ANBIMA (Associação Brasileira das Entidades dos Mercados Financeiro e de Capitais)", "Associacao Brasileira das Entidades dos Mercados Financeiro e de Capitais", "Associação Brasileira das Entidades dos Mercados Financeiro e de Capitais", "ANBIMA"],
        "termos_busca": ["capitais", "mercados", "dos", "entidades", "das", "brasileira", "associação", "anbima"],
        "descricao": "Saiba o que é, sua importância para o mercado financeiro brasileiro e como a entidade promove boas práticas, autorregulação e educação no setor",
        "temas_relacionados": []
    },
    {
        "id": "ancord_associacao_nacional_das_corretoras_e_distribuidoras_de_titulos_e_valores_mobiliarios_cambio_e_mercadorias",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ANCORD (Associacao Nacional das Corretoras e Distribuidoras de Titulos e Valores Mobiliarios, Cambio e Mercadorias)", "ANCORD (Associação Nacional das Corretoras e Distribuidoras de Títulos e Valores Mobiliários, Câmbio e Mercadorias)", "Associacao Nacional das Corretoras e Distribuidoras de Titulos e Valores Mobiliarios, Cambio e Mercadorias", "Associação Nacional das Corretoras e Distribuidoras de Títulos e Valores Mobiliários, Câmbio e Mercadorias", "ANCORD"],
        "termos_busca": ["mercadorias", "câmbio", "mobiliários", "valores", "títulos", "das", "nacional", "associação"],
        "descricao": "Entidade representa corretoras e distribuidoras no mercado de capitais",
        "temas_relacionados": []
    },
    {
        "id": "andar_de_lado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Andar de Lado"],
        "termos_busca": ["lado", "andar", "ação", "apresenta", "tendência", "alta", "baixa"],
        "descricao": "Quando a ação não apresenta tendência de alta ou baixa.",
        "temas_relacionados": []
    },
    {
        "id": "anuncio_de_encerramento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Anuncio de Encerramento", "Anúncio de Encerramento"],
        "termos_busca": ["anúncio", "informando", "acerca", "encerramento", "oferta", "coordenadores"],
        "descricao": "Anúncio informando acerca do encerramento da Oferta pelos Coordenadores e pela Companhia, nos termos da Instrução CVM 400.",
        "temas_relacionados": []
    },
    {
        "id": "anuncio_de_inicio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Anuncio de Inicio", "Anúncio de Início"],
        "termos_busca": ["anúncio", "informando", "acerca", "início", "oferta", "coordenadores"],
        "descricao": "Anúncio informando acerca do início da Oferta pelos Coordenadores e pela Companhia, nos termos da Instrução CVM 400.",
        "temas_relacionados": []
    },
    {
        "id": "anuncio_de_retificacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Anuncio de Retificacao", "Anúncio de Retificação"],
        "termos_busca": ["retificação", "anúncio", "informando", "acerca", "revogação", "modificação", "oferta"],
        "descricao": "Anúncio informando acerca da revogação ou modificação da Oferta pelos coordenadores",
        "temas_relacionados": []
    },
    {
        "id": "api",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["API"],
        "termos_busca": ["api", "significa", "application", "programming", "interface", "programação", "aplicação"],
        "descricao": "API significa Application Programming Interface (Interface de Programação de Aplicação).",
        "temas_relacionados": []
    },
    {
        "id": "aplicacao_minima",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Aplicacao Minima", "Aplicação Mínima"],
        "termos_busca": ["mínima", "aplicação", "valor", "mínimo", "necessário", "investimento", "determinado", "produto"],
        "descricao": "Valor mínimo necessário para o investimento em um determinado produto financeiro.",
        "temas_relacionados": []
    },
    {
        "id": "aplicacoes_financeiras",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Aplicacoes Financeiras", "Aplicações Financeiras"],
        "termos_busca": ["financeiras", "aplicações", "formas", "disponibilidades", "recursos", "espécie", "objetivo", "gerar"],
        "descricao": "São todas as formas de disponibilidades de recursos em espécie com o objetivo de gerar retorno financeiro ao seu titular ao longo de determinado período de tempo",
        "temas_relacionados": []
    },
    {
        "id": "apolice",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Apolice", "Apólice"],
        "termos_busca": ["apólice", "termo", "usado", "indústria", "seguros", "denomina", "documento"],
        "descricao": "Termo usado na indústria de seguros, que denomina o documento mais importante na hora em que se contrata um seguro. Isto porque a emissão da apólice implica na aceitação da proposta e do contrato de seguro por parte da seguradora....",
        "temas_relacionados": []
    },
    {
        "id": "apregoacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Apregoacao", "Apregoação"],
        "termos_busca": ["apregoação", "divulgar", "anunciar", "intenção", "compra", "venda", "bens"],
        "descricao": "Ato de divulgar e anunciar a intenção de compra ou venda de bens ou ativos mobiliários.",
        "temas_relacionados": []
    },
    {
        "id": "aprendizado_organizacional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Aprendizado Organizacional"],
        "termos_busca": ["organizacional", "aprendizado", "termo", "usado", "definir", "questionamento", "avaliação", "inovação"],
        "descricao": "Termo usado para definir o questionamento, avaliação e inovação das práticas de gestão e padrões de trabalho",
        "temas_relacionados": []
    },
    {
        "id": "arbitrador",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Arbitrador"],
        "termos_busca": ["arbitrador", "participante", "mercado", "tanto", "vista", "mercados", "futuros"],
        "descricao": "Participante de mercado tanto no mercado à vista como em mercados futuros de compra e venda de ativos financeiros que visa se beneficiar do diferencial de preços realizando a arbitragem",
        "temas_relacionados": []
    },
    {
        "id": "arbitragem",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Arbitragem"],
        "termos_busca": ["arbitragem", "estratégia", "busca", "lucro", "partir", "diferenças", "preço"],
        "descricao": "Estratégia que busca lucro a partir de diferenças de preço de um mesmo ativo em mercados distintos, com operações simultâneas",
        "temas_relacionados": []
    },
    {
        "id": "area_bruta_locavel_abl",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Area Bruta Locavel (ABL)", "Área Bruta Locável (ABL)", "Area Bruta Locavel", "Área Bruta Locável", "ABL"],
        "termos_busca": ["abl", "locável", "bruta", "área", "empreendimento", "imobiliário", "está", "disponível"],
        "descricao": "É a área de um empreendimento imobiliário que está disponível para locação. Sua medida é feita em m² (metros quadrados).",
        "temas_relacionados": []
    },
    {
        "id": "arpu",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ARPU"],
        "termos_busca": ["arpu", "average", "revenue", "user", "receita", "média", "usuário"],
        "descricao": "“Average Revenue Per User”, ou “Receita Média Por Usuário”, é um indicador financeiro normalmente utilizado por empresas que oferecem serviços por assinatura a seus clientes.",
        "temas_relacionados": []
    },
    {
        "id": "arranjo_de_pagamento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Arranjo de Pagamento"],
        "termos_busca": ["pagamento", "arranjo", "segundo", "conjunto", "regras", "procedimentos", "disciplina", "prestação"],
        "descricao": "Segundo a Lei 12.865, de 2013, é conjunto de regras e procedimentos que disciplina a prestação de determinado serviço de pagamento ao público aceito por mais de um recebedor, mediante acesso direto pelos usuários finais, pagadores e recebedores.",
        "temas_relacionados": []
    },
    {
        "id": "assembleia_geral_extraordinaria_age",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Assembleia Geral Extraordinaria (AGE)", "Assembleia Geral Extraordinária (AGE)", "Assembleia Geral Extraordinaria", "Assembleia Geral Extraordinária", "AGE"],
        "termos_busca": ["age", "extraordinária", "geral", "assembleia", "reunião", "acionistas", "convocação", "obrigatória"],
        "descricao": "Reunião de acionistas, de convocação não obrigatória, convocada na forma da lei e dos estatutos, a fim de deliberar sobre qualquer matéria de interesse da sociedade.",
        "temas_relacionados": []
    },
    {
        "id": "assembleia_geral_ordinaria_ago",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Assembleia Geral Ordinaria (AGO)", "Assembleia Geral Ordinária (AGO)", "Assembleia Geral Ordinaria", "Assembleia Geral Ordinária", "AGO"],
        "termos_busca": ["ago", "ordinária", "geral", "assembleia", "reunião", "acionistas", "convocada", "obrigatoriamente"],
        "descricao": "Reunião de acionistas convocada obrigatoriamente pela diretoria de uma sociedade anônima para verificação dos resultados, leitura, discussão e votação dos relatórios de diretoria e eleição do conselho fiscal da diretoria. Deve ser realizada até quatro meses após o encerramento do...",
        "temas_relacionados": []
    },
    {
        "id": "asset_allocation",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Asset Allocation"],
        "termos_busca": ["allocation", "asset", "expressão", "inglês", "significa", "alocação", "recursos", "usada"],
        "descricao": "Expressão em inglês que significa alocação de recursos. Usada para designar a escolha dos ativos que irão compor uma carteira de investimentos.",
        "temas_relacionados": []
    },
    {
        "id": "assets",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Assets"],
        "termos_busca": ["assets", "termo", "inglês", "ativos"],
        "descricao": "Termo em inglês para ativos",
        "temas_relacionados": []
    },
    {
        "id": "ativo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativo"],
        "termos_busca": ["ativo", "termo", "determina", "itens", "valor", "possuídos", "empresa"],
        "descricao": "Termo que determina itens de valor possuídos por uma empresa ou indivíduos (assets)",
        "temas_relacionados": []
    },
    {
        "id": "ativo_circulante",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativo Circulante"],
        "termos_busca": ["circulante", "ativo", "balanço", "patrimonial", "empresa", "direito", "convertido", "recursos"],
        "descricao": "Parte do balanço patrimonial da empresa, é um bem ou direito que pode ser convertido em recursos em um curto prazo de tempo (em até 12 meses).",
        "temas_relacionados": []
    },
    {
        "id": "ativo_imobilizado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativo Imobilizado"],
        "termos_busca": ["imobilizado", "ativo", "balanço", "patrimonial", "empresa", "formado", "conjunto", "bens"],
        "descricao": "Parte do balanço patrimonial da empresa, é formado pelo conjunto de bens e direitos necessários à manutenção das suas atividades operacionais.",
        "temas_relacionados": []
    },
    {
        "id": "ativo_permanente",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativo Permanente"],
        "termos_busca": ["permanente", "ativo", "balanço", "patrimonial", "empresa", "formado", "soma", "ativos"],
        "descricao": "Parte do balanço patrimonial da empresa, é formado pela soma dos ativos imobilizados. Segundo a Lei 11.638/2007, o ativo permanente passou a ser chamado de ativo não circulante.",
        "temas_relacionados": []
    },
    {
        "id": "ativo_ponderado_pelo_risco_apr",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativo Ponderado pelo Risco (APR)", "Ativo Ponderado pelo Risco", "APR"],
        "termos_busca": ["apr", "risco", "pelo", "ponderado", "ativo", "segundo", "banco", "central"],
        "descricao": "Segundo o Banco Central do Brasil, APR consiste na soma ponderada dos ativos das instituições, de acordo com seu nível de risco, assim definido pelo Acordo de Basileia.",
        "temas_relacionados": []
    },
    {
        "id": "ativo_rentavel",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativo Rentavel", "Ativo Rentável"],
        "termos_busca": ["rentável", "ativo", "termo", "utilizado", "instituições", "financeiras", "refletindo", "soma"],
        "descricao": "Termo utilizado pelas instituições financeiras refletindo a soma dos ativos que geram retorno financeiro para a instituição ou participante do mercado financeiro.",
        "temas_relacionados": []
    },
    {
        "id": "ativoobjeto",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativo-Objeto"],
        "termos_busca": ["objeto", "ativo", "negociado", "contrato", "futuro", "opções", "chamado"],
        "descricao": "Ativo sobre o qual é negociado o contrato futuro ou as opções. Também chamado ativo subjacente.",
        "temas_relacionados": []
    },
    {
        "id": "ativos_financeiros",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativos financeiros"],
        "termos_busca": ["financeiros", "ativos", "conheça", "categorias", "características", "importância", "desses", "instrumentos"],
        "descricao": "Conheça categorias, características e importância desses instrumentos para a gestão de investimentos e a economia.",
        "temas_relacionados": []
    },
    {
        "id": "ativos_intangiveis",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ativos Intangiveis", "Ativos Intangíveis"],
        "termos_busca": ["intangíveis", "ativos", "representação", "física", "imediata", "tais", "patentes"],
        "descricao": "São os ativos sem representação física imediata, tais como as patentes, franquias, marcas, etc.",
        "temas_relacionados": []
    },
    {
        "id": "atuario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Atuario", "Atuário"],
        "termos_busca": ["atuário", "profissional", "especializado", "avaliar", "administrar", "riscos", "consequências"],
        "descricao": "É o profissional especializado em avaliar e administrar riscos com consequências financeiras adversas.",
        "temas_relacionados": []
    },
    {
        "id": "audiencia_publica",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Audiencia Publica", "Audiência Pública"],
        "termos_busca": ["audiência", "reunião", "pública", "comunicação", "discussão", "determinados", "assuntos"],
        "descricao": "Reunião pública para comunicação e discussão de determinados assuntos entre diversos setores da sociedade e as autoridades públicas.",
        "temas_relacionados": []
    },
    {
        "id": "aumento_de_capital",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Aumento de Capital"],
        "termos_busca": ["aumento", "mudanças", "estrutura", "capital", "empresa", "ocorrem", "meio"],
        "descricao": "Mudanças na estrutura de capital de uma empresa que ocorrem por meio da incorporação de novos recursos ou reservas, como o aportes dos seus acionistas, emissão de novas ações no mercado, etc.",
        "temas_relacionados": []
    },
    {
        "id": "aumento_do_valor_nominal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Aumento do Valor Nominal", "AVN"],
        "termos_busca": ["aumento", "alteração", "valor", "nominal", "ação", "empresa", "decorrente"],
        "descricao": "Alteração do valor nominal da ação de uma empresa, decorrente da incorporação de reservas de capital sem que sejam emitidas novas ações.",
        "temas_relacionados": []
    },
    {
        "id": "auto_patrocinio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Auto Patrocinio", "Auto Patrocínio"],
        "termos_busca": ["patrocínio", "auto", "opção", "direito", "proporciona", "participante", "desligado", "empresa"],
        "descricao": "É a opção ou direito que proporciona ao participante, desligado de empresa por qualquer que seja o motivo, permanecer no plano de previdência complementar, até atingir as condições necessárias para a aposentadoria.",
        "temas_relacionados": []
    },
    {
        "id": "autorizacao_de_faturamento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Autorizacao de Faturamento", "Autorização de Faturamento"],
        "termos_busca": ["autorização", "utilizada", "empresas", "consórcios", "faturamento", "favor"],
        "descricao": "É a autorização utilizada pelas empresas de consórcios para faturamento do bem em favor do consorciado contemplado",
        "temas_relacionados": []
    },
    {
        "id": "autorregulacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Autorregulacao", "Autorregulação"],
        "termos_busca": ["autorregulação", "estabelecimento", "verificação", "regras", "feitas", "pessoas", "entidades"],
        "descricao": "Estabelecimento ou verificação de regras feitas pelas pessoas ou entidades que serão alvo de regulação.",
        "temas_relacionados": []
    },
    {
        "id": "aval",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Aval"],
        "termos_busca": ["aval", "garantia", "cambial", "autônoma", "meio", "avalista", "torna"],
        "descricao": "É a garantia cambial e autônoma, por meio da qual o avalista se torna responsável pelo pagamento de um título de crédito nas mesmas condições de avalizado, vinculando-se diretamente ao credor.",
        "temas_relacionados": []
    },
    {
        "id": "average_hourly_earnings",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Average Hourly Earnings", "AHE"],
        "termos_busca": ["earnings", "hourly", "average", "ganho", "médio", "hora", "mede", "mudança"],
        "descricao": "É o Ganho Médio por Hora que mede a mudança no preço que as empresas pagam pelo trabalho, não incluindo o setor agrícola.",
        "temas_relacionados": []
    },
    {
        "id": "average_workweek",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Average Workweek"],
        "termos_busca": ["workweek", "average", "semana", "trabalho", "média", "medida", "horas", "trabalhadas"],
        "descricao": "Semana de Trabalho Média. Medida de horas trabalhadas utilizada para comparação entre países podendo variar entre 40 horas a 50 horas. A duração da semana de trabalho varia muito de um setor para outro e de um país para outro.",
        "temas_relacionados": []
    },
    {
        "id": "averbacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Averbacao", "Averbação"],
        "termos_busca": ["averbação", "termo", "utilizado", "contratos", "seguros", "transportes", "denominando"],
        "descricao": "Termo utilizado nos contratos de seguros de transportes denominando o documento usado pelo segurado para informar a seguradora sobre verbas e objetos usados para garantir apólices em aberto.",
        "temas_relacionados": []
    },
    {
        "id": "averbadora",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Averbadora"],
        "termos_busca": ["averbadora", "instituição", "contratar", "plano", "previdência", "privada", "funcionários"],
        "descricao": "É a instituição que, ao contratar um plano de previdência privada para os seus funcionários, não participa do seu custeamento, ao contrario da instituição patrocinadora.",
        "temas_relacionados": []
    },
    {
        "id": "aviso_ao_mercado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Aviso ao Mercado"],
        "termos_busca": ["mercado", "aviso", "divulgação", "pública", "informação", "emitida", "companhia", "coordenadores"],
        "descricao": "Divulgação pública de informação emitida por uma Companhia ou pelos Coordenadores de uma oferta pública, nos termos da Instrução CVM 400.",
        "temas_relacionados": []
    },
    {
        "id": "b3_sa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["B3 S/A"],
        "termos_busca": ["bolsa", "valores", "brasil", "responsável", "viabilizar", "negociação"],
        "descricao": "B3 S/A é a bolsa de valores do Brasil, responsável por viabilizar a negociação de ações, FIIs, derivativos e renda fixa",
        "temas_relacionados": []
    },
    {
        "id": "bacen_8211_banco_central_do_brasil_bc",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["BACEN", "Banco Central do Brasil", "BCB"],
        "termos_busca": ["brasil", "central", "banco", "bacen", "instituição", "regula", "sistema", "financeiro"],
        "descricao": "Instituição regula o sistema financeiro, emite moeda e é responsável pela estabilidade econômica",
        "temas_relacionados": []
    },
    {
        "id": "back_office",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Back Office"],
        "termos_busca": ["office", "back", "área", "responsável", "liquidação", "compensação", "contabilização", "registro"],
        "descricao": "Área responsável pela liquidação, compensação, contabilização, registro e custódia das operações realizadas por uma instituição financeira.",
        "temas_relacionados": []
    },
    {
        "id": "banco_comercial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Banco Comercial"],
        "termos_busca": ["comercial", "banco", "bancos", "comerciais", "funções", "história", "importância", "sistema"],
        "descricao": "O que são bancos comerciais, suas funções, história e importância no sistema financeiro",
        "temas_relacionados": []
    },
    {
        "id": "banco_cooperativo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Banco Cooperativo"],
        "termos_busca": ["cooperativo", "banco", "bancos", "cooperativos", "integram", "cooperativas", "crédito", "oferecem"],
        "descricao": "Bancos cooperativos integram cooperativas de crédito, oferecem produtos bancários, suporte tecnológico e governança compartilhada para promover inclusão e desenvolvimento",
        "temas_relacionados": []
    },
    {
        "id": "banco_de_desenvolvimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Banco de Desenvolvimento"],
        "termos_busca": ["banco", "bancos", "desenvolvimento", "financiam", "projetos", "longo", "prazo"],
        "descricao": "Bancos de desenvolvimento financiam projetos de longo prazo, fomentam inovação e infraestrutura e reduzem desigualdades regionais",
        "temas_relacionados": []
    },
    {
        "id": "banco_de_investimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Banco de Investimento"],
        "termos_busca": ["entenda", "banco", "investimento", "principais", "funções", "exemplos"],
        "descricao": "Entenda o que é um banco de investimento, principais funções, exemplos no Brasil e no exterior e o papel que exerce na economia",
        "temas_relacionados": []
    },
    {
        "id": "banco_multiplo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Banco Multiplo", "Banco Múltiplo"],
        "termos_busca": ["múltiplo", "segundo", "banco", "central", "brasil", "instituição", "financeira"],
        "descricao": "Segundo o Banco Central do Brasil, é a instituição financeira privada ou pública que realiza as operações ativas, passivas e acessórias das diversas instituições financeiras, por intermédio das seguintes carteiras: comercial, de investimento e/ou de desenvolvimento, de crédito imobiliário, de...",
        "temas_relacionados": []
    },
    {
        "id": "base_monetaria",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Base Monetaria", "Base Monetária"],
        "termos_busca": ["base", "monetária", "total", "dinheiro", "circulação", "reservas"],
        "descricao": "Base monetária é total de dinheiro em circulação e reservas bancárias, essencial para controle da inflação e política monetária",
        "temas_relacionados": []
    },
    {
        "id": "bater",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Bater"],
        "termos_busca": ["bater", "vender", "seja", "fechar", "negócio", "melhor", "oferta"],
        "descricao": "Mesmo que vender, ou seja, fechar negócio com a melhor oferta de compra disponível",
        "temas_relacionados": []
    },
    {
        "id": "bc_bcb_bacen",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["BC, BCB, BACEN", "BBB"],
        "termos_busca": ["bacen", "bcb", "siglas", "correspondentes", "banco", "central", "brasil", "respectivamente"],
        "descricao": "Siglas correspondentes a Banco Central e a Banco Central do Brasil, respectivamente.",
        "temas_relacionados": []
    },
    {
        "id": "bear_market_urso",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Bear Market (urso)", "Bear Market", "urso"],
        "termos_busca": ["urso", "market", "bear", "mercado", "ações", "indica", "tendência", "queda"],
        "descricao": "No mercado de ações, indica tendência de queda. Termo comparado ao movimento de ataque do urso, feito de cima para baixo.",
        "temas_relacionados": []
    },
    {
        "id": "benchmark_1",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Benchmark (1)"],
        "termos_busca": ["benchmark", "padrão", "referência", "utilizado", "comparar", "rentabilidade", "investimentos"],
        "descricao": "Padrão de referência utilizado para comparar rentabilidade entre investimentos, títulos, taxas de juros.",
        "temas_relacionados": []
    },
    {
        "id": "benchmark_2",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Benchmark (2)"],
        "termos_busca": ["benchmark", "termo", "inglês", "processo", "comparação", "produtos", "serviços"],
        "descricao": "Termo em inglês para processo de comparação de produtos, serviços e práticas empresariais. Índice de referência.",
        "temas_relacionados": []
    },
    {
        "id": "beneficiario_final",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Beneficiario Final", "Beneficiário Final"],
        "termos_busca": ["final", "beneficiário", "segundo", "instrução", "pessoa", "natural", "pessoas", "naturais"],
        "descricao": "Segundo a Instrução CVM 617/2019, é a pessoa natural ou pessoas naturais que, em conjunto, possuam, controlem ou influenciem significativamente, direta ou indiretamente, um cliente em nome do qual uma transação esteja sendo conduzida ou dela se beneficie.",
        "temas_relacionados": []
    },
    {
        "id": "beneficio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Beneficio", "Benefício"],
        "termos_busca": ["benefício", "segundo", "susep", "pagamento", "beneficiários", "recebem", "função"],
        "descricao": "Segundo a Susep, é o pagamento que os beneficiários recebem em função da ocorrência do evento gerador durante o período de cobertura;",
        "temas_relacionados": []
    },
    {
        "id": "black_swans",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Black swans"],
        "termos_busca": ["entenda", "black", "swans", "eventos", "imprevisíveis", "grande"],
        "descricao": "Entenda os Black Swans, eventos imprevisíveis de grande impacto, e como eles afetam os mercados e decisões financeiras.",
        "temas_relacionados": []
    },
    {
        "id": "bndes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["BNDES"],
        "termos_busca": ["bndes", "banco", "nacional", "desenvolvimento", "econômico", "social", "empresa"],
        "descricao": "Banco Nacional de Desenvolvimento Econômico e Social. Empresa pública federal, é o principal instrumento de financiamento de longo prazo para a realização de investimentos em todos os segmentos da economia, em uma política que inclui as dimensões social, regional e...",
        "temas_relacionados": []
    },
    {
        "id": "boletar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Boletar"],
        "termos_busca": ["entenda", "boletar", "mercado", "financeiro", "funciona", "envio"],
        "descricao": "Entenda o que é boletar no mercado financeiro, como funciona o envio de ordens e quando usar na prática.",
        "temas_relacionados": []
    },
    {
        "id": "bombar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Bombar"],
        "termos_busca": ["bombar", "disparada", "positiva", "cotações", "determinado", "ativo", "mercado"],
        "descricao": "Disparada positiva nas cotações de determinado ativo ( mercado em alta)",
        "temas_relacionados": []
    },
    {
        "id": "bonificacoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Bonificacoes", "Bonificações"],
        "termos_busca": ["bonificações", "distribuição", "remuneração", "novas", "ações", "proporcionais", "capital"],
        "descricao": "Distribuição ou remuneração de novas ações proporcionais ao capital investido pelos acionistas de uma empresa.",
        "temas_relacionados": []
    },
    {
        "id": "bonus",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Bonus", "Bônus"],
        "termos_busca": ["bônus", "obrigações", "renda", "fixa", "emitidas", "empresas", "bancos"],
        "descricao": "São obrigações de renda fixa emitidas por empresas, bancos ou governos em que o emissor se compromete a pagar juros predeterminados durante um período de tempo e o seu montante da emissão na data de vencimento.",
        "temas_relacionados": []
    },
    {
        "id": "bonus_de_subscricao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Bonus de Subscricao", "Bônus de Subscrição"],
        "termos_busca": ["subscrição", "bônus", "segundo", "títulos", "negociáveis", "emitidos", "sociedades", "ações"],
        "descricao": "Segundo a CVM, são títulos negociáveis emitidos por sociedades por ações, que conferem aos seus titulares, nas condições constantes do certificado, o direito de subscrever ações do capital social da companhia, dentro do limite de capital autorizado no estatuto.",
        "temas_relacionados": []
    },
    {
        "id": "bonus_soberano",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Bonus Soberano", "Bônus Soberano"],
        "termos_busca": ["soberano", "bônus", "títulos", "emissão", "publica", "país", "região", "garantidas"],
        "descricao": "Títulos de emissão publica de um país ou região garantidas pelo governo central.",
        "temas_relacionados": []
    },
    {
        "id": "br_gaap",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["BR GAAP"],
        "termos_busca": ["gaap", "segundo", "conselho", "federal", "contabilidade", "práticas", "contábeis"],
        "descricao": "Segundo o Conselho Federal de Contabilidade (CFC), são as práticas contábeis adotadas no Brasil, as quais são baseadas na Lei das Sociedades por Ações, nas normas e regulamentos da CVM e nas normas contábeis emitidas pelo IBRACON, pelo CFC e...",
        "temas_relacionados": []
    },
    {
        "id": "breakeven",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Break-Even"],
        "termos_busca": ["even", "break", "ponto", "equilíbrio", "igualam", "receitas", "despesas", "finanças"],
        "descricao": "Ponto de equilíbrio, no qual igualam-se receitas e despesas. Em finanças, pode ser entendido como o preço em que um investimento não gera lucro nem prejuízo.",
        "temas_relacionados": []
    },
    {
        "id": "breakeven_b3",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Breakeven"],
        "termos_busca": ["entenda", "breakeven", "ajuda", "avaliar", "viabilidade", "negócios"],
        "descricao": "Entenda o que é breakeven, como ajuda a avaliar a viabilidade de negócios e investimentos e saiba como calcular o ponto de equilíbrio",
        "temas_relacionados": []
    },
    {
        "id": "breakout",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Breakout"],
        "termos_busca": ["breakout", "momento", "serve", "oportunidade", "maiores", "lucros", "mercado"],
        "descricao": "Momento serve de oportunidade para maiores lucros no mercado, mas há riscos; entenda",
        "temas_relacionados": []
    },
    {
        "id": "built_to_suit_bts",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Built to Suit (BTS)", "Built to Suit", "BTS"],
        "termos_busca": ["bts", "suit", "built", "operação", "imobiliária", "longo", "prazo", "locatário"],
        "descricao": "É uma operação imobiliária de longo prazo, no qual o locatário contrata a construção para atender suas necessidades por um longo período depois de pronto",
        "temas_relacionados": []
    },
    {
        "id": "bull_ou_bullish",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Bull ou Bullish"],
        "termos_busca": ["bullish", "bull", "contrário", "bear", "referência", "ataque", "touro", "feito"],
        "descricao": "É o contrário de” bear”. Faz referência ao ataque do touro, feito de baixo para cima. Significa que a Bolsa está em tendência de alta.",
        "temas_relacionados": []
    },
    {
        "id": "buy_038_hold",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Buy & Hold", "buy and hold", "B&H"],
        "termos_busca": ["buy", "hold", "estratégia", "comprar", "manter", "ativos", "qualidade"],
        "descricao": "Buy & Hold é estratégia de comprar e manter ativos de qualidade no longo prazo, com foco em crescimento patrimonial e geração de renda com dividendos",
        "temas_relacionados": []
    },
    {
        "id": "buy_to_lease",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Buy to Lease"],
        "termos_busca": ["buy", "lease", "modelo", "investimento", "imobiliário", "voltado", "geração"],
        "descricao": "Buy to Lease é modelo de investimento imobiliário voltado para geração de renda passiva por meio do aluguel de imóveis; entenda como funciona e avalie vantagens e desafios",
        "temas_relacionados": []
    },
    {
        "id": "cadastro_de_credito",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cadastro de Credito", "Cadastro de Crédito"],
        "termos_busca": ["cadastro", "bancos", "dados", "armazenadores", "informações", "histórico", "crédito"],
        "descricao": "Bancos de dados armazenadores de informações sobre o histórico de crédito de pessoas físicas e jurídicas, a fim de possibilitar a decisão sobre conceder ou não um crédito.",
        "temas_relacionados": []
    },
    {
        "id": "caderneta_de_poupanca",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Caderneta de Poupanca", "Caderneta de Poupança"],
        "termos_busca": ["caderneta", "deposito", "poupança", "conta", "bancária", "oferecida", "instituições"],
        "descricao": "O deposito de poupança é uma conta bancária, oferecida por instituições financeiras (bancos comerciais ou múltiplos com carteira comercial). E uma forma de investimento popular de baixo risco com rendimentos mensais, isentos de imposto de renda para a pessoa física...",
        "temas_relacionados": []
    },
    {
        "id": "cadinf",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CADINF"],
        "termos_busca": ["cadinf", "cadastro", "instituições", "financeiras", "contendo", "dados", "sujeitas"],
        "descricao": "Cadastro de Instituições Financeiras. Cadastro contendo dados das instituições sujeitas a fiscalização ou controle do Banco Central do Brasil.",
        "temas_relacionados": []
    },
    {
        "id": "cagr",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CAGR"],
        "termos_busca": ["entenda", "cagr", "taxa", "crescimento", "anual", "composta"],
        "descricao": "Entenda CAGR, a taxa de crescimento anual composta, sua fórmula, cálculo passo a passo e importância em finanças e investimentos",
        "temas_relacionados": []
    },
    {
        "id": "camara_de_compensacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Camara de Compensacao", "Câmara de Compensação"],
        "termos_busca": ["compensação", "câmara", "mecanismo", "centralizador", "operações", "interpõe", "participantes", "troca"],
        "descricao": "É um mecanismo centralizador de operações que se interpõe entre seus participantes para troca de obrigações financeiras podendo ser com contraparte central garantidora ou sem contraparte central garantidora.",
        "temas_relacionados": []
    },
    {
        "id": "cambio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cambio", "Câmbio"],
        "termos_busca": ["câmbio", "tipos", "funciona", "impacto", "economia", "saiba", "diferença"],
        "descricao": "O que é, tipos, como funciona e qual o impacto na economia? Saiba a diferença entre câmbio comercial e turismo",
        "temas_relacionados": []
    },
    {
        "id": "capex_capital_expenditure",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CAPEX (Capital Expenditure)", "Capital Expenditure", "CAPEX"],
        "termos_busca": ["expenditure", "entenda", "conceito", "capex", "despesa", "capital", "relevância"],
        "descricao": "Entenda o conceito de CAPEX (Despesa de Capital), sua relevância para o crescimento empresarial, influência nas finanças e diferenças em relação ao OPEX (Despesa Operacional)",
        "temas_relacionados": []
    },
    {
        "id": "capital_de_risco",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Capital de Risco"],
        "termos_busca": ["risco", "conhecido", "venture", "capital", "investimento", "limita", "apenas"],
        "descricao": "Também conhecido como venture capital, este tipo de investimento não se limita apenas à injeção de recursos financeiros; representa uma parceria estratégica entre investidores e empreendedores, destinada a impulsionar o crescimento acelerado e a transformação de ideias promissoras em realidades...",
        "temas_relacionados": []
    },
    {
        "id": "capital_proprio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Capital Proprio", "Capital Próprio"],
        "termos_busca": ["capital", "próprio", "pessoa", "jurídica", "representando", "valores"],
        "descricao": "É o capital próprio da pessoa jurídica representando os valores investidos pelos sócios ou acionistas.",
        "temas_relacionados": []
    },
    {
        "id": "capitalizacao_composta",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Capitalizacao Composta", "Capitalização Composta"],
        "termos_busca": ["entenda", "capitalização", "composta", "funciona", "mecanismo", "juros"],
        "descricao": "Entenda o que é capitalização composta, como funciona o mecanismo de juros sobre juros e por que é fundamental para investimentos e planejamento de longo prazo",
        "temas_relacionados": []
    },
    {
        "id": "capitalizacao_simples",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Capitalizacao Simples", "Capitalização Simples"],
        "termos_busca": ["simples", "regime", "capitalização", "juros", "montante", "inicial", "serve"],
        "descricao": "Regime de capitalização de juros em que o montante inicial serve como base de cálculo para os juros de todos os períodos.",
        "temas_relacionados": []
    },
    {
        "id": "capm_capital_asset_pricing_model",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CAPM (Capital Asset Pricing Model)", "Capital Asset Pricing Model", "CAPM"],
        "termos_busca": ["model", "pricing", "asset", "capital", "entenda", "capm", "calcular", "retorno"],
        "descricao": "Entenda o que é o CAPM, como calcular o retorno esperado de um ativo e por que ele é essencial na avaliação de risco e investimento.",
        "temas_relacionados": []
    },
    {
        "id": "carencia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Carencia", "Carência"],
        "termos_busca": ["carência", "prazo", "preestabelecido", "durante", "participante", "plano", "previdência"],
        "descricao": "Prazo preestabelecido durante o qual o participante de um plano de previdência, ou investidor, não tem acesso aos seus recursos.",
        "temas_relacionados": []
    },
    {
        "id": "carregar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Carregar"],
        "termos_busca": ["carregar", "manter", "ativo", "atingir", "objetivo"],
        "descricao": "Manter o ativo até atingir seu objetivo.",
        "temas_relacionados": []
    },
    {
        "id": "carry_trade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Carry Trade"],
        "termos_busca": ["carry", "trade", "estratégia", "investimento", "aproveita", "diferença"],
        "descricao": "Carry Trade é uma estratégia de investimento que aproveita a diferença de juros entre moedas; entenda como funciona e os riscos",
        "temas_relacionados": []
    },
    {
        "id": "carta_de_recomendacao_anbima",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Carta de Recomendacao ANBIMA", "Carta de Recomendação ANBIMA", "CRA"],
        "termos_busca": ["recomendação", "carta", "segundo", "anbima", "proposta", "elaborada", "área", "supervisão"],
        "descricao": "Segundo a Anbima, é a proposta elaborada pela sua área de Supervisão para uma instituição participante visando à correção ou compensação de uma infração de pequeno potencial ofensivo.",
        "temas_relacionados": []
    },
    {
        "id": "carteira_de_ativos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Carteira de Ativos"],
        "termos_busca": ["entenda", "carteira", "ativos", "montar", "diversificação", "essencial"],
        "descricao": "Entenda o que é carteira de ativos, como montar a sua e por que a diversificação é essencial para reduzir riscos e alcançar metas",
        "temas_relacionados": []
    },
    {
        "id": "carteira_recomendada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Carteira Recomendada"],
        "termos_busca": ["carteira", "recomendada", "estruturada", "benefícios", "contribuir", "abordagem"],
        "descricao": "O que é carteira recomendada, como é estruturada, quais os benefícios e de que forma pode contribuir para uma abordagem de investimentos mais estratégica e compatível com o perfil do investidor",
        "temas_relacionados": []
    },
    {
        "id": "casar_com_o_ativo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Casar (com o ativo)", "com o ativo", "Casar"],
        "termos_busca": ["ativo", "com", "casar", "ficar", "papel", "tempo", "desejado", "aguardando"],
        "descricao": "Ficar com o papel mais tempo que o desejado aguardando uma recuperação no preço para realizar a venda.",
        "temas_relacionados": []
    },
    {
        "id": "cdawa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CDA/WA"],
        "termos_busca": ["cda", "títulos", "crédito", "representativos", "promessa", "pagamento", "entrega"],
        "descricao": "São títulos de crédito representativos de promessa de pagamento por entrega de produto agropecuário. Estes títulos são emitidos conjuntamente pelos armazéns destinados à atividade de guarda e conservação de produtos agropecuários, de acordo com a Lei 11.076/2004.",
        "temas_relacionados": []
    },
    {
        "id": "cdb_certificado_de_deposito_bancario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CDB (Certificado de Deposito Bancario)", "CDB (Certificado de Depósito Bancário)", "Certificado de Deposito Bancario", "Certificado de Depósito Bancário", "CDB"],
        "termos_busca": ["bancário", "depósito", "certificado", "cdb", "investimento", "renda", "fixa", "rende"],
        "descricao": "CDB é um investimento de renda fixa que rende mais que a poupança. Saiba como funciona, tipos e vantagens. Leia mais!",
        "temas_relacionados": []
    },
    {
        "id": "cdca",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CDCA"],
        "termos_busca": ["cdca", "título", "crédito", "nominativo", "livre", "negociação", "representativo"],
        "descricao": "É um título de crédito nominativo, de livre negociação e representativo de promessa de pagamento em dinheiro, vinculado a direitos creditórios originários de negócios realizados entre produtores rurais (ou suas cooperativas) e terceiros, inclusive financiamentos ou empréstimos.",
        "temas_relacionados": []
    },
    {
        "id": "cds",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CDS"],
        "termos_busca": ["cds", "credit", "default", "swap", "derivativo", "balcão", "permite"],
        "descricao": "Credit Default Swap é um derivativo de balcão que permite a compra/venda de proteção para crédito contra determinado evento de crédito do emissor de ativos ou tomador de crédito respectivo.",
        "temas_relacionados": []
    },
    {
        "id": "cedula_de_credito_bancario_ccb",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cedula de Credito Bancario (CCB)", "Cédula de Crédito Bancário (CCB)", "Cedula de Credito Bancario", "Cédula de Crédito Bancário", "CCB"],
        "termos_busca": ["ccb", "cédula", "crédito", "bancário", "principais", "instrumentos", "jurídicos"],
        "descricao": "Cédula de Crédito Bancário é um dos principais instrumentos jurídicos para formalizar operações de crédito no Brasil, pois proporciona segurança e agilidade para credores e devedores",
        "temas_relacionados": []
    },
    {
        "id": "cedula_de_credito_imobiliario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cedula de Credito Imobiliario", "Cédula de Crédito Imobiliário", "CCI"],
        "termos_busca": ["entenda", "conceito", "cédula", "crédito", "imobiliário", "funções"],
        "descricao": "Entenda o conceito da Cédula de Crédito Imobiliário, funções, características e importância no mercado",
        "temas_relacionados": []
    },
    {
        "id": "cedula_de_produto_rural_cpr",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cedula de Produto Rural (CPR)", "Cédula de Produto Rural (CPR)", "Cedula de Produto Rural", "Cédula de Produto Rural", "CPR"],
        "termos_busca": ["cpr", "rural", "produto", "cédula", "saiba", "funciona", "tipos", "vantagens"],
        "descricao": "Saiba o que é CPR, como funciona, tipos, vantagens e papel no financiamento do agronegócio, com segurança jurídica e liquidez",
        "temas_relacionados": []
    },
    {
        "id": "central_de_cessao_de_credito",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Central de Cessao de Credito", "Central de Cessão de Crédito", "CCC"],
        "termos_busca": ["crédito", "cessão", "central", "sistema", "operado", "câmara", "interbancária", "pagamentos"],
        "descricao": "Sistema operado pela Câmara Interbancária de Pagamentos (CIP). Segundo o BCB, a C3 faz a transferência definitiva do ativo negociado (cessão de crédito) simultaneamente à liquidação financeira definitiva, trazendo assim maior segurança às operações de cessões de crédito interbancárias.",
        "temas_relacionados": []
    },
    {
        "id": "centralizadora_da_compensacao_de_cheques_compe",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Centralizadora da Compensacao de Cheques (COMPE)", "Centralizadora da Compensação de Cheques (COMPE)", "Centralizadora da Compensacao de Cheques", "Centralizadora da Compensação de Cheques", "COMPE"],
        "termos_busca": ["compe", "cheques", "compensação", "centralizadora", "segundo", "infraestrutura", "mercado", "financeiro"],
        "descricao": "Segundo BCB, é a infraestrutura do mercado financeiro gerida pelo Banco do Brasil, responsável pelo Serviço de compensação de cheques.",
        "temas_relacionados": []
    },
    {
        "id": "certificado_de_deposito_interbancario_cdi",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Certificado de Deposito Interbancario (CDI)", "Certificado de Depósito Interbancário (CDI)", "Certificado de Deposito Interbancario", "Certificado de Depósito Interbancário", "CDI"],
        "termos_busca": ["cdi", "interbancário", "depósito", "certificado", "saiba", "funcionamento", "importância", "referência"],
        "descricao": "Saiba o que é CDI, seu funcionamento e sua importância como referência para investimentos de renda fixa; entenda impacto nos rendimentos",
        "temas_relacionados": []
    },
    {
        "id": "chinese_wall",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Chinese wall"],
        "termos_busca": ["wall", "chinese", "separação", "atuação", "setores", "financeiros", "instituição"],
        "descricao": "É a separação da atuação entre setores financeiros de uma mesma instituição.",
        "temas_relacionados": []
    },
    {
        "id": "circuitbreak",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Circuit-Break"],
        "termos_busca": ["break", "circuit", "breaker", "mecanismo", "suspende", "temporariamente", "negociações"],
        "descricao": "Circuit Breaker é um mecanismo que suspende temporariamente negociações na bolsa em casos de quedas abruptas, com o objetivo de conter o pânico no mercado; entenda",
        "temas_relacionados": []
    },
    {
        "id": "cisao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cisao", "Cisão"],
        "termos_busca": ["cisão", "segundo", "artigo", "operação", "empresa", "transfere", "parcelas"],
        "descricao": "Segundo o artigo 229 da Lei 6407/76, é a operação pela qual a empresa transfere parcelas do seu patrimônio para uma ou mais sociedades, constituídas para esse fim ou já existentes, extinguindo-se a empresa cindida, se houver versão de todo...",
        "temas_relacionados": []
    },
    {
        "id": "classe_do_fundo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Classe do Fundo"],
        "termos_busca": ["fundo", "classe", "segundo", "categorias", "atribuídas", "fundos", "investimento", "coletivo"],
        "descricao": "Segundo a CVM, são as categorias atribuídas aos fundos de investimento coletivo de acordo com suas respectivas políticas de investimento definidas em seu regulamento.",
        "temas_relacionados": []
    },
    {
        "id": "clearing",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Clearing"],
        "termos_busca": ["clearing", "termo", "inglês", "clear", "significa", "compensação", "denominação"],
        "descricao": "Do termo em inglês clear, significa compensação, denominação dadas as centrais de compensação e liquidação que atuam como contraparte central garantidora.",
        "temas_relacionados": []
    },
    {
        "id": "clube_de_investimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Clube de Investimento"],
        "termos_busca": ["clube", "modalidade", "investimento", "principais", "objetivos", "instrumento", "aprendizado"],
        "descricao": "É uma modalidade de investimento que tem como principais objetivos ser um instrumento de aprendizado para o pequeno investidor e um canal de acesso ao mercado de capitais. Trata-se de um condomínio constituído por pessoas físicas para a aplicação de...",
        "temas_relacionados": []
    },
    {
        "id": "cmn",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CMN"],
        "termos_busca": ["cmn", "conselho", "monetário", "nacional", "órgão", "deliberativo", "máximo"],
        "descricao": "Conselho Monetário Nacional. Órgão deliberativo máximo do Sistema Financeiro Nacional.",
        "temas_relacionados": []
    },
    {
        "id": "coaf",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["COAF"],
        "termos_busca": ["coaf", "conselho", "controle", "atividades", "financeiras", "órgão", "ligado"],
        "descricao": "Conselho de Controle de Atividades Financeiras, órgão ligado ao Banco Central que tem como missão produzir inteligência financeira e promover a proteção dos setores econômicos contra a lavagem de dinheiro e o financiamento ao terrorismo.",
        "temas_relacionados": []
    },
    {
        "id": "codigos_das_acoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Codigos das acoes", "Códigos das ações", "CDA"],
        "termos_busca": ["ações", "das", "códigos", "entenda", "servem", "impactam", "mercado", "financeiro"],
        "descricao": "Entenda para o que servem e como impactam o mercado financeiro.",
        "temas_relacionados": []
    },
    {
        "id": "cofins_contribuicao_para_o_financiamento_da_seguridade_social",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["COFINS (Contribuicao para o Financiamento da Seguridade Social)", "COFINS (Contribuição para o Financiamento da Seguridade Social)", "Contribuicao para o Financiamento da Seguridade Social", "Contribuição para o Financiamento da Seguridade Social", "COFINS"],
        "termos_busca": ["social", "seguridade", "financiamento", "para", "saiba", "cofins", "funciona", "contribuição"],
        "descricao": "Saiba o que é COFINS, como funciona a contribuição, alíquotas, regimes de apuração e impacto na carga tributária das empresas",
        "temas_relacionados": []
    },
    {
        "id": "colocacao_privada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Colocacao Privada", "Colocação Privada"],
        "termos_busca": ["privada", "colocação", "oferta", "primária", "valores", "mobiliários", "vendidas", "diretamente"],
        "descricao": "É uma oferta primária em que valores mobiliários são vendidas diretamente a um grupo de selecionado investidores institucionais.",
        "temas_relacionados": []
    },
    {
        "id": "comite_de_basileia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Comite de Basileia", "Comitê de Basileia"],
        "termos_busca": ["comitê", "supervisão", "bancária", "basileia", "função", "estabelecer"],
        "descricao": "Comitê de Supervisão Bancária de Basileia tem a função de estabelecer recomendações para a padronização das práticas de supervisão bancária em nível internacional.",
        "temas_relacionados": []
    },
    {
        "id": "comite_de_politica_monetaria_copom",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Comite de Politica Monetaria (COPOM)", "Comitê de Política Monetária (COPOM)", "Comite de Politica Monetaria", "Comitê de Política Monetária", "COPOM"],
        "termos_busca": ["copom", "monetária", "política", "segundo", "comitê", "criado", "âmbito", "banco"],
        "descricao": "Segundo o BCB, é o comitê criado no âmbito do Banco Central do Brasil e incumbido de implementar a política monetária, definir a meta para a Taxa Selic (e seu eventual viés) bem como analisar o Relatório de Inflação. É...",
        "temas_relacionados": []
    },
    {
        "id": "comitente",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Comitente"],
        "termos_busca": ["comitente", "cliente", "corretora", "pessoa", "física", "jurídica", "atua"],
        "descricao": "Cliente de corretora. É a pessoa física ou jurídica que atua em bolsa de valores, através de corretoras negociando ativos por ela negociados.",
        "temas_relacionados": []
    },
    {
        "id": "commodities",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Commodities"],
        "termos_busca": ["commodities", "saiba", "tipos", "importância", "economia", "global", "investir"],
        "descricao": "Saiba o que são, os tipos, a importância na economia global e como investir. Entenda fatores que influenciam os preços",
        "temas_relacionados": []
    },
    {
        "id": "companhia_aberta",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Companhia Aberta"],
        "termos_busca": ["aberta", "companhia", "consideradas", "empresas", "abertas", "companhias", "possuem", "títulos"],
        "descricao": "São consideradas empresas abertas as companhias que possuem títulos e valores mobiliários, de acordo com a regulação da CVM, negociados em bolsa de valores ou em mercado de balcão.",
        "temas_relacionados": []
    },
    {
        "id": "companhia_fechada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Companhia Fechada"],
        "termos_busca": ["fechada", "companhia", "consideradas", "empresas", "fechadas", "companhias", "possuem", "títulos"],
        "descricao": "São consideradas empresas fechadas as companhias que não possuem títulos e valores mobiliários, de acordo com a regulação da CVM, negociados em bolsa de valores ou em mercado de balcão, caracterizadas por manter sua gestão restrita a um pequeno grupo...",
        "temas_relacionados": []
    },
    {
        "id": "companhia_securitizadora",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Companhia Securitizadora"],
        "termos_busca": ["securitizadora", "companhia", "instituição", "financeira", "cuja", "finalidade", "compra", "securitização"],
        "descricao": "Instituição não financeira cuja finalidade é a compra e securitização de créditos, usando-os como lastro para emissão de títulos e valores mobiliários, de acordo com a regulamentação da CVM",
        "temas_relacionados": []
    },
    {
        "id": "compensacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Compensacao", "Compensação"],
        "termos_busca": ["compensação", "segundo", "acordo", "compensar", "posições", "obrigações", "participantes"],
        "descricao": "Segundo o BCB, é o acordo para compensar posições ou obrigações por parte dos participantes ou sócios de uma negociação. A compensação reduz um grande número de posições ou obrigações individuais a um número menor de obrigações ou posições. A...",
        "temas_relacionados": []
    },
    {
        "id": "compensacao_bilateral",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Compensacao Bilateral", "Compensação Bilateral"],
        "termos_busca": ["bilateral", "acordo", "envolve", "compensação", "duas", "entidades", "obrigações"],
        "descricao": "É o acordo que envolve a compensação entre duas entidades com obrigações financeiras entre si.",
        "temas_relacionados": []
    },
    {
        "id": "compensacao_de_encerramento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Compensacao de Encerramento", "Compensação de Encerramento"],
        "termos_busca": ["encerramento", "especial", "compensação", "cujo", "objetivo", "reduzir", "exposições"],
        "descricao": "Forma especial de compensação cujo objetivo é reduzir as exposições em contratos abertos quando uma das partes possui as condições definidas em antes da data da liquidação.",
        "temas_relacionados": []
    },
    {
        "id": "compensacao_multilateral",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Compensacao Multilateral", "Compensação Multilateral"],
        "termos_busca": ["multilateral", "compensação", "segundo", "procedimento", "caracteriza", "apuração", "resultados", "bilaterais"],
        "descricao": "Segundo o BCB, é o procedimento que se caracteriza pela apuração dos resultados bilaterais devedores e credores de cada participante em relação aos demais.",
        "temas_relacionados": []
    },
    {
        "id": "compensacao_por_novacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Compensacao por Novacao", "Compensação por Novação", "CPN"],
        "termos_busca": ["novação", "por", "compensação", "segundo", "acordos", "estabelecem", "disposições", "compromissos"],
        "descricao": "Segundo o BCB, são acordos que estabelecem disposições para que os compromissos contratuais individuais futuros sejam cancelados no momento de sua confirmação e substituídos por novas obrigações que fazem parte de um acordo único.",
        "temas_relacionados": []
    },
    {
        "id": "compensacao_privada_de_creditos_e_debitos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Compensacao Privada de Creditos e Debitos", "Compensação Privada de Créditos e Débitos", "CPCD"],
        "termos_busca": ["privada", "compensação", "segundo", "quitação", "créditos", "débitos", "residentes", "país"],
        "descricao": "Segundo o BCB, é a quitação de créditos e débitos entre residentes no país e no exterior, sem movimentação cambial, por meio de lançamentos contábeis. A compensação privada de créditos e débitos é vedada pelo Decreto-Lei 9.025, de 27/2/1946.",
        "temas_relacionados": []
    },
    {
        "id": "compliance",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Compliance"],
        "termos_busca": ["compliance", "conformidade", "designação", "cumprimento", "políticas", "procedimentos", "regras"],
        "descricao": "Ou conformidade, é a designação do cumprimento das políticas, procedimentos, e regras estabelecidas pela regulação em vigência.",
        "temas_relacionados": []
    },
    {
        "id": "comprado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Comprado"],
        "termos_busca": ["comprado", "investidor", "comprou", "está", "comprando", "determinado", "ativo"],
        "descricao": "Diz-se do investidor que comprou ou está comprando um determinado ativo.",
        "temas_relacionados": []
    },
    {
        "id": "condominio_aberto",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Condominio Aberto", "Condomínio Aberto"],
        "termos_busca": ["aberto", "condomínio", "condôminos", "cotistas", "determinado", "fundo", "podem", "solicitar"],
        "descricao": "Quando os condôminos ou cotistas de determinado fundo podem solicitar o resgate de suas cotas a qualquer tempo.",
        "temas_relacionados": []
    },
    {
        "id": "condominio_fechado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Condominio Fechado", "Condomínio Fechado"],
        "termos_busca": ["fechado", "condomínio", "condôminos", "cotistas", "determinado", "fundo", "somente", "podem"],
        "descricao": "Quando os condôminos ou cotistas de determinado fundo somente podem solicitar o resgate de suas cotas ao término do prazo de duração do fundo.",
        "temas_relacionados": []
    },
    {
        "id": "conglomerado_financeiro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conglomerado Financeiro"],
        "termos_busca": ["financeiro", "conglomerado", "conjunto", "entidades", "financeiras", "vinculadas", "participação", "acionária"],
        "descricao": "É o conjunto de entidades financeiras vinculadas por participação acionária ou por controle operacional efetivo.",
        "temas_relacionados": []
    },
    {
        "id": "conselho_administrativo_de_defesa_economica_cade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conselho Administrativo de Defesa Economica (CADE)", "Conselho Administrativo de Defesa Econômica (CADE)", "Conselho Administrativo de Defesa Economica", "Conselho Administrativo de Defesa Econômica", "CADE"],
        "termos_busca": ["cade", "econômica", "defesa", "administrativo", "conselho", "segundo", "autarquia", "federal"],
        "descricao": "Segundo a Lei 12.529/2011, é uma autarquia federal, vinculada ao Ministério da Justiça, com sede e foro no Distrito Federal, tendo como missão zelar pela livre concorrência no mercado, sendo a entidade responsável, no âmbito do Poder Executivo, não só...",
        "temas_relacionados": []
    },
    {
        "id": "conselho_de_administracao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conselho de Administracao", "Conselho de Administração"],
        "termos_busca": ["administração", "conselho", "composição", "colegiada", "máxima", "formalizada", "estatutos", "organização"],
        "descricao": "É uma composição colegiada máxima formalizada pelos estatutos da organização que comanda as politicas da sociedade sendo responsável pelas estratégias de negócios.",
        "temas_relacionados": []
    },
    {
        "id": "conselho_fiscal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conselho Fiscal"],
        "termos_busca": ["fiscal", "conselho", "colegiado", "interno", "criado", "fiscalizar", "resultados", "operações"],
        "descricao": "É um colegiado interno criado para fiscalizar os resultados das operações da companhia.",
        "temas_relacionados": []
    },
    {
        "id": "conta_cel",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conta CEL"],
        "termos_busca": ["cel", "conta", "especial", "liquidação", "característica", "corrente", "banco"],
        "descricao": "Conta especial de liquidação com característica de conta-corrente, do Banco B3 S.A.",
        "temas_relacionados": []
    },
    {
        "id": "conta_de_liquidacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conta de Liquidacao", "Conta de Liquidação"],
        "termos_busca": ["liquidação", "segundo", "conta", "mantida", "câmaras", "prestadores", "serviços"],
        "descricao": "Segundo o BCB, é a conta mantida no BC pelas Câmaras/prestadores de serviços de compensação e de liquidação e por instituições autorizadas a funcionar pelo BCB não elegíveis a abertura de conta Reservas Bancárias.",
        "temas_relacionados": []
    },
    {
        "id": "conta_do_tesouro_nacional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conta do Tesouro Nacional", "CTN"],
        "termos_busca": ["nacional", "tesouro", "segundo", "conta", "reflete", "pagamentos", "recebimentos", "recursos"],
        "descricao": "Segundo o BCB, é a conta que reflete pagamentos e recebimentos de recursos primários do Tesouro Nacional, depositados no Banco Central, não incluindo as operações com títulos de emissão do Tesouro.",
        "temas_relacionados": []
    },
    {
        "id": "conta_garantida",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conta Garantida"],
        "termos_busca": ["garantida", "produto", "bancário", "crédito", "vinculado", "conta", "corrente"],
        "descricao": "Produto bancário de crédito vinculado a conta corrente com utilização de limite de crédito pré-estabelecido.",
        "temas_relacionados": []
    },
    {
        "id": "conta_master",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Conta Master", "Conta Máster"],
        "termos_busca": ["máster", "conta", "mantida", "câmara", "agrupa", "contas", "registradas"],
        "descricao": "Conta mantida na câmara, que agrupa contas registradas sob o mesmo participante de negociação pleno ou participantes de liquidação, de comitentes que possuem vínculo específico entre si, como o de gestão comum ou o de representação pelo mesmo intermediário internacional...",
        "temas_relacionados": []
    },
    {
        "id": "contraparte_central",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Contraparte Central"],
        "termos_busca": ["central", "contraparte", "entidade", "atua", "compradora", "vendedores", "vendedora", "compradores"],
        "descricao": "Entidade que atua como compradora para todos vendedores e como vendedora para todos compradores para determinados contratos previamente estabelecidos.",
        "temas_relacionados": []
    },
    {
        "id": "contrato_de_distribuicao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Contrato de Distribuicao", "Contrato de Distribuição"],
        "termos_busca": ["distribuição", "contrato", "coordenação", "colocação", "garantia", "firme", "liquidação"],
        "descricao": "Contrato de Coordenação, Colocação e Garantia Firme de Liquidação de Ações Ordinárias de Emissão de uma Companhia, a ser celebrado entre a Companhia, o Acionista Controlador, os Coordenadores e a B3, esta última na qualidade de interveniente anuente.",
        "temas_relacionados": []
    },
    {
        "id": "contrato_de_estabilizacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Contrato de Estabilizacao", "Contrato de Estabilização"],
        "termos_busca": ["estabilização", "contrato", "instrumento", "particular", "prestação", "serviços", "realizado", "bancos"],
        "descricao": "Instrumento particular de prestação de serviços realizado com bancos de investimento que estão participando de um processo de IPO cuja função é realizar operações de estabilização de preço das ações de emissão da companhia no mercado brasileiro após o início...",
        "temas_relacionados": []
    },
    {
        "id": "contrato_de_participacao_no_novo_mercado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Contrato de Participacao no Novo Mercado", "Contrato de Participação no Novo Mercado", "CPNM"],
        "termos_busca": ["mercado", "novo", "participação", "contrato", "celebrado", "companhia", "acionista", "controlador"],
        "descricao": "Contrato celebrado entre a Companhia, o Acionista Controlador, os administradores e a B3, contendo obrigações relativas à listagem das ações da Companhia no Novo Mercado, cuja eficácia somente terá início a partir da data de publicação do Anúncio de Início.",
        "temas_relacionados": []
    },
    {
        "id": "controladores",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Controladores"],
        "termos_busca": ["controladores", "acionistas", "quotistas", "detentores", "ações", "quotas", "participação"],
        "descricao": "São todos os acionistas ou quotistas detentores de ações ou quotas de participação com direito a voto, os quais possam compor com demais acionistas ou quotistas para formar o grupo controlador da sociedade empresarial.",
        "temas_relacionados": []
    },
    {
        "id": "coordenador_lider",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Coordenador Lider", "Coordenador Líder"],
        "termos_busca": ["líder", "coordenador", "oferta", "instituição", "financeira", "função", "principal"],
        "descricao": "Ou coordenador de oferta, é a instituição financeira com a função principal de organizar ofertas públicas de ações, debêntures e demais valores mobiliários.",
        "temas_relacionados": []
    },
    {
        "id": "coordenadores_da_oferta",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Coordenadores da Oferta"],
        "termos_busca": ["oferta", "coordenadores", "nome", "coordenador", "líder", "bancos", "considerados", "conjunto"],
        "descricao": "Nome do Coordenador Líder e outros bancos considerados em conjunto.",
        "temas_relacionados": []
    },
    {
        "id": "corretora_de_cambio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Corretora de Cambio", "Corretora de Câmbio"],
        "termos_busca": ["câmbio", "corretora", "segundo", "instituição", "objeto", "social", "exclusivo", "intermediação"],
        "descricao": "Segundo o BCB, é a instituição que tem por objeto social exclusivo a intermediação em operações de câmbio. Deve ser constituída sob a forma de sociedade anônima ou por quotas de responsabilidade limitada, devendo constar na sua denominação social a...",
        "temas_relacionados": []
    },
    {
        "id": "corretora_de_valores_cctvm",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Corretora de Valores (CCTVM)", "Corretora de Valores", "CCTVM"],
        "termos_busca": ["cctvm", "corretora", "corretoras", "valores", "mobiliários", "conectam", "investidores", "mercado"],
        "descricao": "Corretoras de valores mobiliários conectam investidores ao mercado por meio de ações, renda fixa e derivativos",
        "temas_relacionados": []
    },
    {
        "id": "cotista",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cotista"],
        "termos_busca": ["cotista", "investidor", "fundos", "investimento"],
        "descricao": "Investidor de fundos de investimento.",
        "temas_relacionados": []
    },
    {
        "id": "cpr",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CPR"],
        "termos_busca": ["cpr", "cédula", "produto", "rural", "título", "representa", "promessa"],
        "descricao": "Cédula de Produto Rural é um título que representa uma promessa de entrega futura de um produto agropecuário, funcionando como um facilitador na produção e comercialização rural.",
        "temas_relacionados": []
    },
    {
        "id": "cra_certificado_de_recebiveis_do_agronegocio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CRA (Certificado de Recebiveis do Agronegocio)", "CRA (Certificado de Recebíveis do Agronegócio)", "Certificado de Recebiveis do Agronegocio", "Certificado de Recebíveis do Agronegócio", "CRA"],
        "termos_busca": ["cra", "descubra", "certificado", "recebíveis", "agronegócio", "vantagens", "riscos"],
        "descricao": "Descubra o que é o CRA (Certificado de Recebíveis do Agronegócio), suas vantagens, riscos e como investir nesse título de crédito vinculado ao setor agrícola.",
        "temas_relacionados": []
    },
    {
        "id": "crash",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Crash"],
        "termos_busca": ["crash", "termo", "inglês", "utilizado", "queda", "extremamente", "forte"],
        "descricao": "É um termo em inglês utilizado quando há uma queda extremamente forte em bolsa de valores em que os preços dos ativos negociados são depreciados rapidamente.",
        "temas_relacionados": []
    },
    {
        "id": "credit_default_swap_cds",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Credit Default Swap (CDS)", "Credit Default Swap", "CDS"],
        "termos_busca": ["cds", "swap", "default", "credit", "descubra", "funciona", "proteção", "contra"],
        "descricao": "Descubra o que é o CDS, como funciona essa proteção contra calotes e por que é um indicador-chave de risco de crédito no mercado",
        "temas_relacionados": []
    },
    {
        "id": "cri_certificado_de_recebiveis_imobiliarios",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CRI (Certificado de Recebiveis Imobiliarios)", "CRI (Certificado de Recebíveis Imobiliários)", "Certificado de Recebiveis Imobiliarios", "Certificado de Recebíveis Imobiliários", "CRI"],
        "termos_busca": ["imobiliários", "recebíveis", "certificado", "cri", "vantagens", "riscos", "investir", "nesse"],
        "descricao": "O que é, vantagens, riscos e como investir nesse título de renda fixa ligado ao setor imobiliário.",
        "temas_relacionados": []
    },
    {
        "id": "criptoativos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Criptoativos"],
        "termos_busca": ["descubra", "criptoativos", "tipos", "usos", "aplicações", "saiba"],
        "descricao": "Descubra o que são criptoativos, seus tipos, usos e aplicações. Saiba como funcionam e entenda os benefícios, riscos e desafios de investir nesse mercado",
        "temas_relacionados": []
    },
    {
        "id": "crph",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CRPH"],
        "termos_busca": ["crph", "cédula", "rural", "pignoratícia", "hipotecária"],
        "descricao": "Cédula Rural Pignoratícia e Hipotecária",
        "temas_relacionados": []
    },
    {
        "id": "ctvm_corretora_de_titulos_e_valores_mobiliarios",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CTVM (Corretora de Titulos e Valores Mobiliarios)", "CTVM (Corretora de Títulos e Valores Mobiliários)", "Corretora de Titulos e Valores Mobiliarios", "Corretora de Títulos e Valores Mobiliários", "CTVM"],
        "termos_busca": ["mobiliários", "títulos", "entenda", "ctvm", "funciona", "corretora", "valores", "papel"],
        "descricao": "Entenda o que é CTVM, como funciona uma corretora de valores e seu papel no acesso a investimentos no mercado brasileiro",
        "temas_relacionados": []
    },
    {
        "id": "cupom",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cupom"],
        "termos_busca": ["cupom", "juros", "pagos", "periodicamente", "títulos", "dívida"],
        "descricao": "Juros pagos periodicamente por títulos de dívida.",
        "temas_relacionados": []
    },
    {
        "id": "cupom_cambial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Cupom cambial"],
        "termos_busca": ["cambial", "cupom", "taxa", "juros", "referenciadas", "dólar", "cotada", "reais"],
        "descricao": "Taxa de juros referenciadas em dólar, cotada em Reais, calculada como o diferencial entre a taxa de juros, em Reais, e a expectativa de desvalorização da moeda nacional.",
        "temas_relacionados": []
    },
    {
        "id": "cusip",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CUSIP"],
        "termos_busca": ["cusip", "segundo", "número", "identificação", "títulos", "americanos", "canadenses"],
        "descricao": "Segundo o BCB, é o número de identificação dos títulos americanos e canadenses, formado por nove dígitos alfanuméricos.",
        "temas_relacionados": []
    },
    {
        "id": "custo_de_oportunidade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Custo de Oportunidade"],
        "termos_busca": ["oportunidade", "custo", "taxa", "retorno", "selecionada", "relação", "melhor", "alternativa"],
        "descricao": "É a taxa de retorno não selecionada em relação a melhor alternativa de investimento. É o valor do que o investidor renuncia ao tomar uma decisão de investimento.",
        "temas_relacionados": []
    },
    {
        "id": "custo_efetivo_total_cet",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Custo Efetivo Total (CET)", "Custo Efetivo Total", "CET"],
        "termos_busca": ["cet", "custo", "efetivo", "total", "mostra", "real", "crédito"],
        "descricao": "Custo Efetivo Total mostra o custo real do crédito ao considerar juros, tarifas e encargos; entenda como comparar propostas",
        "temas_relacionados": []
    },
    {
        "id": "cvm_comissao_de_valores_mobiliarios",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["CVM (Comissao de Valores Mobiliarios)", "CVM (Comissão de Valores Mobiliários)", "Comissao de Valores Mobiliarios", "Comissão de Valores Mobiliários", "CVM"],
        "termos_busca": ["mobiliários", "valores", "comissão", "cvm", "autarquia", "papel", "central", "proteção"],
        "descricao": "Autarquia tem papel central na proteção de investidores e na promoção da integridade e eficiência do mercado de capitais",
        "temas_relacionados": []
    },
    {
        "id": "darf_documento_de_arrecadacao_de_receitas_federais",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["DARF (Documento de Arrecadacao de Receitas Federais)", "DARF (Documento de Arrecadação de Receitas Federais)", "Documento de Arrecadacao de Receitas Federais", "Documento de Arrecadação de Receitas Federais", "DARF"],
        "termos_busca": ["entenda", "darf", "documento", "arrecadação", "receitas", "federais"],
        "descricao": "Entenda o que é DARF (Documento de Arrecadação de Receitas Federais), como funciona e saiba preenchê-lo corretamente",
        "temas_relacionados": []
    },
    {
        "id": "data_de_inicio_de_negociacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Data de Inicio de Negociacao", "Data de Início de Negociação", "DIN"],
        "termos_busca": ["negociação", "data", "útil", "seguinte", "publicação", "anúncio", "início"],
        "descricao": "Dia útil seguinte à publicação do Anúncio de Início.",
        "temas_relacionados": []
    },
    {
        "id": "data_de_liquidacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Data de Liquidacao", "Data de Liquidação"],
        "termos_busca": ["entenda", "data", "liquidação", "impacta", "operações", "financeiras"],
        "descricao": "Entenda o que é data de liquidação e como isso impacta suas operações financeiras",
        "temas_relacionados": []
    },
    {
        "id": "data_de_liquidacao_das_acoes_suplementares",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Data de Liquidacao das Acoes Suplementares", "Data de Liquidação das Ações Suplementares", "DLDAS"],
        "termos_busca": ["suplementares", "das", "data", "ocorrerá", "liquidação", "física", "financeira", "ações"],
        "descricao": "Data em que ocorrerá a liquidação física e financeira das ações do lote suplementar, geralmente no prazo de 3 dias úteis contados da data do exercício da opção das ações suplementares.",
        "temas_relacionados": []
    },
    {
        "id": "data_ex",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Data EX"],
        "termos_busca": ["entenda", "data", "veja", "funciona", "importância", "investidores"],
        "descricao": "Entenda o que é a Data EX, veja como funciona e qual sua importância para investidores.",
        "temas_relacionados": []
    },
    {
        "id": "dealers",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dealers"],
        "termos_busca": ["dealers", "segundo", "instituições", "financeiras", "atuam", "conta", "risco"],
        "descricao": "Segundo o BCB, são as instituições financeiras que atuam, por sua conta e risco, no mercado financeiro intermediando operações de compra e venda de títulos.",
        "temas_relacionados": []
    },
    {
        "id": "debentures_conversiveis",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Debentures Conversiveis", "Debêntures Conversíveis"],
        "termos_busca": ["conversíveis", "debêntures", "debentures", "conferem", "titular", "opção", "convertê", "ações"],
        "descricao": "Debentures que conferem ao seu titular a opção de convertê-las em ações da própria empresa emissora , em datas determinadas, a um preço pré-especificado.",
        "temas_relacionados": []
    },
    {
        "id": "debentures_incentivadas",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Debentures Incentivadas", "Debêntures Incentivadas"],
        "termos_busca": ["incentivadas", "debêntures", "possível", "diversificar", "carteira", "contribuir", "diretamente", "melhoria"],
        "descricao": "É possível diversificar carteira e contribuir diretamente para melhoria e expansão de serviços essenciais à sociedade com esse tipo de investimento",
        "temas_relacionados": []
    },
    {
        "id": "debentures_permutaveis",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Debentures permutaveis", "Debêntures permutáveis"],
        "termos_busca": ["debêntures", "permutáveis", "podem", "permitir", "troca", "títulos"],
        "descricao": "Debêntures permutáveis podem permitir a troca de títulos por ações de outra empresa, caso o investidor opte pela conversão",
        "temas_relacionados": []
    },
    {
        "id": "debenturista",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Debenturista"],
        "termos_busca": ["debenturista", "titular", "debenture"],
        "descricao": "Titular da debenture",
        "temas_relacionados": []
    },
    {
        "id": "defi_decentralized_finance",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["DeFi (Decentralized Finance)", "Decentralized Finance", "DeFi"],
        "termos_busca": ["finance", "decentralized", "entenda", "defi", "finanças", "descentralizadas", "funcionam", "vantagens"],
        "descricao": "Entenda o que é DeFi (Finanças Descentralizadas), como funcionam, vantagens, riscos e impacto dessa revolução nas finanças digitais",
        "temas_relacionados": []
    },
    {
        "id": "depositario_central",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Depositario Central", "Depositário Central"],
        "termos_busca": ["entenda", "depositário", "central", "estrutura", "assegura", "segurança"],
        "descricao": "Entenda o que é depositário central e como a estrutura assegura segurança, liquidez e registro de ativos no mercado financeiro",
        "temas_relacionados": []
    },
    {
        "id": "derreter",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Derreter"],
        "termos_busca": ["derreter", "mercado", "está", "derretendo", "movimento", "queda"],
        "descricao": "Mercado está derretendo quando está em movimento de queda.",
        "temas_relacionados": []
    },
    {
        "id": "desdobramento_de_acoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Desdobramento de acoes", "Desdobramento de ações"],
        "termos_busca": ["entenda", "desdobramento", "ações", "funciona", "objetivos", "vantagens"],
        "descricao": "Entenda o que é desdobramento de ações, como funciona, seus objetivos, vantagens e desvantagens para investidores e empresas",
        "temas_relacionados": []
    },
    {
        "id": "desovando",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Desovando"],
        "termos_busca": ["desovando", "indicar", "venda", "expressiva", "determinado", "ativo", "grande"],
        "descricao": "Indicar venda expressiva de determinado ativo por uma grande investidor seja ele pessoa física ou jurídica.",
        "temas_relacionados": []
    },
    {
        "id": "dever_de_diligencia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dever de diligencia", "Dever de diligência"],
        "termos_busca": ["diligência", "dever", "segundo", "artigo", "administrador", "companhia", "deve", "empregar"],
        "descricao": "Segundo o artigo 153 da Lei das S/As, é quando “o administrador da companhia deve empregar, no exercício de suas funções, o cuidado e diligência que todo homem ativo e probo costuma empregar na administração dos seus próprios negócios\".",
        "temas_relacionados": []
    },
    {
        "id": "di",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["DI", "Depósito Interfinanceiro", "deposito interfinanceiro"],
        "termos_busca": ["depósito", "interfinanceiro", "empréstimo", "instituições", "financeiras"],
        "descricao": "Depósito Interfinanceiro. Empréstimo entre instituições financeiras",
        "temas_relacionados": []
    },
    {
        "id": "dia_de_negociacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dia de Negociacao", "Dia de Negociação"],
        "termos_busca": ["dia", "trata", "data", "negociação", "dias", "úteis", "bolsa"],
        "descricao": "Trata-se da data de negociação em dias úteis na Bolsa de Valores.",
        "temas_relacionados": []
    },
    {
        "id": "direct_market_access_dma",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Direct Market Access (DMA)", "Direct Market Access", "DMA"],
        "termos_busca": ["dma", "access", "market", "direct", "acesso", "direto", "ambiente", "eletrônico"],
        "descricao": "Acesso direto ao ambiente eletrônico de negociação em bolsa, autorizado e sob responsabilidade de um participante, o que permite ao investidor enviar as próprias ofertas ao sistema de negociação e receber, em tempo real, as informações de difusão ao mercado.",
        "temas_relacionados": []
    },
    {
        "id": "direito_creditorio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Direito creditorio", "Direito creditório"],
        "termos_busca": ["creditório", "direito", "determinado", "crédito", "títulos", "representativos", "deste"],
        "descricao": "Direito a determinado crédito e títulos representativos deste direito.",
        "temas_relacionados": []
    },
    {
        "id": "distribuidor",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Distribuidor"],
        "termos_busca": ["distribuidor", "atividade", "distribuição", "títulos", "valores", "mobiliários", "mercado"],
        "descricao": "é a atividade de distribuição de títulos e valores mobiliários no mercado, por conta de terceiros, realizando a intermediação e distribuição com as bolsas de valores e de mercadorias",
        "temas_relacionados": []
    },
    {
        "id": "distribuidora_dtvm",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Distribuidora (DTVM)", "Distribuidora", "DTVM"],
        "termos_busca": ["distribuidora", "saiba", "dtvm", "funciona", "funções", "mercado", "financeiro"],
        "descricao": "Saiba o que é DTVM, como funciona, funções no mercado financeiro e diferença em relação às corretoras de valores",
        "temas_relacionados": []
    },
    {
        "id": "divida_externa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Divida Externa", "Dívida Externa"],
        "termos_busca": ["dívida", "externa", "representa", "compromissos", "financeiros", "assumidos"],
        "descricao": "Dívida externa representa os compromissos financeiros assumidos por um país com credores estrangeiros; entenda funcionamento, impactos e formas de gestão",
        "temas_relacionados": []
    },
    {
        "id": "divida_securitizada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Divida Securitizada", "Dívida Securitizada"],
        "termos_busca": ["securitizada", "dívida", "resultado", "agrupamento", "dívidas", "único", "título", "novo"],
        "descricao": "É o resultado de agrupamento de dívidas em um único título novo com objetivo de ser colocado junto ao mercado.",
        "temas_relacionados": []
    },
    {
        "id": "dividas_reestruturadas",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dividas Reestruturadas", "Dívidas Reestruturadas"],
        "termos_busca": ["reestruturadas", "segundo", "dívidas", "estados", "municípios", "estatais", "união"],
        "descricao": "Segundo o BCB, são as dívidas de estados, municípios e estatais com a União decorrentes de operações de crédito externo assumidas pela União relativas aos avisos MF-30 de 29/8/1983, ao BIB, ao Clube de Paris, à divida de médio e...",
        "temas_relacionados": []
    },
    {
        "id": "dolar_futuro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dolar Futuro", "Dólar Futuro"],
        "termos_busca": ["futuro", "dólar", "negociado", "liquidação", "futura"],
        "descricao": "Dólar negociado na B3, para liquidação futura.",
        "temas_relacionados": []
    },
    {
        "id": "dolar_pronto",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dolar Pronto", "Dólar Pronto"],
        "termos_busca": ["pronto", "segundo", "dólar", "negociado", "mercado", "vista", "geralmente"],
        "descricao": "Segundo o BCB, é o dólar negociado no mercado à vista, geralmente com liquidação em dois dias úteis (D2).",
        "temas_relacionados": []
    },
    {
        "id": "dormir_comprado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dormir Comprado"],
        "termos_busca": ["comprado", "dormir", "investidor", "carrega", "posição"],
        "descricao": "Quando o investidor carrega a posição de um dia para outro",
        "temas_relacionados": []
    },
    {
        "id": "dovish",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dovish"],
        "termos_busca": ["descubra", "significa", "postura", "dovish", "afeta", "mercados"],
        "descricao": "Descubra o que significa postura dovish, como afeta mercados e a diferença em relação ao perfil hawkish na política monetária",
        "temas_relacionados": []
    },
    {
        "id": "dow_jones",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Dow Jones"],
        "termos_busca": ["jones", "dow", "composto", "grandes", "empresas", "americanas", "operam", "diversos"],
        "descricao": "Composto por 30 grandes empresas americanas que operam em diversos setores, o índice oferece uma visão abrangente da saúde econômica dos Estados Unidos da América.",
        "temas_relacionados": []
    },
    {
        "id": "du",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["DU", "dias úteis", "dias uteis"],
        "termos_busca": ["dias", "úteis"],
        "descricao": "Dias úteis",
        "temas_relacionados": []
    },
    {
        "id": "duracao_duration",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Duracao (Duration)", "Duração (Duration)", "Duration", "Duracao", "Duração"],
        "termos_busca": ["duration", "duração", "prazo", "médio", "ponderado", "fluxos", "caixa", "trazidos"],
        "descricao": "É o prazo médio ponderado dos fluxos de caixa, trazidos a valor presente, de um título de renda fixa.",
        "temas_relacionados": []
    },
    {
        "id": "economia_de_escala",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Economia de Escala"],
        "termos_busca": ["escala", "economia", "eficiência", "econômica", "obtida", "meio", "intensificação", "determinada"],
        "descricao": "Eficiência econômica obtida por meio da intensificação de determinada atividade.",
        "temas_relacionados": []
    },
    {
        "id": "embibr",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["EMBI+Br"],
        "termos_busca": ["embi", "medida", "risco", "títulos", "dívida", "externa", "brasileira"],
        "descricao": "Medida de risco de títulos da dívida externa brasileira. A diferença entre o EMBI+Br e os títulos do tesouro americano é o prêmio utilizado pelos investidores como medida de risco Brasil",
        "temas_relacionados": []
    },
    {
        "id": "emissoes_publicas",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Emissoes Publicas", "Emissões Públicas"],
        "termos_busca": ["públicas", "emissões", "ofertas", "títulos", "valores", "mobiliários", "emitidos", "companhias"],
        "descricao": "São as ofertas de títulos e valores mobiliários emitidos por companhias abertas efetuadas para o público em geral.",
        "temas_relacionados": []
    },
    {
        "id": "emissor",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Emissor"],
        "termos_busca": ["emissor", "órgão", "responsável", "emissão", "títulos", "junto", "público"],
        "descricao": "Órgão responsável pela emissão de títulos junto ao público.",
        "temas_relacionados": []
    },
    {
        "id": "entidades_abertas_de_previdencia_complementar_eapc",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Entidades Abertas de Previdencia Complementar (EAPC)", "Entidades Abertas de Previdência Complementar (EAPC)", "Entidades Abertas de Previdencia Complementar", "Entidades Abertas de Previdência Complementar", "EAPC"],
        "termos_busca": ["eapc", "complementar", "previdência", "abertas", "entidades", "entidade", "sociedade", "seguradora"],
        "descricao": "Entidade ou sociedade seguradora autorizada a instituir planos de previdência complementar aberta.",
        "temas_relacionados": []
    },
    {
        "id": "entidades_fechadas_de_previdencia_complementar_efpc",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Entidades Fechadas de Previdencia Complementar (EFPC)", "Entidades Fechadas de Previdência Complementar (EFPC)", "Entidades Fechadas de Previdencia Complementar", "Entidades Fechadas de Previdência Complementar", "EFPC"],
        "termos_busca": ["efpc", "complementar", "fechadas", "entidades", "instituições", "fins", "lucrativos", "gerenciam"],
        "descricao": "São instituições sem fins lucrativos que gerenciam planos de previdência privada coletivos, voltados aos funcionários de uma determinada empresa. São também conhecidas como fundos de pensão",
        "temas_relacionados": []
    },
    {
        "id": "escritura_de_emissao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Escritura de Emissao", "Escritura de Emissão"],
        "termos_busca": ["entenda", "escritura", "emissão", "função", "benefícios", "importância"],
        "descricao": "Entenda o que é Escritura de emissão, sua função, benefícios e importância para investidores e empresas no mercado financeiro",
        "temas_relacionados": []
    },
    {
        "id": "esg_environmental_social_and_governance",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ESG (Environmental, Social and Governance)", "Environmental, Social and Governance", "ESG"],
        "termos_busca": ["governance", "and", "social", "environmental", "esg", "funciona", "essencial", "empresas"],
        "descricao": "O que é ESG, como funciona e por que é essencial para empresas e investidores",
        "temas_relacionados": []
    },
    {
        "id": "especulador",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Especulador"],
        "termos_busca": ["especulador", "agente", "assume", "risco", "variação", "preços", "operação"],
        "descricao": "É o agente que assume o risco de variação de preços uma operação financeira.",
        "temas_relacionados": []
    },
    {
        "id": "espirro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Espirro"],
        "termos_busca": ["espirro", "termo", "utilizado", "variação", "brusca", "mercado", "financeiro"],
        "descricao": "Termo utilizado para uma variação brusca no mercado financeiro, seja positivo ou negativo",
        "temas_relacionados": []
    },
    {
        "id": "estar_zerado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Estar Zerado"],
        "termos_busca": ["zerado", "estar", "fora", "mercado", "sair", "aplicação", "vinha"],
        "descricao": "Estar fora do mercado ou sair da aplicação que vinha mantendo.",
        "temas_relacionados": []
    },
    {
        "id": "estatuto_social",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Estatuto Social"],
        "termos_busca": ["social", "estatuto", "principal", "documento", "pessoa", "jurídica", "estabelece", "regras"],
        "descricao": "É o principal documento de uma pessoa jurídica o qual estabelece as regras para o seu funcionamento.",
        "temas_relacionados": []
    },
    {
        "id": "etf_exchange_traded_funds",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ETF (Exchange Traded Funds)", "Exchange Traded Funds", "ETF"],
        "termos_busca": ["funds", "traded", "exchange", "etf", "etfs", "oferecem", "maneira", "conveniente"],
        "descricao": "Os ETFs oferecem uma maneira conveniente de construir portfólios diversificados, seja para investidores institucionais ou para investidores individuais.",
        "temas_relacionados": []
    },
    {
        "id": "euroclear",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Euroclear"],
        "termos_busca": ["euroclear", "instituição", "europeia", "serviços", "financeiros", "sede", "bélgica"],
        "descricao": "É uma instituição europeia de serviços financeiros, com sede na Bélgica, especializada na liquidação de transações, custódia e manutenção de ativos.",
        "temas_relacionados": []
    },
    {
        "id": "exposicao_cambial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Exposicao Cambial", "Exposição Cambial"],
        "termos_busca": ["cambial", "segundo", "total", "exposição", "ouro", "moeda", "estrangeira"],
        "descricao": "Segundo o BCB, é o total de exposição em ouro, moeda estrangeira e em ativos e passivos referenciados na variação cambial mantida por uma instituição.",
        "temas_relacionados": []
    },
    {
        "id": "family_office",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Family Office"],
        "termos_busca": ["office", "family", "serviço", "especializado", "famílias", "alto", "poder", "aquisitivo"],
        "descricao": "É um serviço especializado para as famílias de alto poder aquisitivo, abrangendo assessoria financeira completa, incluindo análise de proteção patrimonial, planejamento tributário e sucessório, etc.",
        "temas_relacionados": []
    },
    {
        "id": "fato_relevante",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fato Relevante"],
        "termos_busca": ["fato", "relevante", "informação", "impactar", "ações", "decisões"],
        "descricao": "Fato relevante é o tipo de informação que pode impactar ações e decisões de investidores, sendo obrigatória sua divulgação pelas empresas.",
        "temas_relacionados": []
    },
    {
        "id": "fatores_de_risco",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fatores de Risco"],
        "termos_busca": ["entenda", "fatores", "risco", "conheça", "tipos", "comuns"],
        "descricao": "Entenda o que são os fatores de risco, conheça tipos mais comuns e como influenciam rentabilidade e segurança de investimentos",
        "temas_relacionados": []
    },
    {
        "id": "fazer_giro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fazer Giro"],
        "termos_busca": ["giro", "fazer", "oportunidades", "operações", "compra", "venda", "ativos", "caracterizando"],
        "descricao": "Oportunidades de operações de compra e venda de ativos, caracterizando um giro nas posições ou lotes do ativo que se está operando.",
        "temas_relacionados": []
    },
    {
        "id": "fechamento_da_bolsa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fechamento da Bolsa"],
        "termos_busca": ["bolsa", "fechamento", "encerramento", "pregão"],
        "descricao": "Encerramento do pregão",
        "temas_relacionados": []
    },
    {
        "id": "fechamento_de_posicao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fechamento de Posicao", "Fechamento de Posição"],
        "termos_busca": ["entenda", "conceito", "fechamento", "posição", "importância", "traders"],
        "descricao": "Entenda o conceito de fechamento de posição, importância para traders e investidores e como essa estratégia é aplicada",
        "temas_relacionados": []
    },
    {
        "id": "fiagro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["FIAGRO"],
        "termos_busca": ["fiagro", "fundo", "voltado", "agronegócio", "distribuição", "rendimentos"],
        "descricao": "Fiagro é um fundo voltado ao agronegócio, com distribuição de rendimentos e potencial de diversificação; veja como funciona e quais são as vantagens",
        "temas_relacionados": []
    },
    {
        "id": "ficfii",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["FICFII"],
        "termos_busca": ["ficfii", "oferece", "acesso", "diversificado", "mercado", "imobiliário"],
        "descricao": "FICFII oferece acesso diversificado ao mercado imobiliário por meio da aquisição de cotas de FIIs, com gestão profissional e distribuição periódica de rendimentos",
        "temas_relacionados": []
    },
    {
        "id": "ficfip_fundo_de_investimento_em_cotas_de_fundo_de_investimento_em_participacoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["FICFIP (Fundo de Investimento em Cotas de Fundo de Investimento em Participacoes)", "FICFIP (Fundo de Investimento em Cotas de Fundo de Investimento em Participações)", "Fundo de Investimento em Cotas de Fundo de Investimento em Participacoes", "Fundo de Investimento em Cotas de Fundo de Investimento em Participações", "FICFIP"],
        "termos_busca": ["participações", "cotas", "investimento", "fundo", "entenda", "ficfip", "funciona", "riscos"],
        "descricao": "Entenda o que é o FICFIP, como funciona, quais são os riscos e as vantagens e para qual perfil de investidor é indicado",
        "temas_relacionados": []
    },
    {
        "id": "fics_fundos_de_investimento_em_cotas_de_fundos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["FICs (Fundos de Investimento em Cotas de Fundos)", "Fundos de Investimento em Cotas de Fundos", "FICs"],
        "termos_busca": ["investimento", "fics", "investem", "cotas", "fundos", "tanto", "mercado"],
        "descricao": "FICs investem em cotas de outros fundos, tanto no mercado local quanto no exterior; entenda funcionamento e vantagens",
        "temas_relacionados": []
    },
    {
        "id": "fidc_fundo_de_investimento_em_direitos_creditorios",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["FIDC (Fundo de Investimento em Direitos Creditorios)", "FIDC (Fundo de Investimento em Direitos Creditórios)", "Fundo de Investimento em Direitos Creditorios", "Fundo de Investimento em Direitos Creditórios", "FIDC"],
        "termos_busca": ["creditórios", "direitos", "investimento", "fundo", "descubra", "fidc", "funcionamento", "tipos"],
        "descricao": "Descubra o que é FIDC, seu funcionamento, tipos, vantagens e riscos.",
        "temas_relacionados": []
    },
    {
        "id": "fii",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["FII"],
        "termos_busca": ["fii", "fundos", "investimento", "aplicam", "recursos", "arrecadados", "meio"],
        "descricao": "Os FII são fundos de investimento que aplicam os recursos arrecadados por meio da venda de suas cotas em empreendimentos e ativos financeiros ligados ao setor imobiliário.",
        "temas_relacionados": []
    },
    {
        "id": "final_offering_memorandum",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Final Offering Memorandum", "FOM"],
        "termos_busca": ["saiba", "final", "offering", "memorandum", "importância", "investidores"],
        "descricao": "Saiba o que é o Final Offering Memorandum e sua importância para investidores",
        "temas_relacionados": []
    },
    {
        "id": "flipar_ou_flippar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Flipar ou Flippar"],
        "termos_busca": ["flippar", "flipar", "termo", "utilizado", "investidor", "compra", "ações", "initial"],
        "descricao": "Termo utilizado quando um investidor compra as ações de um IPO (Initial Public Offering) e as vende no dia do início da sua negociação em bolsa.",
        "temas_relacionados": []
    },
    {
        "id": "fmi_fundo_monetario_internacional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["FMI (Fundo Monetario Internacional)", "FMI (Fundo Monetário Internacional)", "Fundo Monetario Internacional", "Fundo Monetário Internacional", "FMI"],
        "termos_busca": ["fmi", "entenda", "papel", "fundo", "monetário", "internacional", "estabilidade"],
        "descricao": "Entenda o papel do Fundo Monetário Internacional (FMI) na estabilidade econômica global e no apoio a países em crise",
        "temas_relacionados": []
    },
    {
        "id": "fomc_federal_open_market_committee",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["FOMC (Federal Open Market Committee)", "Federal Open Market Committee", "FOMC"],
        "termos_busca": ["committee", "market", "open", "federal", "fomc", "comitê", "responsável", "definir"],
        "descricao": "Comitê do FED é responsável por definir política monetária dos EUA",
        "temas_relacionados": []
    },
    {
        "id": "fonte_da_riqueza",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fonte da Riqueza"],
        "termos_busca": ["riqueza", "fonte", "maneira", "patrimônio", "investidor", "obtido"],
        "descricao": "Maneira pela qual o patrimônio de um investidor foi ou é obtido.",
        "temas_relacionados": []
    },
    {
        "id": "formador_de_mercado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Formador de Mercado"],
        "termos_busca": ["mercado", "formador", "pessoa", "jurídica", "devidamente", "cadastrada", "compromete", "manter"],
        "descricao": "É a pessoa jurídica, devidamente cadastrada na B3, que se compromete a manter ofertas de compra e venda de forma regular e contínua oferecendo liquidez a um determinado ativo.",
        "temas_relacionados": []
    },
    {
        "id": "front_office",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Front Office"],
        "termos_busca": ["office", "front", "área", "responsável", "gerência", "investimentos", "mesas", "operações"],
        "descricao": "Área responsável pela gerência dos investimentos (mesas de operações).",
        "temas_relacionados": []
    },
    {
        "id": "front_running",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Front Running"],
        "termos_busca": ["entenda", "front", "running", "riscos", "mercado", "combate"],
        "descricao": "Entenda o que é Front Running, quais os riscos e como o mercado combate essa prática ilegal",
        "temas_relacionados": []
    },
    {
        "id": "fundo_aberto",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundo aberto"],
        "termos_busca": ["aberto", "fundo", "fundos", "permitem", "entrada", "aplicação", "saída", "resgate"],
        "descricao": "Fundos que permitem a entrada (aplicação) e saída (resgate) de cotistas.",
        "temas_relacionados": []
    },
    {
        "id": "fundo_cambial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundo cambial"],
        "termos_busca": ["fundo", "cambial", "opção", "investimento", "exposição", "moedas"],
        "descricao": "Fundo cambial é uma opção de investimento com exposição a moedas estrangeiras e proteção cambial",
        "temas_relacionados": []
    },
    {
        "id": "fundo_de_investimento_imobiliario_fii",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundo de Investimento Imobiliario (FII)", "Fundo de Investimento Imobiliário (FII)", "Fundo de Investimento Imobiliario", "Fundo de Investimento Imobiliário", "FII"],
        "termos_busca": ["fii", "imobiliário", "investimento", "fundo", "fiis", "administrados", "instituições", "especializadas"],
        "descricao": "Os FIIs são administrados por instituições especializadas, negociados na bolsa de valores e oferecem liquidez e a possibilidade de diversificação do portfólio.",
        "temas_relacionados": []
    },
    {
        "id": "fundo_di",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundo DI"],
        "termos_busca": ["fundo", "descubra", "fundos", "funcionam", "vantagens", "desvantagens", "perfil"],
        "descricao": "Descubra o que são Fundos DI, como funcionam, vantagens, desvantagens e para qual perfil de investidor se adequam melhor",
        "temas_relacionados": []
    },
    {
        "id": "fundo_exclusivo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundo Exclusivo"],
        "termos_busca": ["exclusivo", "fundo", "investimento", "constituído", "único", "cotista", "termos"],
        "descricao": "É um tipo de fundo de investimento constituído para um único cotista, nos termos da Regulação em vigor",
        "temas_relacionados": []
    },
    {
        "id": "fundo_fechado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundo Fechado"],
        "termos_busca": ["fechado", "fundo", "aquele", "cotas", "somente", "resgatadas", "término", "prazo"],
        "descricao": "É aquele em que as cotas somente são resgatadas ao término do prazo de duração do fundo e sua negociação no mercado secundário pode ser realizada através do mercado de bolsa ou do mercado de balcão organizado.",
        "temas_relacionados": []
    },
    {
        "id": "fundo_garantidor_de_credito_fgc",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundo Garantidor de Credito (FGC)", "Fundo Garantidor de Crédito (FGC)", "Fundo Garantidor de Credito", "Fundo Garantidor de Crédito", "FGC"],
        "termos_busca": ["fgc", "crédito", "garantidor", "fundo", "segundo", "entidade", "civil", "privada"],
        "descricao": "Segundo o BCB, é a entidade civil privada, sem fins lucrativos, criada em 1995 com o objetivo de administrar mecanismos de proteção aos credores de instituições financeiras.",
        "temas_relacionados": []
    },
    {
        "id": "fundo_reservado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundo Reservado"],
        "termos_busca": ["reservado", "segundo", "anbima", "fundo", "destinado", "grupo", "investidores"],
        "descricao": "Segundo a ANBIMA, é o fundo destinado a um grupo de investidores que tenham entre si vínculo familiar, societário ou que pertençam a um mesmo conglomerado ou grupo econômico.",
        "temas_relacionados": []
    },
    {
        "id": "fundos_de_desenvolvimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundos de Desenvolvimento"],
        "termos_busca": ["benefícios", "fundos", "desenvolvimento", "incluem", "possibilidade", "obter"],
        "descricao": "Os benefícios dos fundos de desenvolvimento incluem a possibilidade de obter uma rentabilidade mais atrativa que a renda fixa ao longo do tempo, a garantia de renda mínima durante a fase de construção dos imóveis e o potencial de retorno...",
        "temas_relacionados": []
    },
    {
        "id": "fundos_de_fundos_fofs",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundos de Fundos (FOFs)", "Fundos de Fundos", "FOFs"],
        "termos_busca": ["fundos", "fofs", "oferecem", "investidores", "conveniente", "diversificada"],
        "descricao": "Os Fundos de Fundos (FOFs) oferecem aos investidores uma forma conveniente e diversificada de acessar uma ampla gama de ativos financeiros.",
        "temas_relacionados": []
    },
    {
        "id": "fundos_de_investimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundos de Investimento"],
        "termos_busca": ["descubra", "fundos", "investimento", "funcionam", "vantagens", "tipos"],
        "descricao": "Descubra o que são fundos de investimento, como funcionam, suas vantagens, tipos, riscos e tributação. Entenda como escolher o ideal para seu perfil.",
        "temas_relacionados": []
    },
    {
        "id": "fundos_hibridos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Fundos Hibridos", "Fundos Híbridos"],
        "termos_busca": ["próprio", "nome", "sugere", "fundos", "híbridos", "aqueles"],
        "descricao": "Como o próprio nome sugere, os fundos híbridos são aqueles que têm tanto imóveis quanto recebíveis imobiliários em seu patrimônio.",
        "temas_relacionados": []
    },
    {
        "id": "futuro_de_dolar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Futuro de Dolar", "Futuro de Dólar"],
        "termos_busca": ["futuro", "dólar", "contrato", "derivativo", "permite", "negociação"],
        "descricao": "Futuro de Dólar é contrato derivativo que permite negociação de valor do dólar norte-americano em data futura",
        "temas_relacionados": []
    },
    {
        "id": "ganho_de_capital",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ganho de Capital"],
        "termos_busca": ["capital", "ganho", "veja", "você", "precisa", "saber", "cálculo", "tributação"],
        "descricao": "Veja o que você precisa saber sobre cálculo, tributação e isenções do ganho de capital",
        "temas_relacionados": []
    },
    {
        "id": "gatilho",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Gatilho"],
        "termos_busca": ["gatilho", "condição", "estipulada", "previamente", "iniciar", "acionar", "operação"],
        "descricao": "Condição estipulada previamente para iniciar ou acionar uma operação de compra ou de venda.",
        "temas_relacionados": []
    },
    {
        "id": "gerencia_ativa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Gerencia Ativa", "Gerência Ativa"],
        "termos_busca": ["entenda", "conceito", "gerência", "ativa", "características", "vantagens"],
        "descricao": "Entenda o conceito de gerência ativa, as características, as vantagens e os desafios",
        "temas_relacionados": []
    },
    {
        "id": "gerencia_passiva",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Gerencia Passiva", "Gerência Passiva"],
        "termos_busca": ["entenda", "gerência", "passiva", "funciona", "estratégia", "investimento"],
        "descricao": "Entenda o que é gerência passiva, como funciona essa estratégia de investimento e quais são suas vantagens e limitações",
        "temas_relacionados": []
    },
    {
        "id": "gestao_da_carteira",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Gestao da Carteira", "Gestão da Carteira"],
        "termos_busca": ["carteira", "segundo", "gestão", "profissional", "recursos", "valores", "mobiliários"],
        "descricao": "Segundo a CVM, é a gestão profissional de recursos ou valores mobiliários, entregues ao administrador, com autorização para que este, discricionariamente, compre ou venda títulos e valores mobiliários por conta do fundo. Constitui atividade sujeita à fiscalização da CVM.",
        "temas_relacionados": []
    },
    {
        "id": "gestao_de_riscos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Gestao de Riscos", "Gestão de Riscos"],
        "termos_busca": ["gestão", "identificação", "mensuração", "avaliação", "controle", "riscos", "atividade"],
        "descricao": "É a identificação, mensuração, avaliação e controle dos riscos de uma atividade especifica",
        "temas_relacionados": []
    },
    {
        "id": "green_shoe",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Green Shoe"],
        "termos_busca": ["shoe", "green", "opção", "distribuição", "lote", "suplementar", "valores", "mobiliários"],
        "descricao": "Opção de distribuição de lote suplementar de valores mobiliários.",
        "temas_relacionados": []
    },
    {
        "id": "grupamento_de_acoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Grupamento de acoes", "Grupamento de ações"],
        "termos_busca": ["grupamento", "ações", "consolida", "papéis", "eleva", "preço"],
        "descricao": "Grupamento de ações consolida papéis e eleva o preço unitário, sem alterar o capital investido; entenda seus impactos no mercado",
        "temas_relacionados": []
    },
    {
        "id": "grupo_de_egmont",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Grupo de Egmont"],
        "termos_busca": ["egmont", "segundo", "grupo", "unidades", "inteligência", "financeira", "uifs"],
        "descricao": "Segundo o BCB, é o grupo de Unidades de Inteligência Financeira (UIFs) formado com o objetivo de incrementar o apoio aos programas nacionais de combate à lavagem de dinheiro dos países que o integram.",
        "temas_relacionados": []
    },
    {
        "id": "gui",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["GUI"],
        "termos_busca": ["gui", "interface", "gráfica", "utilizador", "graphical", "user", "modelo"],
        "descricao": "Interface gráfica do utilizador, ou GUI (Graphical User Interface), é um modelo de interface que possibilita a interação com dispositivos digitais através de componentes gráficos.",
        "temas_relacionados": []
    },
    {
        "id": "hawkish",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Hawkish"],
        "termos_busca": ["hawkish", "indica", "postura", "rígida", "banco", "central"],
        "descricao": "Hawkish indica postura rígida do banco central para conter inflação, geralmente com alta de juros e redução de estímulos monetários",
        "temas_relacionados": []
    },
    {
        "id": "hedge_cambial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Hedge Cambial"],
        "termos_busca": ["hedge", "cambial", "estratégia", "financeira", "utilizada", "contra"],
        "descricao": "Hedge cambial é estratégia financeira utilizada contra oscilações na taxa de câmbio, por meio de derivativos como contratos futuros, opções e swaps",
        "temas_relacionados": []
    },
    {
        "id": "hedge_funds",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Hedge Funds"],
        "termos_busca": ["entenda", "hedge", "funds", "riscos", "vantagens", "saiba"],
        "descricao": "Entenda o que são Hedge Funds, seus riscos e vantagens; saiba quem pode investir e como esses fundos operam",
        "temas_relacionados": []
    },
    {
        "id": "hedger",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Hedger"],
        "termos_busca": ["hedger", "entenda", "conceito", "hedge", "agentes", "utilizam", "produtos"],
        "descricao": "Entenda o conceito de hedge e como os agentes utilizam produtos do mercado financeiro para minimizar riscos",
        "temas_relacionados": []
    },
    {
        "id": "heterorregulacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Heterorregulacao", "Heterorregulação"],
        "termos_busca": ["heterorregulação", "atividade", "regulatória", "desenvolvida", "agente", "externo", "ambiente"],
        "descricao": "Atividade regulatória desenvolvida por um agente externo ao ambiente regulado.",
        "temas_relacionados": []
    },
    {
        "id": "highfrequency_trading",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["High-Frequency Trading"],
        "termos_busca": ["trading", "frequency", "high", "entenda", "estratégia", "negociação", "alta", "frequência"],
        "descricao": "Entenda a estratégia de negociação de alta frequência, os benefícios e a regulamentação no Brasil",
        "temas_relacionados": []
    },
    {
        "id": "home_broker",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Home Broker"],
        "termos_busca": ["home", "broker", "plataforma", "digital", "permite", "comprar"],
        "descricao": "Home Broker é a plataforma digital que permite comprar e vender ativos da bolsa diretamente, com praticidade, autonomia e acesso em tempo real",
        "temas_relacionados": []
    },
    {
        "id": "hot_issue",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Hot Issue"],
        "termos_busca": ["hot", "entenda", "issue", "funciona", "oferta", "pública", "ações"],
        "descricao": "Entenda o que é Hot Issue, como funciona uma oferta pública de ações muito demandada e quais impactos provoca no mercado financeiro",
        "temas_relacionados": []
    },
    {
        "id": "ibra_b3_indice_brasil_amplo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IBrA B3 (Indice Brasil Amplo)", "IBrA B3 (Índice Brasil Amplo)", "Indice Brasil Amplo", "Índice Brasil Amplo", "IBrA B3"],
        "termos_busca": ["brasil", "entenda", "ibra", "índice", "amplo", "bolsa", "reflete"],
        "descricao": "Entenda o que é o IBrA B3, o índice mais amplo da bolsa que reflete o desempenho das ações mais líquidas e relevantes do mercado brasileiro.",
        "temas_relacionados": []
    },
    {
        "id": "ibrx",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IBrX"],
        "termos_busca": ["índice", "ibrx", "mede", "desempenho", "ações", "líquidas"],
        "descricao": "O índice IBrX mede desempenho de ações mais líquidas da B3; conheça o índice, a importância e as diferenças em relação ao Ibovespa",
        "temas_relacionados": []
    },
    {
        "id": "ibrx_100_b3_indice_brasil_100",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IBrX 100 B3 (Indice Brasil 100)", "IBrX 100 B3 (Índice Brasil 100)"],
        "termos_busca": ["brasil", "conheça", "ibrx", "índice", "reúne", "ações", "maior"],
        "descricao": "Conheça o IBrX 100 B3, índice que reúne as 100 ações com maior negociabilidade da B3, ideal para quem busca diversificação e representatividade no mercado",
        "temas_relacionados": []
    },
    {
        "id": "ibrx_50_b3_indice_brasil_50",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IBrX 50 B3 (Indice Brasil 50)", "IBrX 50 B3 (Índice Brasil 50)"],
        "termos_busca": ["brasil", "conheça", "ibrx", "índice", "reúne", "ações", "líquidas"],
        "descricao": "Conheça o IBrX 50, índice que reúne as 50 ações mais líquidas da B3, referência essencial para investidores e gestores no mercado brasileiro",
        "temas_relacionados": []
    },
    {
        "id": "icms_imposto_sobre_circulacao_de_mercadorias_e_servicos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ICMS (Imposto Sobre Circulacao de Mercadorias e Servicos)", "ICMS (Imposto Sobre Circulação de Mercadorias e Serviços)", "Imposto Sobre Circulacao de Mercadorias e Servicos", "Imposto Sobre Circulação de Mercadorias e Serviços", "ICMS"],
        "termos_busca": ["serviços", "mercadorias", "circulação", "sobre", "imposto", "entenda", "icms", "funciona"],
        "descricao": "Entenda o que é ICMS, como funciona, alíquotas, base de cálculo, substituição tributária e impacto na carga fiscal das empresas",
        "temas_relacionados": []
    },
    {
        "id": "ico2_b3_indice_carbono_eficiente",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ICO2 B3 (Indice Carbono Eficiente)", "ICO2 B3 (Índice Carbono Eficiente)", "Indice Carbono Eficiente", "Índice Carbono Eficiente", "ICO2 B3"],
        "termos_busca": ["carbono", "ico", "conheça", "índice", "destaca", "empresas", "gestão", "eficiente"],
        "descricao": "Conheça o ICO2, índice da B3 que destaca empresas com gestão eficiente de emissões de carbono e que promove sustentabilidade e transparência",
        "temas_relacionados": []
    },
    {
        "id": "idiversa_b3_indice_de_diversidade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IDIVERSA B3 (Indice de diversidade)", "IDIVERSA B3 (Índice de diversidade)", "Indice de diversidade", "Índice de diversidade", "IDIVERSA B3"],
        "termos_busca": ["idiversa", "índice", "diversidade", "transparência", "responsabilidade", "social"],
        "descricao": "IDIVERSA é um índice da B3 que une diversidade, transparência e responsabilidade social no mercado de capitais",
        "temas_relacionados": []
    },
    {
        "id": "iee_b3_indice_de_energia_eletrica",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IEE B3 (Indice de Energia Eletrica)", "IEE B3 (Índice de Energia Elétrica)", "Indice de Energia Eletrica", "Índice de Energia Elétrica", "IEE B3"],
        "termos_busca": ["elétrica", "energia", "iee", "saiba", "índice", "reflete", "desempenho", "principais"],
        "descricao": "Saiba o que é o IEE B3, índice que reflete desempenho de principais empresas do setor de energia elétrica na bolsa brasileira",
        "temas_relacionados": []
    },
    {
        "id": "ifnc_b3_indice_financeiro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IFNC B3 (Indice Financeiro)", "IFNC B3 (Índice Financeiro)", "Indice Financeiro", "Índice Financeiro", "IFNC B3"],
        "termos_busca": ["financeiro", "saiba", "tudo", "ifnc", "índice", "mede", "desempenho"],
        "descricao": "Saiba tudo sobre o IFNC B3, o índice que mede o desempenho das principais empresas financeiras da bolsa de valores brasileira.",
        "temas_relacionados": []
    },
    {
        "id": "ifrs",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IFRS"],
        "termos_busca": ["ifrs", "normas", "internacionais", "contabilidade", "international", "financial", "reporting"],
        "descricao": "Normas Internacionais de Contabilidade - “International Financial Reporting Standards”.",
        "temas_relacionados": []
    },
    {
        "id": "igc_b3_indice_de_governanca_corporativa_difereciada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IGC B3 (Indice de Governanca Corporativa Difereciada)", "IGC B3 (Índice de Governança Corporativa Difereciada)", "Indice de Governanca Corporativa Difereciada", "Índice de Governança Corporativa Difereciada", "IGC B3"],
        "termos_busca": ["difereciada", "corporativa", "governança", "igc", "conheça", "índice", "mede", "desempenho"],
        "descricao": "Conheça o IGC, índice da B3 que mede desempenho de ações de empresas com práticas diferenciadas de governança corporativa",
        "temas_relacionados": []
    },
    {
        "id": "igcnm_b3_indice_de_governanca_corporativa_novo_mercado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IGC-NM B3 (Índice de Governança Corporativa – Novo Mercado)", "IGC-NM B3 (Indice de Governanca Corporativa  Novo Mercado)", "Indice de Governanca Corporativa  Novo Mercado", "IGC-NM B3"],
        "termos_busca": ["mercado", "novo", "corporativa", "governança", "igc", "conheça", "índice", "mede"],
        "descricao": "Conheça o IGC-NM, índice da B3 que mede desempenho de ações de empresas listadas no Novo Mercado, segmento com exigências mais rigorosas de governança corporativa",
        "temas_relacionados": []
    },
    {
        "id": "igct_b3_indice_de_governanca_corporativa_trade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IGCT B3 (Indice de Governanca Corporativa Trade)", "IGCT B3 (Índice de Governança Corporativa Trade)", "Indice de Governanca Corporativa Trade", "Índice de Governança Corporativa Trade", "IGCT B3"],
        "termos_busca": ["trade", "corporativa", "governança", "conheça", "igct", "índice", "mede", "desempenho"],
        "descricao": "Conheça o IGCT, índice da B3 que mede desempenho de empresas com práticas avançadas de governança e liquidez no mercado brasileiro",
        "temas_relacionados": []
    },
    {
        "id": "igp10",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IGP-10"],
        "termos_busca": ["igp", "mede", "inflação", "brasil", "análise", "preços", "atacado"],
        "descricao": "IGP-10 mede inflação no Brasil com análise de preços no atacado, no varejo e na construção; entenda funcionamento e importância",
        "temas_relacionados": []
    },
    {
        "id": "igpdi",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IGP-DI"],
        "termos_busca": ["igp", "mede", "inflação", "mensal", "brasil", "base", "preços"],
        "descricao": "O IGP-DI mede a inflação mensal no Brasil, com base em preços de atacado, consumo e construção civil, sendo amplamente usado em correções contratuais",
        "temas_relacionados": []
    },
    {
        "id": "imat_b3_indice_de_materiais_basicos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IMAT B3 (Indice de Materiais Basicos)", "IMAT B3 (Índice de Materiais Básicos)", "Indice de Materiais Basicos", "Índice de Materiais Básicos", "IMAT B3"],
        "termos_busca": ["básicos", "materiais", "conheça", "imat", "índice", "mede", "desempenho", "ações"],
        "descricao": "Conheça o IMAT, índice da B3 que mede o desempenho de ações mais negociadas de empresas do setor de materiais básicos, como mineração, siderurgia, papel e produtos químicos",
        "temas_relacionados": []
    },
    {
        "id": "imob_b3_indice_imobiliario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IMOB B3 (Indice Imobiliario)", "IMOB B3 (Índice Imobiliário)", "Indice Imobiliario", "Índice Imobiliário", "IMOB B3"],
        "termos_busca": ["imobiliário", "conheça", "imob", "índice", "reflete", "desempenho", "médio"],
        "descricao": "Conheça o IMOB, índice da B3 que reflete desempenho médio de ações mais negociadas do setor imobiliário brasileiro, com base em empresas de construção civil e exploração de imóveis",
        "temas_relacionados": []
    },
    {
        "id": "imposto_de_renda_ir",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Imposto de renda (IR)", "Imposto de renda"],
        "termos_busca": ["renda", "entenda", "funciona", "imposto", "quem", "deve", "declarar"],
        "descricao": "Entenda o que é e como funciona esse tipo de imposto e quem deve declarar",
        "temas_relacionados": []
    },
    {
        "id": "indice_de_basileia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Indice de Basileia", "Índice de Basileia"],
        "termos_busca": ["basileia", "índice", "parâmetro", "essencial", "avaliar", "solidez", "instituições", "financeiras"],
        "descricao": "Parâmetro é essencial para avaliar solidez de instituições financeiras",
        "temas_relacionados": []
    },
    {
        "id": "indice_de_sharpe",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Indice de Sharpe", "Índice de Sharpe"],
        "termos_busca": ["índice", "sharpe", "mede", "retorno", "ajustado", "risco"],
        "descricao": "O Índice de Sharpe mede retorno ajustado ao risco; entenda como funciona, qual é a fórmula e saiba interpretar seus valores",
        "temas_relacionados": []
    },
    {
        "id": "indice_financeiro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Indice Financeiro", "Índice Financeiro"],
        "termos_busca": ["financeiro", "índice", "entenda", "índices", "financeiros", "tipos", "avaliar", "saúde"],
        "descricao": "Entenda o que são índices financeiros, seus tipos e como usá-los para avaliar a saúde e o desempenho econômico de uma empresa.",
        "temas_relacionados": []
    },
    {
        "id": "indices",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Indices", "Índices"],
        "termos_busca": ["entenda", "índices", "mercado", "funcionam", "principais", "tipos"],
        "descricao": "Entenda o que são índices de mercado, como funcionam, os principais tipos e sua importância para investimentos e análise econômica.",
        "temas_relacionados": []
    },
    {
        "id": "indx_b3_indice_do_setor_industrial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["INDX B3 (Indice do Setor Industrial)", "INDX B3 (Índice do Setor Industrial)", "Indice do Setor Industrial", "Índice do Setor Industrial", "INDX B3"],
        "termos_busca": ["industrial", "setor", "conheça", "indx", "índice", "reflete", "desempenho", "médio"],
        "descricao": "Conheça o INDX, índice da B3 que reflete o desempenho médio das ações do setor industrial brasileiro",
        "temas_relacionados": []
    },
    {
        "id": "inegociavel",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Inegociavel", "Inegociável"],
        "termos_busca": ["inegociável", "modalidade", "titularidade", "propriedade", "objeto", "cessão", "transferência"],
        "descricao": "Modalidade na qual a titularidade (propriedade) não pode objeto de cessão ou transferência.",
        "temas_relacionados": []
    },
    {
        "id": "inpc_indice_nacional_de_precos_ao_consumidor",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["INPC (Indice Nacional de Precos ao Consumidor)", "INPC (Índice Nacional de Preços ao Consumidor)", "Indice Nacional de Precos ao Consumidor", "Índice Nacional de Preços ao Consumidor", "INPC"],
        "termos_busca": ["consumidor", "preços", "nacional", "índice", "inpc", "mede", "inflação", "famílias"],
        "descricao": "INPC mede a inflação das famílias de baixa renda no Brasil e impacta salários, aposentadorias e benefícios; saiba como é calculado",
        "temas_relacionados": []
    },
    {
        "id": "insider_trading",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Insider Trading"],
        "termos_busca": ["insider", "trading", "prática", "ilegal", "negociar", "informações"],
        "descricao": "Insider trading é prática ilegal de negociar com informações privilegiadas; entenda o que configura esse ato ilícito e suas implicações",
        "temas_relacionados": []
    },
    {
        "id": "insolvente",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Insolvente"],
        "termos_busca": ["insolvente", "empresa", "consegue", "arcar", "pagamento", "contas", "dívidas"],
        "descricao": "Empresa que não consegue arcar com o pagamento das suas contas ou dívidas nos prazos determinados. Em grande parte dos casos, a insolvência de uma empresa sugere um processo de falência.",
        "temas_relacionados": []
    },
    {
        "id": "instituicao_de_pagamento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Instituicao de Pagamento", "Instituição de Pagamento"],
        "termos_busca": ["instituição", "entenda", "instituições", "pagamento", "funcionam", "diferenças", "bancos"],
        "descricao": "Entenda o que são as instituições de pagamento, como funcionam, diferenças para bancos tradicionais e papel no sistema financeiro",
        "temas_relacionados": []
    },
    {
        "id": "instituicao_nao_liquidante",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Instituicao Nao liquidante", "Instituição Não liquidante", "INL"],
        "termos_busca": ["liquidante", "não", "instituição", "entenda", "instituições", "liquidantes", "funções", "mercado"],
        "descricao": "Entenda o que são instituições não liquidantes e suas funções no mercado",
        "temas_relacionados": []
    },
    {
        "id": "instituicoes_administradoras_de_fundos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Instituicoes Administradoras de Fundos", "Instituições Administradoras de Fundos", "IAF"],
        "termos_busca": ["administradoras", "instituições", "instituição", "financeira", "responsável", "administração", "fundos", "investimento"],
        "descricao": "Instituição financeira responsável pela administração dos fundos de investimento sendo responsáveis pelo cálculo da cota do fundo.",
        "temas_relacionados": []
    },
    {
        "id": "instrucao_cvm",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Instrucao CVM", "Instrução CVM"],
        "termos_busca": ["cvm", "instrução", "veja", "instruções", "importância", "mercado", "capitais", "processo"],
        "descricao": "Veja o que são as Instruções CVM, sua importância para o mercado de capitais e o processo de transição para resoluções",
        "temas_relacionados": []
    },
    {
        "id": "intermediacao_financeira",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Intermediacao financeira", "Intermediação financeira"],
        "termos_busca": ["intermediação", "financeira", "conecta", "poupadores", "tomadores", "crédito"],
        "descricao": "Intermediação financeira conecta poupadores e tomadores de crédito, viabiliza fluxo de recursos e garante alocação eficiente de capital",
        "temas_relacionados": []
    },
    {
        "id": "investidor_anjo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Investidor Anjo"],
        "termos_busca": ["anjo", "angel", "investor", "business", "investidor", "utiliza", "próprio"],
        "descricao": "Angel Investor ou Business Angel, é o tipo de investidor que utiliza parte do seu próprio capital em negócios em estágio inicial e com alto potencial de retorno.",
        "temas_relacionados": []
    },
    {
        "id": "investidor_profissional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Investidor profissional"],
        "termos_busca": ["entenda", "conceito", "investidor", "profissional", "responsabilidades", "regulamentação"],
        "descricao": "Entenda o conceito de investidor profissional, as responsabilidades, a regulamentação e as diferenças em relação aos investidores individuais",
        "temas_relacionados": []
    },
    {
        "id": "investidor_qualificado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Investidor Qualificado"],
        "termos_busca": ["entenda", "conceito", "investidor", "qualificado", "vantagens", "perfil"],
        "descricao": "Entenda o conceito de investidor qualificado, as vantagens e de que forma esse perfil acessa oportunidades exclusivas com maiores potenciais de retorno e de risco",
        "temas_relacionados": []
    },
    {
        "id": "investidores_institucionais",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Investidores Institucionais"],
        "termos_busca": ["entenda", "papel", "investidores", "institucionais", "mercado", "financeiro"],
        "descricao": "Entenda papel dos investidores institucionais no mercado financeiro",
        "temas_relacionados": []
    },
    {
        "id": "investidores_nao_institucionais",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Investidores Nao Institucionais", "Investidores Não Institucionais", "INI"],
        "termos_busca": ["não", "investidores", "institucionais", "papel", "características", "vantagens", "desafios"],
        "descricao": "Investidores não institucionais: papel, características, vantagens e desafios no mercado financeiro",
        "temas_relacionados": []
    },
    {
        "id": "investimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Investimento"],
        "termos_busca": ["investimento", "aplicação", "capital", "meios", "produção", "mercados", "financeiro"],
        "descricao": "Aplicação de capital em meios de produção ou nos mercados financeiro e de capitais.",
        "temas_relacionados": []
    },
    {
        "id": "iof_imposto_sobre_operacoes_financeiras",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IOF (Imposto sobre Operacoes Financeiras)", "IOF (Imposto sobre Operações Financeiras)", "Imposto sobre Operacoes Financeiras", "Imposto sobre Operações Financeiras", "IOF"],
        "termos_busca": ["sobre", "iof", "imposto", "federal", "operações", "financeiras", "crédito", "câmbio"],
        "descricao": "O IOF é um imposto federal sobre operações financeiras, como crédito, câmbio e seguros; conheça alíquotas e implicações econômicas",
        "temas_relacionados": []
    },
    {
        "id": "iosco",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IOSCO"],
        "termos_busca": ["organização", "internacional", "comissões", "valores", "mobiliários", "iosco"],
        "descricao": "Organização Internacional das Comissões de Valores Mobiliários (IOSCO, na sigla em inglês, International Organization of Securities Commissions).",
        "temas_relacionados": []
    },
    {
        "id": "ipa_indice_de_precos_ao_produtor_amplo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IPA (Indice de Precos ao Produtor Amplo)", "IPA (Índice de Preços ao Produtor Amplo)", "Indice de Precos ao Produtor Amplo", "Índice de Preços ao Produtor Amplo", "IPA"],
        "termos_busca": ["amplo", "produtor", "índice", "ipa", "mede", "variação", "preços", "setor"],
        "descricao": "IPA mede a variação de preços no setor produtivo, permite identificar pressões inflacionárias e fornece insights econômicos essenciais",
        "temas_relacionados": []
    },
    {
        "id": "ipc_indice_de_precos_ao_consumidor",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IPC (Indice de Precos ao Consumidor)", "IPC (Índice de Preços ao Consumidor)", "Indice de Precos ao Consumidor", "Índice de Preços ao Consumidor", "IPC"],
        "termos_busca": ["índice", "ipc", "mede", "variação", "preços", "consumidor", "importante", "indicador"],
        "descricao": "IPC mede a variação de preços ao consumidor e é um importante indicador da inflação; entenda importância e impactos na economia",
        "temas_relacionados": []
    },
    {
        "id": "ipcfipe",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IPC-Fipe"],
        "termos_busca": ["ipc", "fipe", "mede", "inflação", "paulo", "base", "preços"],
        "descricao": "IPC-Fipe mede a inflação em São Paulo com base em preços pagos por famílias com renda de 1 a 10 salários mínimos mensais",
        "temas_relacionados": []
    },
    {
        "id": "ipca_indice_de_precos_ao_consumidor_amplo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IPCA (Indice de Precos ao Consumidor Amplo)", "IPCA (Índice de Preços ao Consumidor Amplo)", "Indice de Precos ao Consumidor Amplo", "Índice de Preços ao Consumidor Amplo", "IPCA"],
        "termos_busca": ["amplo", "consumidor", "preços", "saiba", "ipca", "índice", "calculado", "importância"],
        "descricao": "Saiba o que é o IPCA, como esse índice é calculado, sua importância para a economia, política monetária e poder de compra",
        "temas_relacionados": []
    },
    {
        "id": "ipca15",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IPCA-15"],
        "termos_busca": ["saiba", "ipca", "importância", "economia", "diferença", "índices"],
        "descricao": "Saiba o que é o IPCA-15, sua importância para a economia, a diferença para outros índices e sua influência na política monetária e no cotidiano dos brasileiros",
        "temas_relacionados": []
    },
    {
        "id": "ipi_imposto_sobre_produtos_industrializados",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IPI (Imposto sobre Produtos Industrializados)", "Imposto sobre Produtos Industrializados", "IPI"],
        "termos_busca": ["sobre", "ipi", "entenda", "funciona", "imposto", "federal", "produtos", "industrializados"],
        "descricao": "Entenda o que é IPI, como funciona esse imposto federal sobre produtos industrializados e qual seu impacto na economia e no consumo.",
        "temas_relacionados": []
    },
    {
        "id": "ipo_initial_public_offer",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IPO (Initial Public Offer)", "Initial Public Offer", "IPO"],
        "termos_busca": ["offer", "public", "initial", "ipo", "entenda", "funciona", "oferta", "pública"],
        "descricao": "Entenda como funciona a Oferta Pública Inicial de ações",
        "temas_relacionados": []
    },
    {
        "id": "isin",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ISIN"],
        "termos_busca": ["isin", "segundo", "número", "identificação", "títulos", "criado", "facilitar"],
        "descricao": "Segundo o BCB, é o número de identificação de títulos criado para facilitar as transações internacionais, formado por 12 dígitos alfanuméricos.",
        "temas_relacionados": []
    },
    {
        "id": "itag_b3_indice_de_acoes_com_tag_along_diferenciado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ITAG B3 (Indice de Acoes com Tag Along Diferenciado)", "ITAG B3 (Índice de Ações com Tag Along Diferenciado)", "Indice de Acoes com Tag Along Diferenciado", "Índice de Ações com Tag Along Diferenciado", "ITAG B3"],
        "termos_busca": ["diferenciado", "along", "tag", "com", "conheça", "itag", "índice", "reúne"],
        "descricao": "Conheça o ITAG, índice da B3 que reúne ações de empresas com proteção superior aos acionistas minoritários, via tag along diferenciado",
        "temas_relacionados": []
    },
    {
        "id": "ivbx_2_b3_indice_valor",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["IVBX 2 B3 (Indice Valor)", "IVBX 2 B3 (Índice Valor)", "Indice Valor", "Índice Valor", "IVBX 2 B3"],
        "termos_busca": ["valor", "conheça", "ivbx", "índice", "mede", "desempenho", "ações"],
        "descricao": "Conheça o IVBX 2, índice da B3 que mede desempenho de ações com boa liquidez e representatividade intermediária, ideal para estratégias de diversificação",
        "temas_relacionados": []
    },
    {
        "id": "joint_venture",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Joint Venture"],
        "termos_busca": ["joint", "venture", "modelo", "cooperação", "empresarial", "voltado"],
        "descricao": "Joint venture é modelo de cooperação empresarial voltado a objetivos comuns no mercado corporativo e financeiro",
        "temas_relacionados": []
    },
    {
        "id": "juros_compostos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Juros Compostos"],
        "termos_busca": ["entenda", "funcionam", "juros", "compostos", "veja", "exemplos"],
        "descricao": "Entenda como funcionam os juros compostos, veja exemplos e aprenda a calcular esse conceito fundamental para investimentos e dívidas",
        "temas_relacionados": []
    },
    {
        "id": "juros_de_mora",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Juros de Mora"],
        "termos_busca": ["entenda", "juros", "mora", "calculados", "importância", "regulação"],
        "descricao": "Entenda o que são juros de mora, como são calculados e qual é a importância na regulação do pagamento de dívidas no mercado financeiro e comercial",
        "temas_relacionados": []
    },
    {
        "id": "juros_nominais",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Juros nominais"],
        "termos_busca": ["nominais", "entenda", "conceito", "importância", "operações", "financeiras", "juros"],
        "descricao": "Entenda o conceito, a importância nas operações financeiras e por que os juros nominais não refletem o ganho real do investidor diante da inflação",
        "temas_relacionados": []
    },
    {
        "id": "juros_simples",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Juros Simples"],
        "termos_busca": ["entenda", "funcionam", "juros", "simples", "veja", "diferença"],
        "descricao": "Entenda como funcionam os juros simples e veja a diferença em relação aos juros compostos",
        "temas_relacionados": []
    },
    {
        "id": "juros_sobre_capital_proprio_jcp",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Juros Sobre Capital Proprio (JCP)", "Juros Sobre Capital Próprio (JCP)", "Juros Sobre Capital Proprio", "Juros Sobre Capital Próprio", "JCP"],
        "termos_busca": ["jcp", "sobre", "entenda", "juros", "capital", "próprio", "funcionam", "vantagens"],
        "descricao": "Entenda o que são Juros sobre o Capital Próprio (JCP), como funcionam, vantagens e desvantagens para empresas e acionistas e diferenças em relação a dividendos",
        "temas_relacionados": []
    },
    {
        "id": "k_ou_quilo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["K ou Quilo"],
        "termos_busca": ["quilo", "expressão", "usada", "denominar", "conjunto", "papéis"],
        "descricao": "Expressão usada para denominar um conjunto de 1000 papéis",
        "temas_relacionados": []
    },
    {
        "id": "lastro_metalico",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Lastro Metalico", "Lastro Metálico"],
        "termos_busca": ["metálico", "lastro", "segundo", "depósito", "metal", "precioso", "geralmente", "ouro"],
        "descricao": "Segundo o BCB, é o depósito em metal precioso, geralmente em ouro, que garante a conversibilidade do dinheiro em forma concreta de valor.",
        "temas_relacionados": []
    },
    {
        "id": "lateralizacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Lateralizacao", "Lateralização"],
        "termos_busca": ["lateralização", "entenda", "movimento", "lateral", "consolidação", "mercado", "financeiro"],
        "descricao": "Entenda o que é movimento lateral (ou consolidação) no mercado financeiro, suas causas, características e saiba como identificar e operar",
        "temas_relacionados": []
    },
    {
        "id": "lavagem_de_dinheiro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Lavagem de Dinheiro"],
        "termos_busca": ["dinheiro", "lavagem", "segundo", "conjunto", "operações", "comerciais", "financeiras", "buscam"],
        "descricao": "Segundo o BCB, é o conjunto de operações comerciais ou financeiras que buscam a incorporação na economia de cada país, de modo transitório ou permanente, de recursos, bens e valores de origem ilícita. A Lei 9.613, de 3/3/1998, tipificou o...",
        "temas_relacionados": []
    },
    {
        "id": "lca_letra_de_credito_do_agronegocio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LCA (Letra de Credito do Agronegocio)", "LCA (Letra de Crédito do Agronegócio)", "Letra de Credito do Agronegocio", "Letra de Crédito do Agronegócio", "LCA"],
        "termos_busca": ["agronegócio", "crédito", "letra", "lca", "vantagens", "investir", "nesse", "título"],
        "descricao": "O que é, vantagens e como investir nesse título de renda fixa",
        "temas_relacionados": []
    },
    {
        "id": "lci_letra_de_credito_imobiliario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LCI (Letra de Credito Imobiliario)", "LCI (Letra de Crédito Imobiliário)", "Letra de Credito Imobiliario", "Letra de Crédito Imobiliário", "LCI"],
        "termos_busca": ["imobiliário", "crédito", "letra", "lci", "descubra", "vantagens", "tipos", "riscos"],
        "descricao": "Descubra vantagens, tipos, riscos e como investir nesse título de renda fixa com isenção de IR e proteção do FGC",
        "temas_relacionados": []
    },
    {
        "id": "ldft",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LD-FT"],
        "termos_busca": ["lavagem", "dinheiro", "financiamento", "terrorismo"],
        "descricao": "Lavagem de dinheiro e financiamento do terrorismo.",
        "temas_relacionados": []
    },
    {
        "id": "ldo_lei_de_diretrizes_orcamentarias",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LDO (Lei de Diretrizes Orcamentarias)", "LDO (Lei de Diretrizes Orçamentárias)", "Lei de Diretrizes Orcamentarias", "Lei de Diretrizes Orçamentárias", "LDO"],
        "termos_busca": ["orçamentárias", "diretrizes", "lei", "ldo", "legislação", "estabelece", "metas", "prioridades"],
        "descricao": "LDO é legislação que estabelece metas, prioridades e regras para a elaboração do orçamento público anual, com objetivo de garantir equilíbrio fiscal e transparência na gestão de recursos públicos",
        "temas_relacionados": []
    },
    {
        "id": "lei_complementar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Lei complementar"],
        "termos_busca": ["lei", "entenda", "conceito", "complementar", "características", "diferença", "relação"],
        "descricao": "Entenda o conceito de lei complementar, suas características e a diferença em relação à lei ordinária",
        "temas_relacionados": []
    },
    {
        "id": "lei_de_responsabilidade_fiscal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Lei de Responsabilidade Fiscal", "LRF"],
        "termos_busca": ["lei", "entenda", "responsabilidade", "fiscal", "organiza", "contas", "públicas"],
        "descricao": "Entenda o que é a Lei de Responsabilidade Fiscal e como ela organiza as contas públicas",
        "temas_relacionados": []
    },
    {
        "id": "leilao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Leilao", "Leilão"],
        "termos_busca": ["leilão", "modalidade", "negociação", "quem", "oferecer", "maior", "lance"],
        "descricao": "É a modalidade de negociação a quem oferecer o maior lance, igual ou superior ao valor da avaliação. As sessões de leilões ocorrem com dia e horas marcados pela bolsa de valores onde a operação será realizada.",
        "temas_relacionados": []
    },
    {
        "id": "leilao_de_abertura",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Leilao de abertura", "Leilão de abertura"],
        "termos_busca": ["leilão", "abertura", "base", "preço", "inicial", "equilíbrio"],
        "descricao": "Leilão de abertura é base para preço inicial, equilíbrio e transparência nas negociações do pregão",
        "temas_relacionados": []
    },
    {
        "id": "leilao_de_acoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Leilao de Acoes", "Leilão de Ações"],
        "termos_busca": ["leilão", "ações", "mecanismo", "fundamental", "bolsa", "valores"],
        "descricao": "Leilão de ações é mecanismo fundamental na bolsa de valores que promove transparência, equilíbrio e estabilidade nos preços dos ativos negociados",
        "temas_relacionados": []
    },
    {
        "id": "leilao_de_fechamento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Leilao de fechamento", "Leilão de fechamento"],
        "termos_busca": ["leilão", "fechamento", "define", "preço", "oficial", "ações"],
        "descricao": "Leilão de fechamento define preço oficial das ações e assegura equilíbrio e transparência no encerramento do pregão",
        "temas_relacionados": []
    },
    {
        "id": "letra_de_cambio_lc",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Letra de Cambio (LC)", "Letra de Câmbio (LC)", "Letra de Cambio", "Letra de Câmbio"],
        "termos_busca": ["saiba", "tudo", "letra", "câmbio", "funciona", "vantagens"],
        "descricao": "Saiba tudo sobre Letra de Câmbio (LC): o que é, como funciona, vantagens, riscos e como investir",
        "temas_relacionados": []
    },
    {
        "id": "letra_financeira",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Letra Financeira"],
        "termos_busca": ["financeira", "letra", "título", "renda", "fixa", "emitido", "instituições", "financeiras"],
        "descricao": "Título de renda fixa emitido por instituições financeiras com o objetivo de cursos de longo prazo.",
        "temas_relacionados": []
    },
    {
        "id": "libid",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LIBID"],
        "termos_busca": ["libid", "london", "interbank", "rate", "calculada", "partir", "libor"],
        "descricao": "London Interbank Bid Rate. Calculada a partir da LIBOR, é a taxa de juros do mercado internacional à qual os bancos internacionais aceitam depósitos a prazo.",
        "temas_relacionados": []
    },
    {
        "id": "libor",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LIBOR"],
        "termos_busca": ["libor", "london", "interbank", "offered", "rate", "segundo", "taxa"],
        "descricao": "London Interbank Offered Rate. Segundo o BCB, é a Taxa Interbancária do Mercado de Londres. Taxa de juros preferencial, do mercado internacional, utilizada entre bancos de primeira linha no mercado de dinheiro (money market).",
        "temas_relacionados": []
    },
    {
        "id": "lig_letra_imobiliaria_garantida",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LIG (Letra Imobiliaria Garantida)", "LIG (Letra Imobiliária Garantida)", "Letra Imobiliaria Garantida", "Letra Imobiliária Garantida", "LIG"],
        "termos_busca": ["garantida", "imobiliária", "letra", "lig", "conheça", "título", "renda", "fixa"],
        "descricao": "Conheça esse título de renda fixa com dupla garantia e proteção patrimonial, indicado para diversificação e segurança",
        "temas_relacionados": []
    },
    {
        "id": "limite_operacional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Limite Operacional"],
        "termos_busca": ["operacional", "limite", "atribuído", "câmara", "participantes", "estes", "clientes"],
        "descricao": "Limite atribuído pelas câmara da B3 aos seus participantes e por estes a seus clientes para restringir o risco associado à liquidação de operações sob suas responsabilidades, bem como à utilização de garantias.",
        "temas_relacionados": []
    },
    {
        "id": "liquidacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidacao", "Liquidação"],
        "termos_busca": ["liquidação", "processo", "extinção", "obrigações", "referentes", "transferência", "recursos"],
        "descricao": "Processo de extinção de obrigações referentes à transferência de recursos financeiros ou títulos entre dois ou mais agentes.",
        "temas_relacionados": []
    },
    {
        "id": "liquidacao_antecipada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidacao Antecipada", "Liquidação Antecipada"],
        "termos_busca": ["antecipada", "liquidação", "quitação", "parcial", "total", "débito", "data", "vencimento"],
        "descricao": "É a quitação parcial ou total de um débito antes da data de vencimento, mediante redução dos juros, proporcional ao tempo a decorrer.",
        "temas_relacionados": []
    },
    {
        "id": "liquidacao_bruta_em_tempo_real_lbtr",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidacao Bruta em Tempo Real (LBTR)", "Liquidação Bruta em Tempo Real (LBTR)", "Liquidacao Bruta em Tempo Real", "Liquidação Bruta em Tempo Real", "LBTR"],
        "termos_busca": ["lbtr", "bruta", "liquidação", "obrigações", "tempo", "real", "unitária", "compensação"],
        "descricao": "Liquidação de obrigações em tempo real, de forma unitária, sem a compensação de outra operação.",
        "temas_relacionados": []
    },
    {
        "id": "liquidacao_definitiva",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidacao Definitiva", "Liquidação Definitiva"],
        "termos_busca": ["definitiva", "liquidação", "extinção", "obrigação", "mediante", "transferência", "reservas", "entrega"],
        "descricao": "É a extinção de uma obrigação mediante a transferência de reservas e a entrega de valores mobiliários de maneira irrevogável e incondicional.",
        "temas_relacionados": []
    },
    {
        "id": "liquidacao_diferida",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidacao Diferida", "Liquidação Diferida"],
        "termos_busca": ["diferida", "segundo", "liquidação", "realizada", "momento", "posterior", "aceitação"],
        "descricao": "Segundo o BCB, é a liquidação realizada em momento posterior ao de aceitação das operações que dão origem às correspondentes obrigações.",
        "temas_relacionados": []
    },
    {
        "id": "liquidacao_extrajudicial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidacao Extrajudicial", "Liquidação Extrajudicial"],
        "termos_busca": ["extrajudicial", "liquidação", "segundo", "regime", "insolvência", "destina", "interromper", "funcionamento"],
        "descricao": "Segundo o BCB, é o regime de insolvência que se destina a interromper o funcionamento da instituição financeira e promover sua retirada do Sistema Financeiro Nacional (SFN), quando essa insolvência é considerada irrecuperável.",
        "temas_relacionados": []
    },
    {
        "id": "liquidacao_pelo_saldo_liquido_lsl",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidacao pelo Saldo Liquido (LSL)", "Liquidação pelo Saldo Liquido (LSL)", "Liquidacao pelo Saldo Liquido", "Liquidação pelo Saldo Liquido", "LSL"],
        "termos_busca": ["lsl", "liquido", "saldo", "pelo", "liquidação", "extinção", "obrigações", "câmara"],
        "descricao": "Extinção das obrigações da câmara ou dos participantes, pelos saldos líquidos bilaterais e multilaterais das contrapartes",
        "temas_relacionados": []
    },
    {
        "id": "liquidante_direto",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidante Direto"],
        "termos_busca": ["direto", "liquidante", "segundo", "instituição", "titular", "conta", "reservas", "bancárias"],
        "descricao": "Segundo o BCB, é a ​instituição titular de conta Reservas Bancárias ou de Conta de Liquidação no Banco Central, que utiliza essa conta para efetuar ou receber pagamentos próprios ou de terceiros referentes aos processos de liquidação nas Infraestruturas do...",
        "temas_relacionados": []
    },
    {
        "id": "liquidez_intradia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Liquidez Intradia"],
        "termos_busca": ["intradia", "liquidez", "refere", "disponibilidade", "tempo", "real", "instituição", "financeira"],
        "descricao": "Se refere a disponibilidade em tempo real que a instituição financeira tem acesso durante um dia útil de funcionamento do mercado",
        "temas_relacionados": []
    },
    {
        "id": "lockup",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Lockup"],
        "termos_busca": ["lockup", "mecanismo", "contratual", "mercado", "estabelece", "determinado", "período"],
        "descricao": "É um mecanismo contratual de mercado que estabelece determinado período no qual os investidores não podem vender as ações de uma empresa.",
        "temas_relacionados": []
    },
    {
        "id": "long",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Long"],
        "termos_busca": ["long", "posição", "comprada", "ativo"],
        "descricao": "É a posição comprada em um ativo.",
        "temas_relacionados": []
    },
    {
        "id": "long_038_short",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Long & Short", "long short", "L&S"],
        "termos_busca": ["short", "long", "termo", "utilizado", "sucessiva", "compra", "venda", "ativos"],
        "descricao": "Termo utilizado para a sucessiva compra e venda de ativos com o objetivo de se apurar lucros com a diferença entre as cotações.",
        "temas_relacionados": []
    },
    {
        "id": "lote_padronizado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Lote Padronizado"],
        "termos_busca": ["padronizado", "lote", "padrão", "títulos", "características", "idênticas", "quantidade"],
        "descricao": "Ou Lote-Padrão, é o lote de títulos de características idênticas, de quantidade múltipla que pode ser negociado em um pregão regular.",
        "temas_relacionados": []
    },
    {
        "id": "lta",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LTA"],
        "termos_busca": ["lta", "linha", "tendência", "alta", "formada", "elevação", "preço"],
        "descricao": "Linha de Tendência de Alta formada por uma elevação no preço das ações que pode ser visualizada por uma diagonal ascendente nos gráficos de ações.",
        "temas_relacionados": []
    },
    {
        "id": "ltb",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["LTB"],
        "termos_busca": ["ltb", "linha", "tendência", "baixa", "formada", "queda", "preço"],
        "descricao": "Linha de Tendência de Baixa formada por uma queda no preço das ações e que pode ser visualizada por uma diagonal descendente nos gráficos de ações.",
        "temas_relacionados": []
    },
    {
        "id": "macroalocacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Macroalocacao", "Macroalocação"],
        "termos_busca": ["entenda", "conceito", "macroalocação", "importância", "planejamento", "financeiro"],
        "descricao": "Entenda o conceito de macroalocação, sua importância no planejamento financeiro e como pode ser aplicada para alcançar objetivos de longo prazo de um portfólio de investimentos",
        "temas_relacionados": []
    },
    {
        "id": "macroeconomia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Macroeconomia"],
        "termos_busca": ["saiba", "macroeconomia", "principais", "indicadores", "influência", "cenário"],
        "descricao": "Saiba o que é a macroeconomia, seus principais indicadores e sua influência no cenário econômico e nas decisões dos investidores",
        "temas_relacionados": []
    },
    {
        "id": "manipulacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Manipulacao", "Manipulação"],
        "termos_busca": ["manipulação", "segundo", "compra", "venda", "ativos", "mercado", "finalidade"],
        "descricao": "Segundo a CVM, é a compra ou venda de ativos em mercado com a finalidade de criar falsa aparência de negociação ativa e, assim, influenciar a ação dos demais investidores.",
        "temas_relacionados": []
    },
    {
        "id": "market_profile",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Market Profile"],
        "termos_busca": ["profile", "market", "saiba", "ferramenta", "análise", "técnica", "revela", "estrutura"],
        "descricao": "Saiba mais sobre essa ferramenta de análise técnica que revela estrutura de mercado, distribuição de preços e volumes.",
        "temas_relacionados": []
    },
    {
        "id": "medida_da_riqueza",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Medida da Riqueza"],
        "termos_busca": ["riqueza", "medida", "tamanho", "patrimônio", "acumulado", "investidor"],
        "descricao": "Tamanho do patrimônio acumulado por um investidor.",
        "temas_relacionados": []
    },
    {
        "id": "mei_micro_empreendedor_individual",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["MEI (Micro Empreendedor Individual)", "Micro Empreendedor Individual", "MEI"],
        "termos_busca": ["individual", "empreendedor", "micro", "mei", "entenda", "quem", "formalizar", "benefícios"],
        "descricao": "Entenda o que é MEI, quem pode se formalizar, benefícios, obrigações e como esse regime simplificado impacta pequenos negócios no Brasil",
        "temas_relacionados": []
    },
    {
        "id": "meio_circulante",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Meio Circulante"],
        "termos_busca": ["circulante", "meio", "segundo", "conjunto", "cédulas", "moedas", "circulação", "país"],
        "descricao": "Segundo o BCB, é conjunto de cédulas e moedas em circulação em um país.",
        "temas_relacionados": []
    },
    {
        "id": "meios_de_pagamento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Meios de Pagamento"],
        "termos_busca": ["meios", "sãos", "recursos", "prontamente", "disponíveis", "pagamento", "bens"],
        "descricao": "Sãos os recursos prontamente disponíveis para pagamento de bens e serviços.",
        "temas_relacionados": []
    },
    {
        "id": "membro_de_bolsa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Membro de Bolsa"],
        "termos_busca": ["bolsa", "participante", "sistema", "negociação", "sendo", "necessariamente", "membro"],
        "descricao": "Participante do sistema de negociação, não sendo necessariamente membro da câmara de compensação da bolsa.",
        "temas_relacionados": []
    },
    {
        "id": "membro_de_compensacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Membro de Compensacao", "Membro de Compensação"],
        "termos_busca": ["compensação", "membro", "segundo", "participante", "primeiro", "nível", "direto", "estrutura"],
        "descricao": "Segundo o BCB, é participante de primeiro nível (direto) da estrutura hierárquica de pós-negociação de uma contraparte central.",
        "temas_relacionados": []
    },
    {
        "id": "mensagem",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mensagem"],
        "termos_busca": ["mensagem", "segundo", "conjunto", "informações", "trocadas", "participantes", "rede"],
        "descricao": "Segundo o BCB, é o conjunto de informações trocadas entre participantes da Rede do Sistema Financeiro Nacional (RSFN) com a finalidade de solicitar uma operação, transmitir um resultado operacional, anunciar uma mudança operacional ou comunicar qualquer outro fato relevante.",
        "temas_relacionados": []
    },
    {
        "id": "mercado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado"],
        "termos_busca": ["entenda", "mercado", "funciona", "principais", "tipos", "importância"],
        "descricao": "Entenda o que é o mercado, como funciona, os principais tipos e sua importância para a economia e o desenvolvimento global.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_a_termo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado a Termo"],
        "termos_busca": ["mercado", "termo", "permite", "travar", "preço", "compra"],
        "descricao": "Mercado a termo permite travar preço de compra ou venda para datas futuras e aplicar estratégias de proteção ou alavancagem",
        "temas_relacionados": []
    },
    {
        "id": "mercado_a_vista",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado a Vista", "Mercado à Vista"],
        "termos_busca": ["vista", "mercado", "aquele", "compromisso", "compra", "venda", "liquidação", "imediata"],
        "descricao": "É aquele em que há o compromisso de compra e venda para liquidação imediata.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_balcao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Balcao", "Mercado de Balcão"],
        "termos_busca": ["balcão", "mercado", "ambiente", "negociação", "fora", "local", "centralizado", "títulos"],
        "descricao": "Ambiente de negociação fora de local centralizado de títulos e valores mobiliários, também conhecido como mercado fora de bolsa ou mercado OTC – Over The Counter.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_balcao_organizado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Balcao Organizado", "Mercado de Balcão Organizado", "MBO"],
        "termos_busca": ["organizado", "balcão", "mercado", "segundo", "ambiente", "negociação", "administrado", "instituições"],
        "descricao": "Segundo a CVM, é o ambiente de negociação administrado por instituições auto-reguladoras, autorizadas e supervisionadas pela CVM, que mantem sistema de negociação (eletrônico ou não) e regras adequadas à realização de operações de compra e venda de títulos e valores...",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_cambio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Cambio", "Mercado de Câmbio"],
        "termos_busca": ["mercado", "segundo", "ambiente", "realizam", "operações", "câmbio", "agentes"],
        "descricao": "Segundo o BCB, é o ambiente em que se realizam as operações de câmbio entre os agentes autorizados pelo Banco Central do Brasil e entre estes e seus clientes, diretamente ou por meio de seus correspondentes.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_cambio_de_taxas_flutuantes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Cambio de Taxas Flutuantes", "Mercado de Câmbio de Taxas Flutuantes", "MCTF"],
        "termos_busca": ["flutuantes", "taxas", "câmbio", "mercado", "segundo", "segmento", "existente", "criado"],
        "descricao": "Segundo o BCB, era o segmento existente até 2005, criado pela Resolução CMN 1.552/1988, no qual cursavam operações relativas a turismo. O Mercado de Câmbio de Taxas Flutuantes e o Mercado de Câmbio de Taxas Livres foram unificados em 2005...",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_cambio_de_taxas_livres",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Cambio de Taxas Livres", "Mercado de Câmbio de Taxas Livres", "MCTL"],
        "termos_busca": ["livres", "taxas", "câmbio", "mercado", "segundo", "segmento", "existente", "criado"],
        "descricao": "Segundo o BCB, era o segmento existente até 2005, criado pela Resolução CMN 1.690/1990, no qual cursavam as operações relativas a exportação e importação e operações sujeitas a registro no Banco Central. O Mercado de Câmbio de Taxas Livres e...",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_derivativos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Derivativos"],
        "termos_busca": ["derivativos", "mercado", "negociados", "contratos", "liquidação", "futura", "preço"],
        "descricao": "Mercado no qual são negociados contratos para liquidação futura e por um preço pré-determinado referenciados em ativos financeiros, índices, indicadores, taxas, moedas ou mercadorias.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_listados",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Listados"],
        "termos_busca": ["listados", "mercado", "ativos", "negociados", "bolsa", "valores", "mercadorias"],
        "descricao": "Mercado de ativos que são negociados em bolsa de valores, mercadorias e futuros.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_opcoes_flexiveis",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Opcoes Flexiveis", "Mercado de Opções Flexíveis", "MOF"],
        "termos_busca": ["mercado", "negociados", "opções", "flexíveis", "compra", "venda"],
        "descricao": "Mercado em que são negociados opções flexíveis de compra e venda do ativo-objeto de negociação. As opções flexíveis são contratos representativos de um ativo financeiro ou de uma mercadoria no mercado disponível ou no mercado futuro, negociadas em balcão e...",
        "temas_relacionados": []
    },
    {
        "id": "mercado_de_swaps",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado de Swaps"],
        "termos_busca": ["swaps", "mercado", "derivativos", "partes", "trocam", "índices", "rentabilidade"],
        "descricao": "Mercado de derivativos em que as partes trocam índices de rentabilidade.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_firme",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado Firme"],
        "termos_busca": ["firme", "mercado", "está", "tendência", "compradora", "forte", "ativo"],
        "descricao": "Mercado que está com tendência compradora forte para o ativo ou no todo.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_fracionario_de_acoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado Fracionario de Acoes", "Mercado Fracionário de Ações", "MFA"],
        "termos_busca": ["fracionário", "mercado", "negociação", "ações", "quantidades", "abaixo", "lote"],
        "descricao": "É o mercado de negociação de ações em quantidades abaixo de um lote mínimo.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_monetario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado Monetario", "Mercado Monetário"],
        "termos_busca": ["monetário", "mercado", "realizadas", "operações", "financeiras", "curtíssimo", "prazo"],
        "descricao": "É o mercado onde são realizadas as operações financeiras de curtíssimo prazo entre os agentes econômicos.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_oversold",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado Oversold"],
        "termos_busca": ["oversold", "mercado", "segundo", "situação", "reservas", "bancárias", "livres", "inferiores"],
        "descricao": "Segundo o BCB, é a situação em que as reservas bancárias livres são inferiores às necessidades de financiamento dos títulos públicos federais fora do Banco Central.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_pesado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado Pesado"],
        "termos_busca": ["pesado", "mercado", "está", "tendência", "vendedora", "determinado", "ativo"],
        "descricao": "Quando o mercado está com tendência vendedora para determinado ativo ou para o todo.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_primario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado Primario", "Mercado Primário"],
        "termos_busca": ["primário", "mercado", "ocorrem", "lançamentos", "novas", "ações", "títulos"],
        "descricao": "Mercado onde ocorrem os lançamentos de novas ações e títulos de renda fixa para a primeira aquisição por parte de investidores. É nesse mercado que as empresas emissoras de valores mobiliários captam recursos para se financiar.",
        "temas_relacionados": []
    },
    {
        "id": "mercado_undersold",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mercado Undersold"],
        "termos_busca": ["undersold", "mercado", "segundo", "situação", "reservas", "bancárias", "livres", "superiores"],
        "descricao": "Segundo o BCB, é a situação em que as reservas bancárias livres são superiores às necessidades de financiamento dos títulos públicos federais fora do Banco Central.",
        "temas_relacionados": []
    },
    {
        "id": "mico",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Mico"],
        "termos_busca": ["mico", "jargão", "mercado", "expressa", "título", "baixo", "volume"],
        "descricao": "Jargão do mercado que expressa o título de baixo volume negociado e/ou baixa liquidez.",
        "temas_relacionados": []
    },
    {
        "id": "middle_office",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Middle Office"],
        "termos_busca": ["middle", "setor", "intermediário", "front", "back", "office", "responsável"],
        "descricao": "É o setor intermediário entre o front e o back office responsável pela administração do risco, compliance e tecnologia de uma instituição financeira.",
        "temas_relacionados": []
    },
    {
        "id": "mrp_mecanismo_de_ressarcimento_de_prejuizos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["MRP (Mecanismo de Ressarcimento de Prejuizos)", "MRP (Mecanismo de Ressarcimento de Prejuízos)", "Mecanismo de Ressarcimento de Prejuizos", "Mecanismo de Ressarcimento de Prejuízos", "MRP"],
        "termos_busca": ["prejuízos", "mrp", "mecanismo", "mantido", "administrado", "assegura", "investidores", "ressarcimento"],
        "descricao": "É o mecanismo mantido pela B3 e administrado pela BSM que assegura a todos os investidores o ressarcimento por prejuízos comprovadamente causados por erros ou omissões de participantes dos mercados administrados pela B3 (corretoras e distribuidoras de títulos e valores...",
        "temas_relacionados": []
    },
    {
        "id": "nada_na_mao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Nada na Mao", "Nada na Mão"],
        "termos_busca": ["mão", "nada", "existe", "nenhuma", "operação", "pendente"],
        "descricao": "Não existe nenhuma operação pendente.",
        "temas_relacionados": []
    },
    {
        "id": "negociavel",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Negociavel", "Negociável"],
        "termos_busca": ["negociável", "modalidade", "titularidade", "propriedade", "objeto", "cessão", "transferência"],
        "descricao": "Modalidade na qual a titularidade (propriedade) pode ser objeto de cessão ou transferência.",
        "temas_relacionados": []
    },
    {
        "id": "nft_nonfungible_token",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["NFT (Non-fungible token)", "Non-fungible token", "NFT"],
        "termos_busca": ["token", "fungible", "non", "nft", "nfts", "sido", "amplamente", "adotados"],
        "descricao": "Os NFTs têm sido amplamente adotados por artistas, músicos, criadores de jogos e colecionadores como forma de monetizar e autenticar suas obras digitais",
        "temas_relacionados": []
    },
    {
        "id": "nominativa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Nominativa"],
        "termos_busca": ["nominativa", "modalidade", "título", "contém", "nome", "titular", "proprietário"],
        "descricao": "Modalidade na qual o título contém o nome de seu titular (proprietário).",
        "temas_relacionados": []
    },
    {
        "id": "nota_de_credito",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Nota de Credito", "Nota de Crédito"],
        "termos_busca": ["crédito", "nota", "opinião", "emitida", "agência", "classificação", "risco", "respeito"],
        "descricao": "Opinião emitida por agência de classificação de risco a respeito de um emissor ou de um título de renda fixa.",
        "temas_relacionados": []
    },
    {
        "id": "novacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Novacao", "Novação"],
        "termos_busca": ["novação", "segundo", "cumprimento", "cancelamento", "obrigações", "contratuais", "vigentes"],
        "descricao": "Segundo o BCB, é o cumprimento e cancelamento de obrigações contratuais vigentes substituindo-as por novas obrigações (cujo efeito, por exemplo, é substituir obrigações de pagamento brutas por líquidas). As partes envolvidas nas novas obrigações podem ser as mesmas que as...",
        "temas_relacionados": []
    },
    {
        "id": "nucleo_de_inflacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Nucleo de inflacao", "Núcleo de inflação"],
        "termos_busca": ["núcleo", "índice", "inflação", "derivado", "principal", "busca", "obter"],
        "descricao": "Índice de inflação derivado do índice principal que busca obter o componente persistente da inflação, ou a inflação de longo prazo.",
        "temas_relacionados": []
    },
    {
        "id": "objetivo_de_retorno",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Objetivo de Retorno"],
        "termos_busca": ["objetivo", "taxa", "retorno", "requerida", "desejada", "investidor"],
        "descricao": "Taxa de retorno requerida e desejada pelo investidor.",
        "temas_relacionados": []
    },
    {
        "id": "objetivo_de_risco",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Objetivo de Risco"],
        "termos_busca": ["objetivo", "tolerância", "investidor", "risco", "composta", "capacidade", "disposição"],
        "descricao": "Tolerância do investidor ao risco, composta pela capacidade e pela disposição para assumir riscos.",
        "temas_relacionados": []
    },
    {
        "id": "oferta_de_varejo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Oferta de Varejo"],
        "termos_busca": ["varejo", "oferta", "ações", "realizada", "exclusivamente", "investidores", "institucionais"],
        "descricao": "Oferta de ações realizada exclusivamente para investidores não-institucionais.",
        "temas_relacionados": []
    },
    {
        "id": "oferta_institucional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Oferta Institucional"],
        "termos_busca": ["institucional", "oferta", "ações", "realizada", "junto", "investidores", "institucionais"],
        "descricao": "Oferta de ações realizada junto a investidores institucionais.",
        "temas_relacionados": []
    },
    {
        "id": "oferta_primaria",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Oferta Primaria", "Oferta Primária"],
        "termos_busca": ["primária", "oferta", "emissão", "novas", "ações", "cotas", "fundos", "investimento"],
        "descricao": "Emissão de novas ações ou cotas de fundos de investimento que são ofertadas ao mercado, com ingresso de recursos no próprio emissor.",
        "temas_relacionados": []
    },
    {
        "id": "oferta_publica_com_esforcos_restritos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Oferta Publica com Esforcos Restritos", "Oferta Pública com Esforços Restritos", "OPCER"],
        "termos_busca": ["restritos", "esforços", "com", "pública", "oferta", "distribuição", "valores", "mobiliários"],
        "descricao": "Oferta de distribuição de valores mobiliários que ocorre de maneira restrita e com menos exigências do que as ofertas amplas, seguindo as determinações da Instrução CVM 476/09.",
        "temas_relacionados": []
    },
    {
        "id": "oferta_publica_de_titulos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Oferta Publica de Titulos", "Oferta Pública de Títulos", "OPT"],
        "termos_busca": ["pública", "oferta", "colocação", "títulos", "venda", "junto", "público", "investidor"],
        "descricao": "Colocação de títulos à venda junto ao público investidor",
        "temas_relacionados": []
    },
    {
        "id": "ofertas_icvm_400",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ofertas ICVM 400", "OI4"],
        "termos_busca": ["icvm", "ofertas", "realizadas", "acordo", "diretrizes", "instrução", "normativa"],
        "descricao": "Ofertas realizadas de acordo com as diretrizes da Instrução Normativa da Comissão de Valores Mobiliários (CVM) 400, que normatiza as ofertas públicas de distribuição de valores mobiliários.",
        "temas_relacionados": []
    },
    {
        "id": "ofertas_icvm_476",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Ofertas ICVM 476", "OI4"],
        "termos_busca": ["icvm", "ofertas", "oferta", "pública", "esforços", "restritos", "seguindo", "diretrizes"],
        "descricao": "Ver oferta pública com esforços restritos, seguindo as diretrizes da Instrução Normativa da Comissão de Valores Mobiliários (CVM) 476.",
        "temas_relacionados": []
    },
    {
        "id": "off_shore",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Off Shore"],
        "termos_busca": ["shore", "off", "fundos", "aplicam", "recursos", "deles", "exterior"],
        "descricao": "São fundos que aplicam seus recursos ou parte deles no exterior.",
        "temas_relacionados": []
    },
    {
        "id": "offshore_bancos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Offshore (Bancos)", "Offshore", "Bancos"],
        "termos_busca": ["offshore", "segundo", "bancos", "licenças", "limitadas", "transação", "negócios"],
        "descricao": "Segundo o BCB, são os bancos com licenças limitadas à transação de negócios com pessoas fora da jurisdição de licenciamento.",
        "temas_relacionados": []
    },
    {
        "id": "oficio_da_cvm",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Oficio da CVM", "Ofício da CVM"],
        "termos_busca": ["cvm", "ofício", "segundo", "carta", "comentando", "revisão", "registro", "preliminar"],
        "descricao": "Segundo a CVM, é uma carta da CVM comentando sobre sua revisão de um registro preliminar.",
        "temas_relacionados": []
    },
    {
        "id": "ofpub",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["OFPUB"],
        "termos_busca": ["ofpub", "módulo", "registro", "ofertas", "leilões", "títulos", "públicos"],
        "descricao": "Módulo de registro de ofertas dos leilões de títulos públicos federais, utilizado pelas instituições participantes, e que complementa o Selic.",
        "temas_relacionados": []
    },
    {
        "id": "opcao_de_lote_suplementar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Opcao de Lote Suplementar", "Opção de Lote Suplementar", "OLS"],
        "termos_busca": ["suplementar", "lote", "opção", "outorgada", "empresa", "emissora", "coordenador", "líder"],
        "descricao": "Opção outorgada pela empresa emissora ao coordenador líder para aquisição de um lote suplementar, nos termos do artigo 24 da Instrução CVM nº 400, sem considerar as ações adicionais, nas mesmas condições e preço das ações inicialmente ofertadas.",
        "temas_relacionados": []
    },
    {
        "id": "opcoes_binarias",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Opcoes binarias", "Opções binárias"],
        "termos_busca": ["opções", "binárias", "caracterizadas", "formato", "tudo", "nada"],
        "descricao": "As opções binárias são caracterizadas por seu formato \"tudo ou nada\". Isso significa que o investidor sabe, desde o início, quanto poderá ganhar ou perder, dependendo de sua previsão se concretizar ou não.",
        "temas_relacionados": []
    },
    {
        "id": "opcoes_de_acoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Opcoes de Acoes", "Opções de Ações"],
        "termos_busca": ["opções", "ações", "oferecem", "investidores", "traders", "capacidade"],
        "descricao": "As opções de ações oferecem aos investidores e traders a capacidade de gerenciar risco, aumentar a alavancagem e implementar diversas estratégias de negociação para maximizar retornos.",
        "temas_relacionados": []
    },
    {
        "id": "opcoes_de_compra_call",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Opcoes de compra (CALL)", "Opções de compra (CALL)", "Opcoes de compra", "Opções de compra", "CALL"],
        "termos_busca": ["descubra", "opções", "compra", "call", "funcionam", "podem"],
        "descricao": "Descubra como as opções de compra (CALL) funcionam, como podem ser usadas para lucrar com a alta de ativos e proteger seu portfólio. Confira!",
        "temas_relacionados": []
    },
    {
        "id": "opcoes_de_venda_put",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Opcoes de venda (PUT)", "Opções de venda (PUT)", "Opcoes de venda", "Opções de venda", "PUT"],
        "termos_busca": ["put", "saiba", "funcionam", "opções", "venda", "estratégias", "podem"],
        "descricao": "Saiba como funcionam as Opções de venda (PUT), suas estratégias e como podem proteger investimentos ou gerar lucros em mercados voláteis.",
        "temas_relacionados": []
    },
    {
        "id": "open_market",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Open Market"],
        "termos_busca": ["market", "open", "mercado", "bacen", "negocia", "dívida", "pública", "bancos"],
        "descricao": "Mercado onde o Bacen negocia a dívida pública com os bancos.",
        "temas_relacionados": []
    },
    {
        "id": "operacao_compromissada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Operacao Compromissada", "Operação Compromissada"],
        "termos_busca": ["compromissada", "operação", "operações", "compra", "venda", "títulos", "compromisso", "revenda"],
        "descricao": "São operações de compra e/ou venda de títulos com compromisso de revenda e/ou recompra em uma data futura, anterior ou igual à data de vencimento dos títulos.",
        "temas_relacionados": []
    },
    {
        "id": "operacao_de_mercado_aberto",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Operacao de Mercado Aberto", "Operação de Mercado Aberto", "OMA"],
        "termos_busca": ["aberto", "mercado", "operação", "segundo", "operações", "compra", "venda", "definitiva"],
        "descricao": "Segundo o BCB, são as operações de compra e venda, de forma definitiva ou compromissada de títulos no mercado secundário. Essas operações são realizadas por bancos centrais para fins de implementação de política monetária.",
        "temas_relacionados": []
    },
    {
        "id": "operacao_definitiva",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Operacao Definitiva", "Operação Definitiva"],
        "termos_busca": ["definitiva", "operação", "segundo", "compra", "venda", "títulos", "assunção", "compromisso"],
        "descricao": "Segundo o BCB, é a compra e/ou venda de títulos sem assunção de compromisso de revenda ou recompra.",
        "temas_relacionados": []
    },
    {
        "id": "opex_operational_expenditure",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["OPEX (Operational Expenditure)", "Operational Expenditure", "OPEX"],
        "termos_busca": ["expenditure", "operational", "opex", "despesas", "operacionais", "empresa", "salários", "aluguel"],
        "descricao": "OPEX são as despesas operacionais de uma empresa, como salários, aluguel e insumos; entenda a importância de analisar esse indicador",
        "temas_relacionados": []
    },
    {
        "id": "overnight",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Overnight"],
        "termos_busca": ["overnight", "segundo", "operação", "interbancária", "vigente", "negociação", "útil"],
        "descricao": "Segundo o BCB, é a operação interbancária vigente do dia da negociação até o dia útil seguinte (por um dia útil)",
        "temas_relacionados": []
    },
    {
        "id": "pebit",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["P/EBIT"],
        "termos_busca": ["ebit", "indicador", "financeiro", "avalia", "valor", "ações", "base"],
        "descricao": "Indicador financeiro avalia valor de ações com base no lucro operacional antes de juros e impostos",
        "temas_relacionados": []
    },
    {
        "id": "passivos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Passivos"],
        "termos_busca": ["passivos", "obrigações", "empresas", "terceiros", "acionistas", "podem", "circulantes"],
        "descricao": "São as obrigações das empresas com terceiros ou os não acionistas. Podem ser circulantes, de curto prazo, ou de longo prazo.",
        "temas_relacionados": []
    },
    {
        "id": "pedra",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Pedra"],
        "termos_busca": ["pedra", "jargão", "utilizado", "mercado", "designar", "fila", "ordens"],
        "descricao": "Jargão utilizado no mercado para designar a fila de ordens de compra ou venda enviadas mas ainda não executadas.",
        "temas_relacionados": []
    },
    {
        "id": "perfil_agressivo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Perfil Agressivo"],
        "termos_busca": ["agressivo", "investidores", "perfil", "conhecidos", "disposição", "enfrentar", "volatilidade"],
        "descricao": "Investidores com esse perfil são conhecidos por sua disposição em enfrentar a volatilidade do mercado e buscar ativos com potencial de valorização significativa a curto ou médio prazo.",
        "temas_relacionados": []
    },
    {
        "id": "perfil_conservador",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Perfil Conservador"],
        "termos_busca": ["conservador", "investidores", "perfil", "tendem", "optar", "ativos", "baixo"],
        "descricao": "Investidores com esse perfil tendem a optar por ativos de baixo risco e retornos mais previsíveis, mesmo que isso signifique aceitar uma rentabilidade menor.",
        "temas_relacionados": []
    },
    {
        "id": "perfil_de_personalidade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Perfil de Personalidade"],
        "termos_busca": ["personalidade", "mercado", "financeiro", "perfil", "comportamental", "investidor", "influenciar"],
        "descricao": "No mercado financeiro, é o perfil comportamental do investidor que pode influenciar suas decisões a respeito das diferentes alternativas de investimento.",
        "temas_relacionados": []
    },
    {
        "id": "perfil_moderado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Perfil Moderado"],
        "termos_busca": ["moderado", "investidores", "perfil", "buscam", "encontrar", "ponto", "equilíbrio"],
        "descricao": "Investidores com esse perfil buscam encontrar um ponto de equilíbrio entre a segurança dos investimentos de baixo risco e o potencial de crescimento oferecido por ativos mais voláteis.",
        "temas_relacionados": []
    },
    {
        "id": "perfil_situacional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Perfil Situacional"],
        "termos_busca": ["situacional", "perfil", "análise", "investidor", "descreve", "preferências", "condição", "financeira"],
        "descricao": "Análise do investidor que descreve suas preferências, sua condição financeira pessoal e seus objetivos de vida.",
        "temas_relacionados": []
    },
    {
        "id": "periodo_de_carencia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Periodo de Carencia", "Período de Carência"],
        "termos_busca": ["carência", "segundo", "susep", "período", "serão", "aceitas", "solicitações"],
        "descricao": "Segundo a Susep, é o período em que não serão aceitas solicitações de resgate ou de portabilidade por parte do participante de um plano de previdência.",
        "temas_relacionados": []
    },
    {
        "id": "periodo_de_colocacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Periodo de Colocacao", "Período de Colocação"],
        "termos_busca": ["período", "prazo", "colocação", "ações", "contar", "data", "publicação"],
        "descricao": "É o prazo para a colocação das ações a contar da data de publicação do anúncio de início de distribuição.",
        "temas_relacionados": []
    },
    {
        "id": "periodo_de_pagamento_do_beneficio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Periodo de Pagamento do Beneficio", "Período de Pagamento do Benefício", "PPB"],
        "termos_busca": ["benefício", "pagamento", "segundo", "susep", "período", "assistido", "assistidos", "fará"],
        "descricao": "Segundo a Susep, é o período em que o assistido (ou os assistidos) fará jus ao pagamento do benefício, sob a forma de renda, podendo ser vitalício ou temporário.",
        "temas_relacionados": []
    },
    {
        "id": "periodo_de_reserva",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Periodo de Reserva", "Período de Reserva"],
        "termos_busca": ["reserva", "período", "estabelecido", "oferta", "títulos", "valores", "mobiliários"],
        "descricao": "É o período estabelecido na oferta de títulos e valores mobiliários para a realização dos pedidos de reserva dos Investidores não-institucionais.",
        "temas_relacionados": []
    },
    {
        "id": "periodo_de_silencio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Periodo de Silencio", "Período de Silêncio"],
        "termos_busca": ["silêncio", "quiet", "period", "período", "tempo", "empresa", "está"],
        "descricao": "Ou “quiet period”, é um período de tempo em que a empresa que está abrindo o capital não pode divulgar informações ao público.",
        "temas_relacionados": []
    },
    {
        "id": "pernada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Pernada"],
        "termos_busca": ["pernada", "gíria", "extensão", "total", "movimento", "preços", "alta"],
        "descricao": "Gíria para a extensão total de um movimento de preços de alta ou de baixa",
        "temas_relacionados": []
    },
    {
        "id": "pessoas_expostas_politicamente",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Pessoas Expostas Politicamente", "PEP"],
        "termos_busca": ["politicamente", "expostas", "pessoas", "segundo", "agentes", "públicos", "desempenham", "tenham"],
        "descricao": "Segundo o BCB, são os agentes públicos que desempenham ou tenham desempenhado, nos últimos cinco anos, no Brasil ou em países, territórios e dependências estrangeiras, cargos, empregos ou funções públicas relevantes, assim como seus representantes, familiares e estreitos colaboradores.",
        "temas_relacionados": []
    },
    {
        "id": "pessoas_vinculadas_oferta_publica",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Pessoas Vinculadas (Oferta Publica)", "Pessoas Vinculadas (Oferta Pública)", "Pessoas Vinculadas", "Oferta Publica", "Oferta Pública"],
        "termos_busca": ["pública", "oferta", "vinculadas", "pessoas", "segundo", "controladores", "administradores", "instituições"],
        "descricao": "Segundo a CVM, são os controladores ou administradores das instituições intermediárias, agentes de colocação internacional ou outras pessoas vinculadas à emissão e distribuição, bem como seus cônjuges ou companheiros, seus ascendentes, descendentes e colaterais até o 2º grau.",
        "temas_relacionados": []
    },
    {
        "id": "piloto_de_reservas",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Piloto de Reservas"],
        "termos_busca": ["piloto", "segundo", "responsável", "apurar", "saldo", "contas", "reservas"],
        "descricao": "Segundo o BCB, é o responsável por apurar o saldo das contas reservas bancárias ou conta de liquidação, monitorando continuamente todos os lançamentos a débito ou a crédito na conta.",
        "temas_relacionados": []
    },
    {
        "id": "pis_programa_de_integracao_social",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["PIS (Programa de Integracao Social)", "PIS (Programa de Integração Social)", "Programa de Integracao Social", "Programa de Integração Social", "PIS"],
        "termos_busca": ["social", "integração", "programa", "pis", "entenda", "funciona", "quem", "direito"],
        "descricao": "Entenda o que é PIS, como funciona, quem tem direito ao abono salarial e como ocorre a contribuição pelas empresas e o pagamento aos trabalhadores",
        "temas_relacionados": []
    },
    {
        "id": "placement_facilitation_agreement",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Placement Facilitation Agreement", "PFA"],
        "termos_busca": ["agreement", "facilitation", "placement", "contrato", "celebrado", "agentes", "colocação", "internacional"],
        "descricao": "Contrato a ser celebrado entre os agentes de colocação internacional, a companhia emissora e o acionista controlador, no âmbito de uma oferta pública, regulando esforços de colocação das ações no exterior",
        "temas_relacionados": []
    },
    {
        "id": "plano_de_continuidade_de_negocios",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Plano de Continuidade de Negocios", "Plano de Continuidade de Negócios", "PCN"],
        "termos_busca": ["negócios", "continuidade", "plano", "conjunto", "sistemas", "capaz", "proporcionar", "empresa"],
        "descricao": "É um conjunto de sistemas capaz de proporcionar a uma empresa um nível de funcionamento operacional suficiente para lidar com ameaças operacionais aos seus negócios, garantindo a sua continuidade mesmo em uma situação adversa.",
        "temas_relacionados": []
    },
    {
        "id": "plano_de_negocios",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Plano de Negocios", "Plano de Negócios"],
        "termos_busca": ["negócios", "plano", "documento", "escrito", "detalha", "empresa", "pretende", "atingir"],
        "descricao": "Documento escrito que detalha como uma empresa pretende atingir seus objetivos.",
        "temas_relacionados": []
    },
    {
        "id": "plano_gerador_de_beneficio_livre_pgbl",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Plano Gerador de Beneficio Livre (PGBL)", "Plano Gerador de Benefício Livre (PGBL)", "Plano Gerador de Beneficio Livre", "Plano Gerador de Benefício Livre", "PGBL"],
        "termos_busca": ["pgbl", "livre", "benefício", "gerador", "plano", "produto", "previdência", "complementar"],
        "descricao": "Produto de previdência complementar de contratação opcional que tem como objetivo complementar a aposentadoria oficial, oferecendo benefício fiscal em determinadas circunstâncias.",
        "temas_relacionados": []
    },
    {
        "id": "player",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Player"],
        "termos_busca": ["player", "jargão", "normalmente", "utilizado", "classificar", "operadores", "mercado"],
        "descricao": "Jargão normalmente utilizado para classificar os operadores no mercado.",
        "temas_relacionados": []
    },
    {
        "id": "poder_de_compra",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Poder de Compra"],
        "termos_busca": ["compra", "poder", "valor", "moeda", "termos", "quantidade", "bens", "serviços"],
        "descricao": "Valor de uma moeda em termos da quantidade de bens e serviços que uma unidade monetária pode adquirir. O poder de compra da moeda reduz-se quando há inflação de preços.",
        "temas_relacionados": []
    },
    {
        "id": "poison_pill",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Poison Pill"],
        "termos_busca": ["pill", "poison", "estratégia", "utilizada", "empresas", "capital", "pulverizado", "desestimular"],
        "descricao": "Estratégia utilizada pelas empresas de capital pulverizado para desestimular ofertas para aquisição de controle (ofertas hostis).",
        "temas_relacionados": []
    },
    {
        "id": "politica_cambial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Politica cambial", "Política cambial"],
        "termos_busca": ["política", "compreenda", "principais", "medidas", "definem", "regime", "cambial"],
        "descricao": "Compreenda as principais medidas que definem o regime cambial do país, regulam a moeda estrangeira e influenciam a estabilidade econômica e comercial do Brasil",
        "temas_relacionados": []
    },
    {
        "id": "politica_de_investimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Politica de Investimento", "Política de Investimento"],
        "termos_busca": ["política", "documento", "regulamento", "fundo", "investimento", "estabelece", "diretrizes"],
        "descricao": "É o documento (ou parte do regulamento de um fundo de investimento) que estabelece as diretrizes que devem ser observadas na gestão dos recursos dos investidores.",
        "temas_relacionados": []
    },
    {
        "id": "politica_monetaria",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Politica Monetaria", "Política Monetária"],
        "termos_busca": ["política", "econômica", "meio", "autoridade", "monetária", "país"],
        "descricao": "É parte da política econômica por meio da qual a autoridade monetária de um país exerce controle sobre a oferta de moeda buscando manter a estabilidade dos preços.",
        "temas_relacionados": []
    },
    {
        "id": "posicao_zerada",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Posicao Zerada", "Posição Zerada"],
        "termos_busca": ["zerada", "posição", "investidor", "está", "comprado", "vendido"],
        "descricao": "Quando o investidor, ao fim do dia, não está comprado ou vendido",
        "temas_relacionados": []
    },
    {
        "id": "posicionado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Posicionado"],
        "termos_busca": ["posicionado", "investidor", "mantém", "operação"],
        "descricao": "Investidor que se mantém em uma operação.",
        "temas_relacionados": []
    },
    {
        "id": "praticas_nao_equitativas",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Praticas nao Equitativas", "Práticas não Equitativas", "PNE"],
        "termos_busca": ["equitativas", "não", "práticas", "conduta", "vedada", "combatida", "consistente", "prática"],
        "descricao": "Conduta vedada e combatida pela CVM consistente na prática de atos que resultem em colocar uma parte em posição de desequilíbrio ou desigualdade indevida em relação aos demais participantes da operação.",
        "temas_relacionados": []
    },
    {
        "id": "prazo_de_diferimento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Prazo de Diferimento"],
        "termos_busca": ["diferimento", "prazo", "segundo", "susep", "período", "compreendido", "data", "contratação"],
        "descricao": "Segundo a Susep, é o período compreendido entre a data da contratação do plano de previdência complementar pelo participante e a data escolhida por ele para o início da concessão do benefício, podendo coincidir com o prazo de pagamento das...",
        "temas_relacionados": []
    },
    {
        "id": "prazo_de_distribuicao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Prazo de Distribuicao", "Prazo de Distribuição"],
        "termos_busca": ["distribuição", "segundo", "prazo", "máximo", "seis", "meses", "contados"],
        "descricao": "Segundo a CVM, é o prazo máximo de até seis meses, contados a partir da data da publicação do anúncio de início, para subscrição das ações objeto de uma oferta.",
        "temas_relacionados": []
    },
    {
        "id": "prazo_medio_ponderado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Prazo Medio Ponderado", "Prazo Médio Ponderado", "PMP"],
        "termos_busca": ["ponderado", "medida", "estatística", "calcula", "prazo", "médio", "vencimentos"],
        "descricao": "É uma medida estatística que calcula o prazo médio de vencimentos de uma carteira de investimentos, incluídos o principal, amortizações e os juros periódicos.",
        "temas_relacionados": []
    },
    {
        "id": "preco_por_acao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Preco por Acao", "Preço por Ação", "PPA"],
        "termos_busca": ["ação", "por", "preço", "fixado", "realização", "procedimento", "bookbuilding", "oferta"],
        "descricao": "Preço fixado após a realização do procedimento de bookbuilding em uma oferta de ações.",
        "temas_relacionados": []
    },
    {
        "id": "pregao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Pregao", "Pregão"],
        "termos_busca": ["pregão", "leilão", "negociam", "viva", "eletronicamente", "ativos", "negociados"],
        "descricao": "Tipo de leilão, em que se negociam, por viva voz ou eletronicamente, ativos negociados em bolsas de valores, mercadorias e futuros.",
        "temas_relacionados": []
    },
    {
        "id": "prestadores_de_servico",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Prestadores de Servico", "Prestadores de Serviço"],
        "termos_busca": ["serviço", "prestadores", "fundos", "investimento", "pessoa", "física", "jurídica", "contratada"],
        "descricao": "No caso de fundos de investimento, é a pessoa física ou jurídica contratada pelo administrador para prestação de serviço à administração dos recursos.",
        "temas_relacionados": []
    },
    {
        "id": "prestadores_de_servicos_de_compensacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Prestadores de Servicos de Compensacao", "Prestadores de Serviços de Compensação", "PSC"],
        "termos_busca": ["compensação", "serviços", "prestadores", "segundo", "instituições", "operam", "qualquer", "sistemas"],
        "descricao": "Segundo o BCB, são instituições que operam qualquer um dos sistemas integrantes do sistema de pagamentos, cujo funcionamento resulte em movimentações interbancárias e envolva pelo menos três participantes diretos para fins de liquidação, entre instituições financeiras ou demais instituições autorizadas...",
        "temas_relacionados": []
    },
    {
        "id": "previc",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["PREVIC"],
        "termos_busca": ["previc", "autarquia", "federal", "atua", "território", "nacional", "entidade"],
        "descricao": "É uma autarquia federal que atua em todo o território nacional como entidade de fiscalização e supervisão das atividades das entidades fechadas de previdência complementar.",
        "temas_relacionados": []
    },
    {
        "id": "price_action",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Price action"],
        "termos_busca": ["entenda", "price", "action", "funcionamento", "usado", "interpretar"],
        "descricao": "Entenda o que é Price Action, seu funcionamento e como pode ser usado para interpretar movimentos do mercado sem depender de indicadores técnicos",
        "temas_relacionados": []
    },
    {
        "id": "private_capital",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Private Capital"],
        "termos_busca": ["capital", "private", "investimento", "envolve", "participação", "empresas", "encontram", "estado"],
        "descricao": "É o tipo de investimento que envolve a participação em empresas que já se encontram em um estado maduro de desenvolvimento e com alto potencial de crescimento.",
        "temas_relacionados": []
    },
    {
        "id": "processo_de_suitability",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Processo de Suitability"],
        "termos_busca": ["suitability", "processo", "verificar", "adequação", "produtos", "serviços", "operações"],
        "descricao": "É o processo para verificar a adequação de produtos, serviços ou operações realizadas nos mercados financeiro e de capitais ao perfil de um investidor.",
        "temas_relacionados": []
    },
    {
        "id": "produto_interno_bruto_pib",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Produto Interno Bruto (PIB)", "Produto Interno Bruto", "PIB"],
        "termos_busca": ["pib", "bruto", "interno", "produto", "soma", "bens", "serviços", "finais"],
        "descricao": "É a soma de todos os bens e serviços finais, na moeda local e a preços de mercado, produzidos em determinado pais ou região durante um certo período de tempo.",
        "temas_relacionados": []
    },
    {
        "id": "produtos_automaticos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Produtos Automaticos", "Produtos Automáticos"],
        "termos_busca": ["automáticos", "produtos", "serviços", "financeiros", "aplicação", "resgate", "automático"],
        "descricao": "São os produtos ou serviços financeiros de aplicação e resgate automático, destinados aos correntistas da instituição financeira.",
        "temas_relacionados": []
    },
    {
        "id": "prospecto_da_oferta",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Prospecto da Oferta"],
        "termos_busca": ["oferta", "prospecto", "documento", "oficial", "informativo", "emissão", "debêntures", "distribuição"],
        "descricao": "É o documento oficial e informativo de uma emissão de debêntures, com distribuição aberta aos potenciais investidores e que contém as características relevantes do processo.",
        "temas_relacionados": []
    },
    {
        "id": "proxy_voting",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Proxy Voting"],
        "termos_busca": ["voting", "proxy", "meio", "através", "acionista", "possa", "comparecer", "assembleia"],
        "descricao": "É o meio através do qual um acionista que não possa comparecer à assembleia de acionistas pode votar quanto às principais deliberações, normalmente em formato eletrônico.",
        "temas_relacionados": []
    },
    {
        "id": "ptax800",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["PTAX800"],
        "termos_busca": ["ptax", "transação", "constante", "sisbacen", "referente", "consulta", "taxas"],
        "descricao": "Transação constante do Sisbacen referente à consulta a Taxas de Câmbio Bacen.",
        "temas_relacionados": []
    },
    {
        "id": "pull_back",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Pull Back"],
        "termos_busca": ["back", "pull", "ação", "período", "negativo", "apresenta", "trajetória", "recuperação"],
        "descricao": "É quando uma ação com período negativo apresenta trajetória de recuperação ou potencial de retomada em sua cotação.",
        "temas_relacionados": []
    },
    {
        "id": "pullback",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Pullback"],
        "termos_busca": ["saiba", "identificar", "pullback", "aproveitar", "movimento", "mercado"],
        "descricao": "Saiba como identificar um Pullback e como aproveitar esse movimento de mercado em suas operações",
        "temas_relacionados": []
    },
    {
        "id": "puma",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["PUMA"],
        "termos_busca": ["puma", "sistema", "negociação", "títulos", "valores", "mobiliários", "renda"],
        "descricao": "É o sistema de negociação da B3 para títulos e valores mobiliários de renda variável.",
        "temas_relacionados": []
    },
    {
        "id": "quiet_period",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Quiet period", "Quiet períod"],
        "termos_busca": ["períod", "quiet", "período", "durante", "processo", "oferta", "pública", "distribuição"],
        "descricao": "Período no qual, durante o processo de oferta pública de distribuição de valores mobiliários, as instituições participantes não podem dar publicidade à oferta, ou se manifestar a respeito do emissor.",
        "temas_relacionados": []
    },
    {
        "id": "rally",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rally"],
        "termos_busca": ["rally", "termo", "representa", "movimento", "direcional", "rápido", "cima"],
        "descricao": "Termo representa um movimento direcional rápido (para cima ou para baixo) dos preços negociados em bolsa.",
        "temas_relacionados": []
    },
    {
        "id": "raspar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Raspar"],
        "termos_busca": ["raspar", "jargão", "equivalente", "comprar", "volume", "disponível", "ativo"],
        "descricao": "Jargão equivalente a comprar todo o volume disponível de um ativo a determinado preço de mercado",
        "temas_relacionados": []
    },
    {
        "id": "rdb",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["RDB"],
        "termos_busca": ["rdb", "recibo", "depósito", "bancário", "título", "privado", "representativos"],
        "descricao": "​Recibo de Depósito Bancário (RDB). É um título privado representativos de depósitos a prazo feitos por pessoas físicas ou jurídicas. É inegociável e intransferível.",
        "temas_relacionados": []
    },
    {
        "id": "realizar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Realizar"],
        "termos_busca": ["realizar", "zerar", "operação", "seja", "lucro", "prejuízo"],
        "descricao": "Zerar a operação seja ela com lucro ou prejuízo",
        "temas_relacionados": []
    },
    {
        "id": "rebalanceamento_de_carteira",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rebalanceamento de carteira"],
        "termos_busca": ["entenda", "papel", "rebalanceamento", "manutenção", "carteira", "compatível"],
        "descricao": "Entenda o papel do rebalanceamento na manutenção de uma carteira compatível com o perfil do investidor, os objetivos financeiros e as dinâmicas do mercado",
        "temas_relacionados": []
    },
    {
        "id": "redesconto_do_banco_central",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Redesconto do Banco Central", "RBC"],
        "termos_busca": ["central", "redesconto", "segundo", "operação", "concedida", "exclusivo", "critério", "banco"],
        "descricao": "Segundo o BCB, é a operação concedida a exclusivo critério do Banco Central, mediante solicitação da instituição financeira interessada, na modalidade de compra com compromisso de revenda ou na modalidade de redesconto (títulos e valores mobiliários e direitos creditórios descontados...",
        "temas_relacionados": []
    },
    {
        "id": "redesconto_intradia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Redesconto Intradia"],
        "termos_busca": ["intradia", "redesconto", "segundo", "operações", "curtíssimo", "prazo", "títulos", "públicos"],
        "descricao": "Segundo o BCB, são operações de curtíssimo prazo com títulos públicos federais registrados no Selic, na modalidade de compra com compromisso de revenda do Banco Central, conjugado a compromisso de recompra da instituição.",
        "temas_relacionados": []
    },
    {
        "id": "reits_real_estate_investment_trust",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["REITs (Real Estate Investment Trust)", "Real Estate Investment Trust", "REITs"],
        "termos_busca": ["trust", "investment", "estate", "real", "descubra", "reits", "funcionam", "tipos"],
        "descricao": "Descubra o que são REITs, como funcionam, tipos, vantagens, desvantagens e saiba como investir",
        "temas_relacionados": []
    },
    {
        "id": "renda",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Renda"],
        "termos_busca": ["renda", "segundo", "susep", "série", "pagamentos", "periódicos", "direito"],
        "descricao": "Segundo a SUSEP, é a série de pagamentos periódicos a que tem direito o assistido (ou assistidos), de acordo com a estrutura do plano de previdência complementar aberta.",
        "temas_relacionados": []
    },
    {
        "id": "renda_fixa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Renda Fixa"],
        "termos_busca": ["fixa", "renda", "entenda", "tudo", "você", "precisa", "saber", "investir"],
        "descricao": "Entenda tudo que você precisa saber antes de investir e saiba como escolher o melhor para o seu perfil financeiro",
        "temas_relacionados": []
    },
    {
        "id": "renda_variavel",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Renda Variavel", "Renda Variável"],
        "termos_busca": ["variável", "renda", "saiba", "principais", "tipos", "investimentos", "vantagens", "riscos"],
        "descricao": "Saiba o que é, principais tipos de investimentos, vantagens, riscos e como diversificar carteira",
        "temas_relacionados": []
    },
    {
        "id": "rendimentos_fii",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rendimentos (FII)", "Rendimentos", "FII"],
        "termos_busca": ["fii", "rendimentos", "distribuições", "lucros", "fundo", "imobiliário", "regra", "precisa"],
        "descricao": "São as distribuições dos lucros de um fundo imobiliário. Como regra, um FII precisa, obrigatoriamente, distribuir ao menos 95% do seu lucro semestral.",
        "temas_relacionados": []
    },
    {
        "id": "rentabilidade_absoluta",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rentabilidade Absoluta"],
        "termos_busca": ["absoluta", "rentabilidade", "retorno", "total", "obtido", "investimento", "expresso", "percentual"],
        "descricao": "Retorno total obtido em um investimento e expresso na forma de percentual sobre o valor investido.",
        "temas_relacionados": []
    },
    {
        "id": "rentabilidade_bruta",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rentabilidade Bruta"],
        "termos_busca": ["bruta", "rentabilidade", "retorno", "total", "obtido", "investimento", "descontos", "impostos"],
        "descricao": "Retorno total obtido em um investimento, sem os descontos de impostos.",
        "temas_relacionados": []
    },
    {
        "id": "rentabilidade_liquida",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rentabilidade Liquida", "Rentabilidade Líquida"],
        "termos_busca": ["líquida", "rentabilidade", "retorno", "obtido", "investimento", "descontados", "impostos", "taxas"],
        "descricao": "É o retorno obtido em um investimento, descontados os impostos e as taxas aplicáveis.",
        "temas_relacionados": []
    },
    {
        "id": "rentabilidade_nominal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rentabilidade Nominal"],
        "termos_busca": ["nominal", "rentabilidade", "absoluta", "retorno", "obtido", "investimento"],
        "descricao": "É a rentabilidade absoluta. O retorno obtido em um investimento.",
        "temas_relacionados": []
    },
    {
        "id": "rentabilidade_real",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rentabilidade Real"],
        "termos_busca": ["real", "rentabilidade", "obtida", "descontando", "inflação", "decorrida", "período"],
        "descricao": "É a rentabilidade obtida descontando-se a inflação decorrida no período da rentabilidade nominal.",
        "temas_relacionados": []
    },
    {
        "id": "rentabilidade_relativa",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Rentabilidade Relativa"],
        "termos_busca": ["relativa", "rentabilidade", "retorno", "investimento", "descontado", "variação", "benchmark", "índice"],
        "descricao": "É o retorno de um investimento, descontado a variação do seu benchmark, ou do índice de referência, apurando assim o ganho real do investimento.",
        "temas_relacionados": []
    },
    {
        "id": "repo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["REPO"],
        "termos_busca": ["repo", "segundo", "abreviação", "repurchase", "agreements", "acordos", "recompra"],
        "descricao": "Segundo o BCB, é a abreviação de Repurchase Agreements ou Acordos de Recompra ou a venda de um título de renda fixa com o compromisso de recomprá-lo em determinada data por determinado preço.",
        "temas_relacionados": []
    },
    {
        "id": "reserva_de_emergencia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Reserva de Emergencia", "Reserva de Emergência"],
        "termos_busca": ["emergência", "reserva", "planejada", "apenas", "proporciona", "tranquilidade", "tempos"],
        "descricao": "Ter uma reserva bem planejada não apenas proporciona tranquilidade em tempos de crise, mas também evita o endividamento desnecessário e permite decisões financeiras mais estratégicas e informadas.",
        "temas_relacionados": []
    },
    {
        "id": "reservas_bancarias",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Reservas Bancarias", "Reservas Bancárias"],
        "termos_busca": ["bancárias", "reservas", "segundo", "conta", "mantida", "bancos", "comerciais", "múltiplos"],
        "descricao": "Segundo o BCB, é a conta mantida pelos bancos comerciais, bancos múltiplos com carteira comercial, bancos de investimento e caixas econômicas no Banco Central do Brasil. A conta Reservas Bancárias é utilizada para processar diariamente a movimentação financeira dessas instituições,...",
        "temas_relacionados": []
    },
    {
        "id": "resolucoes_cvm",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Resolucoes CVM", "Resoluções CVM"],
        "termos_busca": ["cvm", "resoluções", "normas", "regulam", "mercado", "capitais", "garantir"],
        "descricao": "Resoluções CVM são normas que regulam o mercado de capitais, para garantir segurança, transparência e proteção a investidores",
        "temas_relacionados": []
    },
    {
        "id": "reversao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Reversao", "Reversão"],
        "termos_busca": ["reversão", "ocasião", "algum", "papel", "vendido", "vista", "compra"],
        "descricao": "Ocasião em que algum papel é vendido à vista para compra no mercado de opções.",
        "temas_relacionados": []
    },
    {
        "id": "risco",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco"],
        "termos_busca": ["risco", "possibilidade", "perda", "retorno", "negativo"],
        "descricao": "Possibilidade de perda ou de retorno negativo.",
        "temas_relacionados": []
    },
    {
        "id": "risco_cambial",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Cambial"],
        "termos_busca": ["saiba", "risco", "cambial", "afetar", "investimentos", "operações"],
        "descricao": "Saiba como o risco cambial pode afetar investimentos e operações internacionais e veja estratégias de proteção",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_custodia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Custodia", "Risco de Custódia"],
        "termos_busca": ["risco", "perda", "ativos", "mantidos", "custódia", "insolvência"],
        "descricao": "Risco de perda nos ativos mantidos sob custódia por insolvência do agente custodiante.",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_default_inadimplencia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Default (Inadimplencia)", "Risco de Default (Inadimplência)", "Risco de Default", "Inadimplencia", "Inadimplência"],
        "termos_busca": ["inadimplência", "default", "risco", "investidor", "reaver", "maneira", "integral", "parcial"],
        "descricao": "Risco de o investidor não reaver, de maneira integral ou parcial, o seu investimento original em um título de dívida.",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_downgrade",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Downgrade"],
        "termos_busca": ["downgrade", "risco", "mercado", "ativo", "financeiro", "causada", "queda"],
        "descricao": "Risco de mercado de um ativo financeiro causada pela queda na nota de crédito do emissor ou do próprio título por uma agencia de risco.",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_emissor",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Emissor"],
        "termos_busca": ["emissor", "segundo", "risco", "honrado", "compromisso", "relacionado", "emissão"],
        "descricao": "Segundo o BCB, é o risco de não ser honrado compromisso relacionado com a emissão ou o resgate do principal e acessórios do título ou valor mobiliário, no vencimento previsto.",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_liquidacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Liquidacao", "Risco de Liquidação"],
        "termos_busca": ["segundo", "risco", "liquidação", "sistema", "transferência", "realize"],
        "descricao": "Segundo o BCB, é o risco de que uma liquidação em um sistema de transferência não se realize segundo o esperado. Esse risco pode incluir tanto o risco de crédito quanto o de liquidez.",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_liquidez",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Liquidez"],
        "termos_busca": ["liquidez", "segundo", "risco", "instituição", "tornar", "incapaz", "honrar"],
        "descricao": "Segundo o BCB, é o risco de uma instituição se tornar incapaz de honrar suas obrigações ou de garantir condições para que sejam honradas.",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_principal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Principal"],
        "termos_busca": ["principal", "risco", "vendedor", "entregar", "ativo", "receber", "pagamento"],
        "descricao": "É o risco do vendedor entregar o ativo mas não receber o pagamento e/ou do comprador de efetuar o pagamento mas não receber o ativo.",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_spread",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Spread"],
        "termos_busca": ["spread", "risco", "mercado", "possibilidade", "perda", "decorrente", "variação"],
        "descricao": "Como o risco de mercado, é possibilidade de perda decorrente da variação nas taxas de juros no preço de um título de renda fixa causada pela variação no spread de crédito.",
        "temas_relacionados": []
    },
    {
        "id": "risco_de_taxa_de_juros",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco de Taxa de Juros", "RTJ"],
        "termos_busca": ["juros", "taxa", "risco", "mercado", "possibilidade", "perda", "decorrente", "variação"],
        "descricao": "Como o risco de mercado, é possibilidade de perda decorrente da variação nas taxas de juros no preço de um título de renda fixa.",
        "temas_relacionados": []
    },
    {
        "id": "risco_do_mercado_de_acoes",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco do Mercado de Acoes", "Risco do Mercado de Ações", "RMA"],
        "termos_busca": ["ações", "risco", "mercado", "possibilidade", "perda", "decorrente", "variação"],
        "descricao": "Como o risco de mercado, é possibilidade de perda decorrente da variação nos preços das ações",
        "temas_relacionados": []
    },
    {
        "id": "risco_financeiro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Financeiro"],
        "termos_busca": ["financeiro", "risco", "termo", "variedade", "riscos", "operações", "financeiras", "sejam"],
        "descricao": "É o termo de uma variedade de riscos em operações financeiras, sejam de crédito, de principal, de liquidez e de mercado.",
        "temas_relacionados": []
    },
    {
        "id": "risco_geopolitico",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Geopolitico", "Risco Geopolítico"],
        "termos_busca": ["geopolítico", "risco", "possibilidade", "perdas", "investimento", "conta", "alterações", "adversas"],
        "descricao": "Possibilidade de perdas em um investimento por conta de alterações adversas no cenário político em um país ou uma região.",
        "temas_relacionados": []
    },
    {
        "id": "risco_intradiario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["risco Intradiario", "risco Intradiário"],
        "termos_busca": ["intradiário", "risco", "compreendido", "início", "término", "sessão", "negociação"],
        "descricao": "Compreendido entre o início e o término da sessão de negociação.",
        "temas_relacionados": []
    },
    {
        "id": "risco_legal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Legal"],
        "termos_busca": ["risco", "descumprimento", "normas", "regulamentos", "legal", "surge"],
        "descricao": "Risco de descumprimento de normas ou regulamentos. O risco legal também surge se a aplicação das leis ou regulações é pouco clara.",
        "temas_relacionados": []
    },
    {
        "id": "risco_nao_sistematico",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco nao Sistematico", "Risco não Sistemático", "RNS"],
        "termos_busca": ["sistemático", "não", "risco", "específico", "empresa", "reduzido", "meio", "diversificação"],
        "descricao": "É o risco específico de cada empresa, que pode ser reduzido por meio de diversificação da carteira de investimentos.",
        "temas_relacionados": []
    },
    {
        "id": "risco_operacional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Operacional"],
        "termos_busca": ["operacional", "risco", "falha", "sistemas", "imprescindíveis", "funcionamento", "corporação"],
        "descricao": "Risco de falha em sistemas imprescindíveis ao funcionamento de uma corporação.",
        "temas_relacionados": []
    },
    {
        "id": "risco_pais",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Pais", "Risco País"],
        "termos_busca": ["país", "segundo", "conceito", "busca", "expressar", "objetiva", "risco"],
        "descricao": "Segundo o BCB, é um conceito que busca expressar de forma objetiva o risco de crédito a que investidores estrangeiros estão submetidos quando investem no País.",
        "temas_relacionados": []
    },
    {
        "id": "risco_previo_a_liquidacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Previo a Liquidacao", "Risco Prévio à Liquidação", "RPL"],
        "termos_busca": ["liquidação", "prévio", "segundo", "risco", "contraparte", "operação", "vigente", "completada"],
        "descricao": "Segundo o BCB, é o risco de que uma contraparte em uma operação vigente a ser completada em uma data futura não cumpra com o contrato ou acordo durante a vida da operação.",
        "temas_relacionados": []
    },
    {
        "id": "risco_regulatorio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Regulatorio", "Risco Regulatório"],
        "termos_busca": ["regulatório", "risco", "legal", "possibilidade", "perdas", "descumprimento", "normas"],
        "descricao": "Ver Risco Legal. É a possibilidade de perdas pelo descumprimento de normas à negociação de instrumentos financeiros em determinada localidade",
        "temas_relacionados": []
    },
    {
        "id": "risco_sistematico_nao_diversificavel",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Sistematico (nao diversificavel)", "Risco Sistemático (não diversificável)", "nao diversificavel", "não diversificável", "Risco Sistematico", "Risco Sistemático"],
        "termos_busca": ["diversificável", "não", "sistemático", "risco", "advindo", "fatores", "gerais", "comuns"],
        "descricao": "Risco advindo de fatores gerais e comuns ao mercado",
        "temas_relacionados": []
    },
    {
        "id": "risco_sistemico",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Sistemico", "Risco Sistêmico"],
        "termos_busca": ["sistêmico", "segundo", "risco", "inadimplência", "participante", "obrigações", "sistema"],
        "descricao": "Segundo o BCB, é o risco de que a inadimplência de um participante com suas obrigações em um sistema de transferência, ou em geral nos mercados financeiros, possa fazer com que outros participantes ou instituições financeiras não sejam capazes, por...",
        "temas_relacionados": []
    },
    {
        "id": "risco_total",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Total"],
        "termos_busca": ["total", "risco", "soma", "riscos", "sistemático"],
        "descricao": "É a soma dos riscos sistemático e não sistemático.",
        "temas_relacionados": []
    },
    {
        "id": "risco_tributario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Risco Tributario", "Risco Tributário"],
        "termos_busca": ["tributário", "risco", "mudanças", "regras", "tributárias", "possibilidade", "determinado"],
        "descricao": "Risco de mudanças nas regras tributárias. É a possibilidade de que sobre determinado investimento venham a incidir impostos e taxas não previstos originalmente.",
        "temas_relacionados": []
    },
    {
        "id": "roadshow",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Roadshow"],
        "termos_busca": ["roadshow", "evento", "exposição", "diferentes", "locais", "país", "finalidade"],
        "descricao": "É o evento ou exposição em diferentes locais do país com a finalidade de criar oportunidades de negócio por meio de lançamentos de produtos ou ativos financeiros.",
        "temas_relacionados": []
    },
    {
        "id": "roi",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ROI"],
        "termos_busca": ["roi", "return", "investiment", "retorno", "investimento", "podendo", "positivo"],
        "descricao": "Ou Return On Investiment, é o retorno sobre o investimento, podendo ser positivo ou negativo",
        "temas_relacionados": []
    },
    {
        "id": "roic",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["ROIC"],
        "termos_busca": ["roic", "return", "invested", "capital", "retorno", "investido", "calculado"],
        "descricao": "Ou Return on Invested Capital, é o retorno sobre o capital investido, calculado através do EBIT (lucro antes das despesas financeiras líquidas, do IRPJ e da CSLL), dividido pelo capital total empregado no negócio (Patrimônio Líquido mais as dívidas financeiras).",
        "temas_relacionados": []
    },
    {
        "id": "sampp_500",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["S&amp;P 500"],
        "termos_busca": ["amp", "composição", "diversificada", "abarca", "múltiplos", "setores", "economia"],
        "descricao": "Com composição diversificada que abarca múltiplos setores da economia, índice oferece a investidores visão crucial sobre tendências e flutuações do mercado e serve como referência essencial para estratégias de investimento e análises econômicas",
        "temas_relacionados": []
    },
    {
        "id": "salario_minimo",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Salario minimo", "Salário mínimo"],
        "termos_busca": ["salário", "mínimo", "estabelece", "piso", "salarial", "trabalhadores"],
        "descricao": "Salário mínimo estabelece piso salarial para trabalhadores, influencia a economia e define valores de benefícios sociais",
        "temas_relacionados": []
    },
    {
        "id": "sale_and_leaseback_slb",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sale and Leaseback (SLB)", "Sale and Leaseback", "SLB"],
        "termos_busca": ["slb", "leaseback", "and", "sale", "operação", "proprietário", "empreendimento", "realiza"],
        "descricao": "É um tipo de operação na qual o proprietário de um empreendimento realiza, ao mesmo tempo, a venda de imóvel e o contrato da sua locação. Dessa forma, o antigo proprietário passa a ser inquilino. Para o vendedor do imóvel,...",
        "temas_relacionados": []
    },
    {
        "id": "sardinha",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sardinha"],
        "termos_busca": ["sardinha", "termo", "empregado", "designar", "pequenos", "investidores"],
        "descricao": "Termo empregado para designar pequenos investidores.",
        "temas_relacionados": []
    },
    {
        "id": "scalping",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Scalping"],
        "termos_busca": ["scalping", "entenda", "funciona", "estratégia", "trading", "visa", "pequenos"],
        "descricao": "Entenda como funciona essa estratégia de trading que visa pequenos lucros em várias operações rápidas",
        "temas_relacionados": []
    },
    {
        "id": "sec_securities_and_exchange_commission",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["SEC (Securities and Exchange Commission)", "Securities and Exchange Commission", "SEC"],
        "termos_busca": ["and", "sec", "entenda", "securities", "exchange", "commission", "funções", "impacto"],
        "descricao": "Entenda o que é SEC (Securities and Exchange Commission), suas funções, impacto no mercado financeiro e importância na regulação de valores mobiliários",
        "temas_relacionados": []
    },
    {
        "id": "securitizacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Securitizacao", "Securitização"],
        "termos_busca": ["securitização", "trata", "processo", "conversão", "dívida", "títulos", "negociáveis"],
        "descricao": "Trata-se de um processo de conversão de dívida em títulos negociáveis no mercado.",
        "temas_relacionados": []
    },
    {
        "id": "segmento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Segmento"],
        "termos_busca": ["segmento", "agrupamento", "empresas", "segundo", "objetivo", "social"],
        "descricao": "Agrupamento de empresas segundo o seu objetivo social.",
        "temas_relacionados": []
    },
    {
        "id": "segunda_linha",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Segunda linha"],
        "termos_busca": ["linha", "segunda", "aquelas", "menor", "liquidez", "seja", "volume", "negociações"],
        "descricao": "São aquelas de menor liquidez, ou seja, com menor volume de negociações.",
        "temas_relacionados": []
    },
    {
        "id": "sisbacen",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sisbacen"],
        "termos_busca": ["lançado", "sisbacen", "tornou", "instrumento", "crucial", "supervisão"],
        "descricao": "Lançado em 1985, o Sisbacen se tornou um instrumento crucial para a supervisão e regulação do sistema financeiro nacional, permitindo ao Banco Central monitorar as operações das instituições financeiras, realizar análises econômicas detalhadas e implementar políticas monetárias eficazes.",
        "temas_relacionados": []
    },
    {
        "id": "sistema_cambio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema Cambio", "Sistema Câmbio"],
        "termos_busca": ["sistema", "registradas", "operações", "câmbio", "realizadas", "instituições"],
        "descricao": "Sistema em que são registradas todas as operações de câmbio realizadas pelas instituições autorizadas a operar no mercado de câmbio.",
        "temas_relacionados": []
    },
    {
        "id": "sistema_de_distribuicao_de_valores_mobiliarios",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema de Distribuicao de Valores Mobiliarios", "Sistema de Distribuição de Valores Mobiliários", "SDVM"],
        "termos_busca": ["mobiliários", "valores", "distribuição", "sistema", "segundo", "composto", "determinadas", "instituições"],
        "descricao": "Segundo a Lei 6385/76, é composto, na forma da lei, por determinadas instituições participantes do mercado de capitais. Sua função é a distribuição pública de títulos e valores mobiliários no mercado.",
        "temas_relacionados": []
    },
    {
        "id": "sistema_de_metas_para_a_inflacao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema de Metas para a Inflacao", "Sistema de Metas para a Inflação", "SMPI"],
        "termos_busca": ["inflação", "para", "metas", "sistema", "adotado", "diretriz", "política", "monetária"],
        "descricao": "Sistema adotado em 1999 como diretriz de política monetária. Desde então, as decisões do Comitê de Política Monetária (Copom) passaram a ter como objetivo cumprir as metas para a inflação definidas pelo Conselho Monetário Nacional.",
        "temas_relacionados": []
    },
    {
        "id": "sistema_de_pagamentos_brasileiro_spb",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema de Pagamentos Brasileiro (SPB)", "Sistema de Pagamentos Brasileiro", "SPB"],
        "termos_busca": ["spb", "segundo", "sistema", "pagamentos", "brasileiro", "compreende", "entidades"],
        "descricao": "Segundo o BCB, o Sistema de Pagamentos Brasileiro (SPB) compreende as entidades, os sistemas e os procedimentos relacionados com o processamento e a liquidação de operações de transferência de fundos, de operações com moeda estrangeira ou com ativos financeiros e...",
        "temas_relacionados": []
    },
    {
        "id": "sistema_de_registro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema de Registro"],
        "termos_busca": ["registro", "sistema", "segundo", "infraestrutura", "mercado", "financeiro", "operada", "entidade"],
        "descricao": "Segundo o BCB, é a infraestrutura do mercado financeiro operada por entidade registradora, para o armazenamento de informações referentes a ativos financeiros não objeto de depósito centralizado.",
        "temas_relacionados": []
    },
    {
        "id": "sistema_de_transferencia_de_credito",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema de Transferencia de Credito", "Sistema de Transferência de Crédito", "STC"],
        "termos_busca": ["crédito", "segundo", "sistema", "transferência", "fundos", "ordens", "pagamento"],
        "descricao": "Segundo o BCB, é o sistema de transferência de fundos, em que as ordens de pagamento se movem do (banco do) iniciador da mensagem de transferência ou pagador ao (banco do) receptor da mensagem ou beneficiário.",
        "temas_relacionados": []
    },
    {
        "id": "sistema_financeiro_nacional_sfn",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema Financeiro Nacional (SFN)", "Sistema Financeiro Nacional", "SFN"],
        "termos_busca": ["sfn", "nacional", "financeiro", "sistema", "conjunto", "instituições", "financeiras", "bancárias"],
        "descricao": "Conjunto de instituições financeiras bancárias e não bancarias, bem como os prestadores de serviço de pagamentos que viabilizam o fluxo financeiro entre os poupadores e os tomadores na economia.",
        "temas_relacionados": []
    },
    {
        "id": "sistema_hibrido",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema Hibrido", "Sistema Híbrido"],
        "termos_busca": ["híbrido", "sistema", "pagamento", "combina", "características", "sistemas", "lbtrs"],
        "descricao": "Sistema de pagamento que combina características de sistemas LBTRs (Liquidação pelo Valor Bruto em Tempo Real) e sistemas de apuração de saldos.",
        "temas_relacionados": []
    },
    {
        "id": "sistema_monetario",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sistema Monetario", "Sistema Monetário"],
        "termos_busca": ["monetário", "sistema", "conjunto", "cédulas", "moedas", "adotado", "país"],
        "descricao": "Conjunto de cédulas e moedas adotado por um país.",
        "temas_relacionados": []
    },
    {
        "id": "small_caps",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Small Caps"],
        "termos_busca": ["caps", "small", "classificação", "identifica", "ações", "empresas", "pequena", "capitalização"],
        "descricao": "Classificação que identifica a ações de empresas com pequena capitalização, ou seja, que possuem menor valor de mercado.",
        "temas_relacionados": []
    },
    {
        "id": "sml",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["SML"],
        "termos_busca": ["sml", "sistema", "pagamentos", "moeda", "local", "segundo", "pagamento"],
        "descricao": "Sistema de Pagamentos em Moeda Local. Segundo o BCB, é um sistema de pagamento internacional administrado pelo Banco Central do Brasil em parceria com os bancos centrais da Argentina, Uruguai e Paraguai.",
        "temas_relacionados": []
    },
    {
        "id": "smll_b3_indice_small_cap",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["SMLL B3 (Indice Small Cap)", "SMLL B3 (Índice Small Cap)", "Indice Small Cap", "Índice Small Cap", "SMLL B3"],
        "termos_busca": ["cap", "small", "conheça", "smll", "índice", "mede", "desempenho", "ações"],
        "descricao": "Conheça o SMLL, índice da B3 que mede desempenho de ações de empresas brasileiras de menor capitalização, chamadas small caps",
        "temas_relacionados": []
    },
    {
        "id": "sobredemanda",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Sobredemanda"],
        "termos_busca": ["sobredemanda", "excesso", "demanda", "oferta", "distribuição", "ações", "mercado"],
        "descricao": "É o excesso de demanda em uma oferta ou distribuição de ações no mercado primário.",
        "temas_relacionados": []
    },
    {
        "id": "special_account",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Special Account"],
        "termos_busca": ["account", "special", "contas", "moeda", "estrangeira", "tais", "destinadas", "receber"],
        "descricao": "Contas em moeda estrangeira. Tais contas são destinadas a receber créditos especiais concedidos por organismos internacionais a instituições da administração pública direta ou indireta sejam elas federal, estadual, municipal e do Distrito Federal.",
        "temas_relacionados": []
    },
    {
        "id": "stablecoins",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Stablecoins"],
        "termos_busca": ["stablecoins", "conheça", "criptomoeda", "entenda", "diferente", "tradicionais", "bitcoin"],
        "descricao": "Conheça esse tipo de criptomoeda e entenda por que é diferente das tradicionais Bitcoin e Ethereum",
        "temas_relacionados": []
    },
    {
        "id": "stock_pick",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Stock Pick"],
        "termos_busca": ["pick", "stock", "escolha", "ações", "investidor", "utiliza", "sistemática", "análise"],
        "descricao": "Ou escolha de ações, é quando o investidor utiliza uma forma sistemática de análise para determinar quais ações devem ser incluídos em seu portfólio, por representarem boas oportunidades de retorno financeiro.",
        "temas_relacionados": []
    },
    {
        "id": "str",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["STR"],
        "termos_busca": ["str", "segundo", "sistema", "transferência", "fundos", "liquidação", "bruta"],
        "descricao": "Segundo o BCB, é o sistema de transferência de fundos com liquidação bruta em tempo real (LBTR), gerido e operado pelo Banco Central do Brasil. Funciona com base em ordens de crédito, isto é, somente o titular da conta a...",
        "temas_relacionados": []
    },
    {
        "id": "subcustodiante",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Subcustodiante"],
        "termos_busca": ["subcustodiante", "segundo", "custodiante", "global", "mantém", "ativos", "valores"],
        "descricao": "Segundo o BCB, quando um custodiante global mantém ativos e valores mobiliários por meio de outro custodiante local, este último é chamado de subcustodiante.",
        "temas_relacionados": []
    },
    {
        "id": "subscrever",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Subscrever"],
        "termos_busca": ["subscrever", "exercer", "direito", "subscrição", "ações"],
        "descricao": "Exercer o direito a subscrição de ações",
        "temas_relacionados": []
    },
    {
        "id": "tabela_regressiva_do_imposto_de_renda",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Tabela regressiva do Imposto de Renda", "TRIR"],
        "termos_busca": ["renda", "imposto", "entenda", "tabela", "regressiva", "sistema", "diminui", "alíquota"],
        "descricao": "Entenda a tabela regressiva do IR, sistema que diminui a alíquota do imposto quanto maior o prazo do seu investimento",
        "temas_relacionados": []
    },
    {
        "id": "take_over",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Take Over"],
        "termos_busca": ["over", "take", "chamado", "oferta", "hostil", "tomada", "controle", "companhia"],
        "descricao": "Também chamado de Oferta Hostil, é quando há uma tomada de controle de uma companhia por outro grupo por meio de compra de ações, sem o conhecimento ou consentimento dos seus acionistas.",
        "temas_relacionados": []
    },
    {
        "id": "tape_reading",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Tape Reading"],
        "termos_busca": ["reading", "tape", "conheça", "técnica", "leitura", "fluxo", "ordens", "ajuda"],
        "descricao": "Conheça a técnica de leitura de fluxo de ordens que ajuda traders a identificar movimentos de grandes players no mercado",
        "temas_relacionados": []
    },
    {
        "id": "target",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Target"],
        "termos_busca": ["target", "valor", "estabelecido", "investidor", "objetivo", "lucro", "operação"],
        "descricao": "É o valor estabelecido pelo investidor como objetivo de lucro de uma operação.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_cambio",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Cambio", "Taxa de Câmbio"],
        "termos_busca": ["câmbio", "taxa", "preço", "moeda", "termos", "razão", "conversão", "duas"],
        "descricao": "Preço de uma moeda em termos de outra moeda. É a razão de conversão entre duas moedas distintas.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_cambio_real_efetiva",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Cambio Real Efetiva", "Taxa de Câmbio Real Efetiva", "TCRE"],
        "termos_busca": ["real", "segundo", "taxa", "câmbio", "efetiva", "competitividade", "exportações"],
        "descricao": "Segundo o BCB, é a taxa de câmbio efetiva de competitividade das exportações, dada pela cotação do real em relação às moedas de nossos 15 principais mercados, ponderada pela participação desses países no total das exportações brasileiras.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_cambio_spot",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Cambio Spot", "Taxa de Câmbio Spot", "TCS"],
        "termos_busca": ["spot", "câmbio", "taxa", "compra", "venda", "imediata", "dólares", "conhecida"],
        "descricao": "Taxa para compra e venda imediata de dólares, também conhecida como “dólar pronto”.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_carregamento",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Carregamento"],
        "termos_busca": ["carregamento", "taxa", "segundo", "susep", "percentual", "incidente", "contribuições", "pagas"],
        "descricao": "Segundo a Susep, é o percentual incidente sobre as contribuições pagas pelo participante, para fazer face às despesas administrativas, às de corretagem e às de comercialização de um plano de previdência complementar.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_consenso",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Consenso"],
        "termos_busca": ["consenso", "taxa", "mercado", "objeto", "leilão", "títulos", "públicos"],
        "descricao": "É a taxa de mercado para o objeto do leilão de títulos públicos federais obtida pelas instituições dealers.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_corretagem",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Corretagem"],
        "termos_busca": ["corretagem", "taxa", "valor", "cobrado", "corretoras", "remuneração", "operações", "compra"],
        "descricao": "Valor cobrado pelas corretoras como remuneração pelas operações de compra e venda de ações e demais ativos financeiros.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_custodia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Custodia", "Taxa de Custódia"],
        "termos_busca": ["custódia", "taxa", "cobrada", "instituições", "financeiras", "serviço", "manutenção"],
        "descricao": "Taxa cobrada por instituições financeiras pelo serviço de manutenção dos ativos em uma conta de custódia própria.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_ingresso",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Ingresso"],
        "termos_busca": ["ingresso", "taxa", "entrada", "paga", "investidor", "aplicar", "recursos"],
        "descricao": "Taxa de entrada paga pelo investidor ao aplicar recursos em um fundo de investimento.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_juro",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Juro"],
        "termos_busca": ["juro", "taxa", "custo", "empréstimo", "definido", "razão", "percentual", "cobrável"],
        "descricao": "Custo de um empréstimo, definido como a razão percentual cobrável no fim do período da operação.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_juros_equivalente",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Juros Equivalente", "TJE"],
        "termos_busca": ["equivalente", "taxa", "diferentes", "taxas", "juros", "consideradas", "equivalentes", "geram"],
        "descricao": "As diferentes taxas de juros são consideradas equivalentes quando geram valores iguais ao ser aplicadas sobre um mesmo montante e por um mesmo período de tempo.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_juros_implicita",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Juros Implicita", "Taxa de Juros Implícita", "TJI"],
        "termos_busca": ["implícita", "taxa", "segundo", "quociente", "despesas", "receitas", "juros", "nominais"],
        "descricao": "Segundo o BCB, é o quociente entre as despesas ou receitas de juros nominais e os saldos de dívidas ou de ativos, acrescidos dos fluxos primários ocorridos no mês de referência.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_juros_nominal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Juros Nominal", "TJN"],
        "termos_busca": ["nominal", "taxa", "juros", "contratada", "operação", "financeira"],
        "descricao": "Taxa de juros contratada em uma operação financeira.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_juros_real",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Juros Real", "TJR"],
        "termos_busca": ["real", "taxa", "juros", "efeito", "inflação", "calculada", "descontando"],
        "descricao": "Taxa de juros sem o efeito da inflação. É calculada descontando a taxa de inflação da taxa de juros nominal obtida em um investimento e considerando o mesmo período de tempo.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_de_saida",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa de Saida", "Taxa de Saída"],
        "termos_busca": ["taxa", "saída", "paga", "investidor", "resgatar", "recursos"],
        "descricao": "Taxa de saída paga pelo investidor ao resgatar recursos em um fundo de investimento.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_di",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa DI"],
        "termos_busca": ["entenda", "taxa", "calculada", "serve", "referência", "essencial"],
        "descricao": "Entenda o que é Taxa DI, como é calculada e por que serve como referência essencial para investimentos e contratos no mercado financeiro",
        "temas_relacionados": []
    },
    {
        "id": "taxa_interna_de_retorno_tir",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa Interna de Retorno (TIR)", "Taxa Interna de Retorno", "TIR"],
        "termos_busca": ["tir", "retorno", "interna", "taxa", "desconto", "utilizada", "trazer", "valor"],
        "descricao": "É a taxa de desconto que, quando utilizada para trazer ao valor presente um fluxo de caixa futuro, iguala os valores de receitas e despesas.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_ptax",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa PTAX"],
        "termos_busca": ["ptax", "taxa", "valor", "representativo", "cotações", "dólar", "mercado", "spot"],
        "descricao": "Valor representativo das cotações do dólar no mercado spot, calculada diariamente pelo Banco Central do Brasil com base em quatro observações feitas ao longo do dia.",
        "temas_relacionados": []
    },
    {
        "id": "taxa_referencial_tr",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa Referencial (TR)", "Taxa Referencial"],
        "termos_busca": ["referencial", "taxa", "calculada", "banco", "central", "brasil", "base"],
        "descricao": "Taxa calculada pelo Banco Central do Brasil com base na média das taxas de juros das LTN (Letras do Tesouro Nacional) utilizada no cálculo do rendimento das cadernetas de poupança e dos juros dos empréstimos do Sistema Financeiro da Habitação...",
        "temas_relacionados": []
    },
    {
        "id": "taxa_selic",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa Selic"],
        "termos_busca": ["descubra", "taxa", "selic", "funciona", "impacto", "economia"],
        "descricao": "Descubra o que é a taxa Selic, como funciona, seu impacto na economia e nos investimentos. Entenda por que ela é tão importante",
        "temas_relacionados": []
    },
    {
        "id": "taxa_sml",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxa SML"],
        "termos_busca": ["sml", "taxa", "segundo", "valor", "convertidos", "valores", "fixados", "operações"],
        "descricao": "Segundo o BCB, é o valor pelo qual são convertidos os valores fixados das operações cursadas no Sistema de Pagamentos em Moeda Local (SML) na moeda da parte emissora da ordem de pagamento. São divulgadas duas taxas SML: Real/Peso, pelo...",
        "temas_relacionados": []
    },
    {
        "id": "taxas_de_juros_proporcionais",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Taxas de Juros Proporcionais", "TJP"],
        "termos_busca": ["proporcionais", "juros", "regime", "capitalização", "simples", "taxas", "expressas", "unidades"],
        "descricao": "No regime de capitalização simples, são taxas expressas em unidades diferentes de tempo, mas que se aplicadas a um mesmo valor durante um mesmo prazo, resultarão em um mesmo montante.",
        "temas_relacionados": []
    },
    {
        "id": "temporada_de_balancos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Temporada de Balancos", "Temporada de Balanços"],
        "termos_busca": ["entenda", "temporada", "balanços", "funciona", "importância", "mercado"],
        "descricao": "Entenda o que é a temporada de balanços, como funciona, sua importância para o mercado financeiro e como interpretar os resultados divulgados.",
        "temas_relacionados": []
    },
    {
        "id": "termo_de_anuencia_dos_acionistas_controladores",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Termo de Anuencia dos Acionistas Controladores", "Termo de Anuência dos Acionistas Controladores", "TADAC"],
        "termos_busca": ["controladores", "acionistas", "dos", "anuência", "termos", "regulamento", "novo", "mercado"],
        "descricao": "Nos termos do Regulamento do Novo Mercado, significa termo pelo qual os acionistas controladores de uma companhia se responsabilizam pessoalmente a se submeter e a agir em conformidade com o Contrato de Participação no Novo Mercado, com o Regulamento do...",
        "temas_relacionados": []
    },
    {
        "id": "termo_de_anuencia_dos_administradores",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Termo de Anuencia dos Administradores", "Termo de Anuência dos Administradores", "TADA"],
        "termos_busca": ["administradores", "dos", "anuência", "termos", "regulamento", "novo", "mercado", "significa"],
        "descricao": "Nos termos do Regulamento do Novo Mercado, significa o termo pelo qual os administradores da Companhia se responsabilizam pessoalmente a se submeter e a agir em conformidade com o Contrato de Participação no Novo Mercado, com o Regulamento do Novo...",
        "temas_relacionados": []
    },
    {
        "id": "termo_de_compromisso",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Termo de Compromisso"],
        "termos_busca": ["compromisso", "termo", "documento", "agente", "regulado", "corrigir", "compensar", "infrações"],
        "descricao": "Documento de um agente regulado a fim de corrigir ou compensar infrações regulatórias no âmbito da autorregulação.",
        "temas_relacionados": []
    },
    {
        "id": "tesouro_ipca_ntnb_principal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Tesouro IPCA (NTN-B Principal)", "NTN-B Principal", "Tesouro IPCA"],
        "termos_busca": ["principal", "ntn", "ipca", "notas", "tesouro", "nacional", "série", "título"],
        "descricao": "Notas do Tesouro Nacional Série B. Título público federal de remuneração pós-fixada, atrelado à variação do IPCA sem pagamento de cupons semestrais",
        "temas_relacionados": []
    },
    {
        "id": "tesouro_ipca_com_juros_semestrais_ntnb",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Tesouro IPCA com Juros Semestrais (NTN-B)", "Tesouro IPCA com Juros Semestrais", "NTN-B"],
        "termos_busca": ["ntn", "semestrais", "juros", "com", "ipca", "notas", "tesouro", "nacional"],
        "descricao": "Notas do Tesouro Nacional Série B. Título público federal de remuneração pós-fixada, atrelado à variação do IPCA com pagamento de cupons semestrais",
        "temas_relacionados": []
    },
    {
        "id": "tesouro_nacional",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Tesouro Nacional"],
        "termos_busca": ["nacional", "tesouro", "espinha", "dorsal", "finanças", "públicas", "país", "desempenha"],
        "descricao": "Espinha dorsal das finanças públicas de um país, desempenha papel essencial na gestão, no planejamento e no controle dos recursos financeiros governamentais",
        "temas_relacionados": []
    },
    {
        "id": "tesouro_posfixado",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Tesouro Pos-Fixado", "Tesouro Pós-Fixado"],
        "termos_busca": ["pós", "tesouro", "fixado", "opção", "investimento", "rentabilidade", "atrelada"],
        "descricao": "Tesouro Pós-Fixado é uma opção de investimento com rentabilidade atrelada à Selic ou ao IPCA; entenda como funciona e vantagens",
        "temas_relacionados": []
    },
    {
        "id": "tesouro_prefixado_com_juros_semestrais_ntnf",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Tesouro Prefixado com Juros Semestrais (NTN-F)", "Tesouro Prefixado com Juros Semestrais", "NTN-F"],
        "termos_busca": ["ntn", "semestrais", "juros", "com", "prefixado", "nota", "tesouro", "nacional"],
        "descricao": "Nota do Tesouro Nacional Série F. Título público federal de remuneração prefixada com remuneração calculada em função do desconto sobre o Valor Nominal (R$1.000,00) e com pagamento de cupons semestrais.",
        "temas_relacionados": []
    },
    {
        "id": "time_deposits",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Time Deposits"],
        "termos_busca": ["deposits", "time", "depósitos", "interbancários", "negociados", "mercado", "internacional", "prazo"],
        "descricao": "Depósitos interbancários negociados no mercado internacional com prazo fixo e inegociáveis até o vencimento.",
        "temas_relacionados": []
    },
    {
        "id": "titulo_da_divida_agraria_tda",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Titulo da Divida Agraria (TDA)", "Título da Dívida Agrária (TDA)", "Titulo da Divida Agraria", "Título da Dívida Agrária", "TDA"],
        "termos_busca": ["tda", "agrária", "dívida", "título", "responsabilidade", "tesouro", "nacional", "emitido"],
        "descricao": "Título de responsabilidade do Tesouro Nacional, emitido escrituralmente para a promoção da reforma agrária, com rentabilidade pós-fixada pela variação da TR mais um taxa fixa.",
        "temas_relacionados": []
    },
    {
        "id": "titulo_de_credito",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Titulo de Credito", "Título de Crédito"],
        "termos_busca": ["crédito", "título", "documento", "representativo", "obrigação", "pagar", "valor", "nele"],
        "descricao": "É o documento representativo de uma obrigação de pagar o valor que nele está escrito, revestido de liquidez e certeza.",
        "temas_relacionados": []
    },
    {
        "id": "titulo_publico_federal",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Titulo Publico Federal", "Título Público Federal", "TPF"],
        "termos_busca": ["federal", "público", "título", "instrumentos", "financeiros", "renda", "fixa", "emitidos"],
        "descricao": "São instrumentos financeiros de renda fixa emitidos pelo Governo Federal para obtenção de recursos junto à sociedade.",
        "temas_relacionados": []
    },
    {
        "id": "titulos_posfixados",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Titulos Pos-Fixados", "Títulos Pós-Fixados"],
        "termos_busca": ["fixados", "pós", "títulos", "título", "cuja", "rentabilidade", "varia", "acordo"],
        "descricao": "Título cuja rentabilidade varia de acordo com um índice de referência.",
        "temas_relacionados": []
    },
    {
        "id": "titulos_prefixados",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Titulos Pre-Fixados", "Títulos Pré-Fixados"],
        "termos_busca": ["fixados", "pré", "títulos", "título", "cuja", "rentabilidade", "preestabelecida", "momento"],
        "descricao": "Título cuja rentabilidade é preestabelecida no momento da contratação.",
        "temas_relacionados": []
    },
    {
        "id": "titulos_privados",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Titulos Privados", "Títulos Privados"],
        "termos_busca": ["privados", "títulos", "emitidos", "instituições", "caracterizadas", "agentes", "públicos"],
        "descricao": "Títulos emitidos por instituições não caracterizadas como agentes públicos para a captação de recursos para financiar suas atividades.",
        "temas_relacionados": []
    },
    {
        "id": "titulos_publicos",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Titulos Publicos", "Títulos Públicos"],
        "termos_busca": ["títulos", "emitidos", "instituições", "agentes", "caracterizadas", "públicos"],
        "descricao": "Títulos emitidos por instituições ou agentes caracterizadas como agentes públicos para a captação de recursos para financiar suas atividades.",
        "temas_relacionados": []
    },
    {
        "id": "tjlp",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["TJLP"],
        "termos_busca": ["taxa", "juros", "longo", "prazo", "regulada", "tjlp"],
        "descricao": "Taxa de Juros de Longo Prazo, regulada pela Lei 9.365, de 16/12/1996 e Lei 10.183, de 12/2/2001. A TJLP é fixada pelo Conselho Monetário Nacional e divulgada até o último dia útil do trimestre imediatamente anterior ao de sua vigência....",
        "temas_relacionados": []
    },
    {
        "id": "tlp",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["TLP"],
        "termos_busca": ["tlp", "taxa", "longo", "prazo", "segundo", "bndes", "definida"],
        "descricao": "Taxa de Longo Prazo. Segundo o BNDES, a TLP é definida pelo Índice de Preços ao Consumidor Amplo (IPCA), mais a taxa de juro real da NTN-B de cinco anos.",
        "temas_relacionados": []
    },
    {
        "id": "tomar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Tomar"],
        "termos_busca": ["tomar", "adquire", "ativo", "quantidade", "preço", "sugeridos"],
        "descricao": "Quando se adquire um ativo pela quantidade e preço sugeridos.",
        "temas_relacionados": []
    },
    {
        "id": "top_pick",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Top Pick"],
        "termos_busca": ["pick", "top", "ativo", "mercado", "considerado", "melhor", "opção", "algum"],
        "descricao": "Ativo ou mercado considerado como melhor opção por algum analista ou instituição.",
        "temas_relacionados": []
    },
    {
        "id": "touro_bullish",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Touro (Bullish)", "Bullish", "Touro"],
        "termos_busca": ["bullish", "touro", "mercado", "tendência", "alta"],
        "descricao": "Mercado com tendência de alta.",
        "temas_relacionados": []
    },
    {
        "id": "trigger_ou_gatilho",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Trigger ou Gatilho"],
        "termos_busca": ["gatilho", "trigger", "determina", "fato", "desencadeou", "movimento", "alta", "baixa"],
        "descricao": "Determina o fato que desencadeou o movimento de alta e baixa de uma ação.",
        "temas_relacionados": []
    },
    {
        "id": "tubaraoshark",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["tubarão", "tubarao", "shark"],
        "termos_busca": ["shark", "tubarão", "termo", "empregado", "grandes", "investidores"],
        "descricao": "Termo empregado a grandes investidores.",
        "temas_relacionados": []
    },
    {
        "id": "underwritting",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Underwritting"],
        "termos_busca": ["underwritting", "subscrição", "operações", "financeiras", "agentes", "financeiros", "intermediam"],
        "descricao": "Ou Subscrição, são operações financeiras nas quais os agentes financeiros intermediam o lançamento e a distribuição de ações ou títulos de renda fixa no mercado de capitais.",
        "temas_relacionados": []
    },
    {
        "id": "units",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Units"],
        "termos_busca": ["units", "ativos", "compostos", "classe", "valores", "mobiliários", "ação"],
        "descricao": "São ativos compostos por mais de uma classe de valores mobiliários, como uma ação ordinária e uma ação preferencial, por exemplo, negociados em conjunto. As units são compradas e/ou vendidas no mercado como uma unidade.",
        "temas_relacionados": []
    },
    {
        "id": "upside",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Upside"],
        "termos_busca": ["upside", "potencial", "valorização", "determinado", "ativo"],
        "descricao": "É o potencial de valorização de determinado ativo.",
        "temas_relacionados": []
    },
    {
        "id": "urso_bearish",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Urso (Bearish)", "Bearish", "Urso"],
        "termos_busca": ["bearish", "urso", "mercado", "tendência", "queda"],
        "descricao": "Mercado com tendência de queda.",
        "temas_relacionados": []
    },
    {
        "id": "us_gaap",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["US GAAP"],
        "termos_busca": ["gaap", "princípios", "contábeis", "geralmente", "aceitos", "estados", "unidos"],
        "descricao": "Princípios contábeis geralmente aceitos nos Estados Unidos da América.",
        "temas_relacionados": []
    },
    {
        "id": "us_treasuries",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["US Treasuries"],
        "termos_busca": ["treasuries", "títulos", "renda", "fixa", "emitidos", "tesouro", "chamados"],
        "descricao": "Títulos de renda fixa emitidos pelo Tesouro dos EUA chamados de Bills, Notes ou Bonds.",
        "temas_relacionados": []
    },
    {
        "id": "util_b3_indice_de_utilidade_publica",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["UTIL B3 (Indice de Utilidade Publica)", "UTIL B3 (Índice de Utilidade Pública)", "Indice de Utilidade Publica", "Índice de Utilidade Pública", "UTIL B3"],
        "termos_busca": ["pública", "utilidade", "conheça", "util", "índice", "mede", "desempenho", "ações"],
        "descricao": "Conheça o UTIL, índice da B3 que mede desempenho de ações de empresas de utilidade pública, como energia, saneamento e gás",
        "temas_relacionados": []
    },
    {
        "id": "vacancia_fisica",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Vacancia Fisica", "Vacância Física"],
        "termos_busca": ["física", "vacância", "espaço", "vago", "desocupado", "empreendimento", "imobiliário"],
        "descricao": "É o espaço vago ou desocupado de um empreendimento imobiliário.",
        "temas_relacionados": []
    },
    {
        "id": "valor_ao_par",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Valor ao Par"],
        "termos_busca": ["par", "valor", "face", "título"],
        "descricao": "Valor de face de um título.",
        "temas_relacionados": []
    },
    {
        "id": "valor_de_face",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Valor de Face"],
        "termos_busca": ["face", "valor", "título", "obrigação", "expresso", "instrumento", "montante"],
        "descricao": "Ou Valor ao Par, é o valor de um título ou obrigação, expresso no instrumento. É o montante principal sobre o qual é calculado o pagamento de juros.",
        "temas_relacionados": []
    },
    {
        "id": "valor_de_referencia",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Valor de Referencia", "Valor de Referência"],
        "termos_busca": ["referência", "valor", "unitário", "ativo", "operações", "realizadas", "acordo"],
        "descricao": "Valor unitário do ativo para as operações realizadas de acordo com referencia em mercado",
        "temas_relacionados": []
    },
    {
        "id": "valor_intrinseco",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Valor Intrinseco", "Valor Intrínseco"],
        "termos_busca": ["intrínseco", "valor", "estimado", "análise", "investimentos", "obtido", "modelos"],
        "descricao": "Valor estimado em análise de investimentos obtido por modelos de avaliação",
        "temas_relacionados": []
    },
    {
        "id": "valor_nominal_vn",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Valor Nominal (VN)", "Valor Nominal"],
        "termos_busca": ["nominal", "segundo", "valor", "unitário", "título", "explicitamente", "informado"],
        "descricao": "Segundo o BCB, é o valor unitário de um título, explicitamente informado no estatuto ou contrato social.",
        "temas_relacionados": []
    },
    {
        "id": "valor_nominal_atualizado_vna",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Valor Nominal Atualizado (VNA)", "Valor Nominal Atualizado", "VNA"],
        "termos_busca": ["vna", "atualizado", "nominal", "valor", "emissão", "título", "corrigido", "índice"],
        "descricao": "Valor de emissão de um título corrigido por um índice definido em contrato.",
        "temas_relacionados": []
    },
    {
        "id": "valores_mobiliarios",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Valores Mobiliarios", "Valores Mobiliários"],
        "termos_busca": ["segundo", "artigo", "valores", "mobiliários", "ofertados", "publicamente"],
        "descricao": "Segundo a Lei 6385/76, artigo 2º-IX, são valores mobiliários, quando ofertados publicamente, quaisquer títulos ou contratos de investimento coletivo que gerem direito de participação, de parceria ou remuneração, inclusive resultante da prestação de serviços, cujos rendimentos advém do esforço do...",
        "temas_relacionados": []
    },
    {
        "id": "var",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["VaR"],
        "termos_busca": ["var", "value", "risk", "valor", "risco", "medida", "estatística"],
        "descricao": "Value at Risk ou Valor em Risco, é uma medida estatística usada para o cálculo do valor máximo da perda esperada de um ativo ou portfólio em função da variação diária nos preços que o compõem.",
        "temas_relacionados": []
    },
    {
        "id": "venture_capital",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Venture Capital"],
        "termos_busca": ["capital", "venture", "modalidade", "investimento", "empresas", "geralmente", "médio", "porte"],
        "descricao": "Modalidade de investimento em empresas geralmente de médio porte com potencial de crescimento.",
        "temas_relacionados": []
    },
    {
        "id": "violinar",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Violinar"],
        "termos_busca": ["violinar", "jargão", "utilizado", "análise", "grafista", "cotações", "fazem"],
        "descricao": "Jargão utilizado na análise grafista quando as cotações fazem um movimento forte em um sentido e revertem esse movimento pouco depois.",
        "temas_relacionados": []
    },
    {
        "id": "virar_po",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Virar Po", "Virar Pó"],
        "termos_busca": ["virar", "jargão", "utilizado", "mercado", "opções", "data", "vencimento"],
        "descricao": "Jargão utilizado no mercado de opções, quando na data do vencimento esses ativos podem ser exercidos ou deixarão de existir.",
        "temas_relacionados": []
    },
    {
        "id": "vix",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["VIX"],
        "termos_busca": ["vix", "descubra", "famoso", "índice", "medo", "entenda", "funcionamento"],
        "descricao": "Descubra o que é VIX, famoso “Índice do Medo”. Entenda funcionamento, aplicações no mercado e como interpretar movimentos",
        "temas_relacionados": []
    },
    {
        "id": "volatilidade_historica",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Volatilidade historica", "Volatilidade histórica"],
        "termos_busca": ["histórica", "volatilidade", "calculada", "usando", "séries", "históricas", "determinado"],
        "descricao": "É a volatilidade calculada usando séries históricas de um determinado ativo.",
        "temas_relacionados": []
    },
    {
        "id": "volume_profile",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Volume Profile"],
        "termos_busca": ["profile", "volume", "descubra", "ferramenta", "ajuda", "traders", "identificar", "níveis"],
        "descricao": "Descubra como ferramenta ajuda traders a identificar níveis de suporte, resistência e volume negociado para decisões mais estratégicas",
        "temas_relacionados": []
    },
    {
        "id": "yield_to_call",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Yield to Call"],
        "termos_busca": ["call", "yield", "taxa", "interna", "opção", "data", "exercício", "compra"],
        "descricao": "Taxa Interna da Opção (YTC) até o data de exercício de uma opção de compra embutida um título de renda fixa que leva em consideração o total dos pagamentos periódicos de juros, o preço de compra, o valor de resgate...",
        "temas_relacionados": []
    },
    {
        "id": "yield_to_maturity",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Yield to Maturity"],
        "termos_busca": ["maturity", "yield", "taxa", "retorno", "vencimento", "título", "renda", "fixa"],
        "descricao": "Taxa de retorno até o vencimento de um título de renda fixa que leva em consideração o total dos pagamentos periódicos de juros, o preço de compra, o valor de resgate e o tempo restante até o prazo de vencimento.",
        "temas_relacionados": []
    },
    {
        "id": "zerar_posicao",
        "categoria": "GLOSSARIO_B3",
        "termos_usuario": ["Zerar posicao", "Zerar posição"],
        "termos_busca": ["posição", "zerar", "encerrar", "operações", "determinado", "ativo", "vendendo", "totalidade"],
        "descricao": "Encerrar todas as operações em um determinado ativo, vendendo a totalidade dos ativos comprados, ou recomprando todos os ativos previamente vendidos, de modo a eliminar a exposição do investidor a esse ativo.",
        "temas_relacionados": []
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
    
    _INITIALIZED = False


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
