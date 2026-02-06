"""
Dataset completo das Estruturas de Derivativos XPI.
Organizado em 3 camadas: Conteúdo Geral > Abas > Estratégias > Estruturas

Fonte: https://www.xpi.com.br/investimentos/produtos-estruturados/
"""

GENERAL_CONTENT = {
    "title": "Produtos Estruturados XPI - Soluções em Derivativos",
    "sections": [
        {
            "title": "O que são Produtos Estruturados?",
            "content": (
                "Produtos Estruturados são estratégias de investimento que combinam dois ou mais "
                "instrumentos financeiros, como ações, opções, contratos futuros e swaps, para criar "
                "uma solução personalizada de investimento. Eles permitem ao investidor montar "
                "operações com diferentes perfis de risco e retorno, adequando-se a objetivos "
                "específicos como proteção de carteira, alavancagem controlada, geração de renda "
                "ou aproveitamento de cenários de mercado. As estruturas são montadas pela mesa de "
                "derivativos da XPI e podem ser customizadas para cada necessidade."
            )
        },
        {
            "title": "Para quem são indicados os Produtos Estruturados?",
            "content": (
                "Os Produtos Estruturados são indicados para investidores com perfil moderado a "
                "arrojado que buscam estratégias mais sofisticadas para otimizar seus investimentos. "
                "São especialmente úteis para: investidores que desejam proteção (hedge) para suas "
                "carteiras de ações; investidores que buscam alavancagem controlada com risco "
                "limitado; investidores que querem gerar renda adicional a partir de suas posições; "
                "investidores que desejam se posicionar em cenários específicos de mercado; "
                "e investidores que buscam troca de indexadores para otimizar suas exposições."
            )
        },
        {
            "title": "Quais são os riscos dos Produtos Estruturados?",
            "content": (
                "Os principais riscos dos Produtos Estruturados incluem: risco de mercado, onde "
                "movimentos adversos nos preços dos ativos podem gerar perdas; risco de liquidez, "
                "pois algumas estruturas podem ter dificuldade de desmontagem antes do vencimento; "
                "risco de contraparte, relacionado à capacidade de pagamento da outra parte; "
                "risco de modelo, onde o comportamento real pode divergir das projeções; e risco "
                "operacional, associado à execução e gestão das operações. É fundamental que o "
                "investidor compreenda completamente a estrutura antes de investir e conte com o "
                "suporte de seu assessor para avaliar a adequação ao seu perfil."
            )
        },
        {
            "title": "Quando investir em Produtos Estruturados?",
            "content": (
                "Produtos Estruturados são mais indicados em cenários onde o investidor tem uma "
                "visão definida sobre o comportamento do mercado. Por exemplo: quando se acredita "
                "na alta de um ativo mas deseja limitar o risco; quando se quer proteger uma "
                "carteira existente contra quedas; quando se identifica um cenário de baixa "
                "volatilidade e quer gerar renda; quando se deseja trocar a exposição entre "
                "indexadores (CDI, IPCA, pré-fixado); ou quando se quer participar de movimentos "
                "de mercado sem necessariamente comprar o ativo-objeto."
            )
        },
        {
            "title": "Exemplos de instrumentos utilizados em Produtos Estruturados",
            "content": (
                "Os instrumentos mais comuns em Produtos Estruturados incluem: Opções de compra "
                "(Calls) e de venda (Puts), que dão o direito de comprar ou vender um ativo a um "
                "preço predeterminado; Contratos Futuros, acordos para comprar ou vender um ativo "
                "em data futura; Swaps, contratos de troca de fluxos financeiros entre duas partes; "
                "Opções com Barreira (Knock-in e Knock-out), que são ativadas ou desativadas quando "
                "o preço atinge certos níveis; e Opções Exóticas, com características especiais como "
                "barreiras, lookback e asian. A combinação criativa destes instrumentos permite "
                "criar estratégias para praticamente qualquer cenário de mercado."
            )
        }
    ]
}

TABS = [
    {
        "name": "Alavancagem",
        "description": "Estratégias que permitem amplificar ganhos em movimentos de mercado, com risco controlado.",
        "strategies": [
            {
                "name": "Participação dobrada na alta do ativo",
                "description": "Estratégia para quem acredita na alta de um ativo e deseja dobrar a participação no movimento, aceitando um limitador de lucro.",
                "structures": [
                    {
                        "name": "Booster",
                        "slug": "booster",
                        "description": (
                            "O Booster é uma estrutura que possibilita ao investidor ter o dobro de "
                            "participação na alta de um ativo-objeto. Em contrapartida, há um limitador "
                            "de ganhos (cap). O custo da operação é zero. A estratégia é indicada para "
                            "investidores que acreditam em uma alta moderada do ativo e desejam "
                            "potencializar seus ganhos até determinado ponto. Se o ativo subir, o "
                            "investidor ganha o dobro até o cap; se cair, a perda é equivalente à queda "
                            "do ativo-objeto."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Booster.pdf"
                    }
                ]
            }
        ]
    },
    {
        "name": "Juros",
        "description": "Estratégias para troca de indexadores e gestão de exposição a taxas de juros.",
        "strategies": [
            {
                "name": "Troca de indexadores",
                "description": "Estratégia para investidores que desejam trocar a rentabilidade de um investimento entre diferentes indexadores (CDI, IPCA, pré-fixado), sem necessidade de resgatar a posição original.",
                "structures": [
                    {
                        "name": "Swap",
                        "slug": "swap",
                        "description": (
                            "O Swap é um contrato derivativo no qual duas partes concordam em trocar fluxos "
                            "financeiros futuros. No contexto de renda fixa, é utilizado para trocar a "
                            "rentabilidade de um indexador por outro. Por exemplo, um investidor com posição "
                            "atrelada ao CDI pode fazer um swap para trocar por uma taxa pré-fixada, caso "
                            "acredite que os juros irão cair. A operação não exige movimentação do investimento "
                            "original, apenas a troca dos fluxos financeiros na data de vencimento. É indicada "
                            "para investidores que desejam alterar sua exposição a indexadores sem precisar "
                            "resgatar ou vender suas posições."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Swap.pdf"
                    }
                ]
            }
        ]
    },
    {
        "name": "Proteção",
        "description": "Estratégias de hedge que protegem a carteira contra quedas, mantendo participação em altas.",
        "strategies": [
            {
                "name": "Participação na alta do ativo com proteção",
                "description": "Estratégia defensiva para investidores que possuem o ativo e querem se proteger contra quedas, mantendo participação limitada na alta.",
                "structures": [
                    {
                        "name": "Collar com ativo",
                        "slug": "collar-com-ativo",
                        "description": (
                            "O Collar é uma das estratégias mais clássicas de proteção. O investidor que possui "
                            "o ativo compra uma opção de venda (Put) para se proteger contra quedas e, para "
                            "financiar essa proteção, vende uma opção de compra (Call), limitando seus ganhos "
                            "na alta. A estrutura geralmente é montada a custo zero. O resultado é que o "
                            "investidor fica protegido contra quedas abaixo do strike da Put, mas tem seus "
                            "ganhos limitados ao strike da Call. É indicada para investidores conservadores "
                            "que possuem ações e desejam proteção contra cenários de queda."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Collar-com-ativo.pdf"
                    }
                ]
            },
            {
                "name": "Participação na alta com proteção parcial",
                "description": "Estratégia para investidores que desejam proteção parcial contra quedas, com maior participação na alta comparado ao Collar tradicional.",
                "structures": [
                    {
                        "name": "Fence com ativo",
                        "slug": "fence-com-ativo",
                        "description": (
                            "O Fence (ou cerca) é uma variação do Collar que oferece proteção parcial contra "
                            "quedas. O investidor compra uma Put com strike abaixo do preço atual (out of the "
                            "money), o que reduz o custo da proteção. A proteção só é ativada quando o ativo "
                            "cai abaixo do strike da Put, ficando o investidor exposto a uma faixa de queda. "
                            "Em contrapartida, o limite de ganho (Call vendida) pode ser mais alto que no "
                            "Collar tradicional. A estrutura é indicada para investidores que aceitam uma "
                            "exposição parcial à queda em troca de maior participação na alta."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Fence-com-ativo.pdf"
                    }
                ]
            },
            {
                "name": "Proteção com ganho mínimo",
                "description": "Estratégia que garante um ganho mínimo ao investidor, independente do cenário de mercado, combinando proteção com rentabilidade garantida.",
                "structures": [
                    {
                        "name": "Step-up",
                        "slug": "step-up",
                        "description": (
                            "O Step-up é uma estrutura que garante ao investidor um ganho mínimo "
                            "predeterminado, independentemente do cenário de mercado. Funciona como uma "
                            "proteção com piso de rentabilidade. Se o ativo subir, o investidor participa "
                            "da alta até um limite (cap). Se o ativo cair, o investidor recebe o ganho "
                            "mínimo garantido. A estrutura é ideal para investidores que querem manter "
                            "exposição ao mercado de ações com a segurança de um retorno mínimo garantido."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Step-up.pdf"
                    }
                ]
            }
        ]
    },
    {
        "name": "Volatilidade",
        "description": "Estratégias que se beneficiam de cenários de alta ou baixa volatilidade do mercado.",
        "strategies": [
            {
                "name": "Ganho com ativos lateralizados",
                "description": "Estratégias para cenários de baixa volatilidade, onde o investidor acredita que o ativo ficará lateralizado (sem grandes movimentos de alta ou queda).",
                "structures": [
                    {
                        "name": "Compra de Condor e Venda de Strangle com hedge",
                        "slug": "condor-strangle-com-hedge",
                        "description": (
                            "Combinação de uma compra de Condor com venda de Strangle hedgeada. O investidor "
                            "lucra se o ativo se mantiver dentro de um intervalo de preços predefinido. A "
                            "estrutura tem risco limitado graças ao hedge do Strangle vendido. É indicada "
                            "para cenários de baixa volatilidade onde o investidor acredita que o ativo "
                            "permanecerá lateralizado. O ganho máximo ocorre quando o ativo termina dentro "
                            "do intervalo central no vencimento."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Compra-de-condor-e-venda-de-strangle-com-hedge.pdf"
                    },
                    {
                        "name": "Compra de Condor com Venda de Strangle",
                        "slug": "condor-venda-strangle",
                        "description": (
                            "Combinação de compra de Condor com venda de Strangle sem hedge adicional. Similar "
                            "à versão com hedge, mas com maior potencial de ganho e maior risco. O investidor "
                            "lucra quando o ativo permanece dentro de uma faixa de preço esperada. O risco é "
                            "ilimitado caso o ativo se mova fortemente para cima ou para baixo. É indicada "
                            "para investidores mais arrojados com forte convicção de lateralização."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Compra-de-condor-e-venda-de-strangle.pdf"
                    },
                    {
                        "name": "Venda de Straddle",
                        "slug": "venda-straddle",
                        "description": (
                            "A Venda de Straddle consiste na venda simultânea de uma Call e uma Put com o "
                            "mesmo strike (geralmente no dinheiro - ATM). O investidor recebe o prêmio das "
                            "duas opções e lucra se o ativo permanecer próximo ao strike no vencimento. O "
                            "risco é ilimitado em ambas as direções. É uma estratégia agressiva de venda de "
                            "volatilidade, indicada quando o investidor acredita fortemente que o ativo "
                            "não terá grandes movimentos. O ganho máximo é o prêmio total recebido."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Venda-de-straddle.pdf"
                    }
                ]
            },
            {
                "name": "Ganho com ativo dentro de um intervalo de preço",
                "description": "Estratégias para investidores que acreditam que o ativo terminará dentro de uma faixa de preço específica no vencimento.",
                "structures": [
                    {
                        "name": "Compra de Condor",
                        "slug": "compra-condor",
                        "description": (
                            "O Condor é uma estrutura que combina quatro opções com diferentes strikes para "
                            "criar uma zona de ganho. O investidor lucra se o ativo terminar dentro de um "
                            "intervalo de preço predefinido no vencimento. O risco é limitado ao custo da "
                            "estrutura. É indicada para investidores que acreditam que o ativo permanecerá "
                            "dentro de uma faixa, com risco e retorno limitados. É menos agressiva que a "
                            "venda de volatilidade pura."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Compra-de-condor.pdf"
                    },
                    {
                        "name": "Compra de Borboleta (FLY)",
                        "slug": "compra-borboleta-fly",
                        "description": (
                            "A Borboleta (ou FLY - Butterfly) é uma estrutura que combina três strikes "
                            "diferentes. O investidor lucra quando o ativo termina exatamente no strike "
                            "central no vencimento. O risco é limitado ao custo da estrutura. É indicada "
                            "para investidores que têm uma visão precisa sobre o preço-alvo do ativo no "
                            "vencimento. Quanto mais próximo do strike central, maior o ganho. É uma "
                            "aposta direcional precisa com risco limitado."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Compra-de-borboleta-fly.pdf"
                    }
                ]
            },
            {
                "name": "Participação na variação de preço do ativo",
                "description": "Estratégias para investidores que acreditam em movimentos intensos do ativo (alta ou queda), sem necessariamente saber a direção.",
                "structures": [
                    {
                        "name": "Compra de Straddle",
                        "slug": "compra-straddle",
                        "description": (
                            "A Compra de Straddle consiste na compra simultânea de uma Call e uma Put com "
                            "o mesmo strike (geralmente ATM). O investidor lucra se o ativo se mover "
                            "significativamente em qualquer direção. O custo é o prêmio pago pelas duas "
                            "opções. É indicada para cenários de alta volatilidade esperada, como antes de "
                            "resultados corporativos, decisões de juros ou eventos macroeconômicos. O "
                            "investidor não precisa acertar a direção, apenas a intensidade do movimento."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Compra-de-straddle.pdf"
                    },
                    {
                        "name": "Compra de Strangle",
                        "slug": "compra-strangle",
                        "description": (
                            "A Compra de Strangle é similar ao Straddle, mas usa strikes diferentes (fora "
                            "do dinheiro - OTM) para a Call e a Put. Isso torna a estrutura mais barata que "
                            "o Straddle, mas exige um movimento maior do ativo para gerar lucro. O risco é "
                            "limitado ao prêmio pago. É indicada quando o investidor espera um movimento "
                            "forte mas quer pagar menos pelo posicionamento. O breakeven é mais distante "
                            "do preço atual que no Straddle."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Compra-de-strangle.pdf"
                    },
                    {
                        "name": "Compra e Venda de Opções (Calls e Puts)",
                        "slug": "compra-venda-opcoes",
                        "description": (
                            "A compra e venda de opções (Calls e Puts) são os blocos fundamentais de todas "
                            "as estratégias de derivativos. Uma Call dá o direito de comprar o ativo a um "
                            "preço predefinido, enquanto uma Put dá o direito de vender. Comprar uma Call "
                            "gera ganhos na alta; comprar uma Put gera ganhos na queda. Vender opções gera "
                            "receita de prêmio mas expõe a riscos. O investidor pode usar essas operações "
                            "básicas de forma isolada ou combinada para montar estratégias mais complexas."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Compra-e-venda-de-opcoes.pdf"
                    }
                ]
            }
        ]
    },
    {
        "name": "Direcionais",
        "description": "Estratégias para investidores com visão direcional definida sobre o ativo, seja de alta ou de queda.",
        "strategies": [
            {
                "name": "Participação na alta do ativo",
                "description": "Estratégias para investidores que acreditam na valorização do ativo e desejam participar da alta sem necessariamente comprar o ativo-objeto.",
                "structures": [
                    {
                        "name": "Risk Reversal",
                        "slug": "risk-reversal",
                        "description": (
                            "O Risk Reversal (Reversão de Risco) é uma estrutura que combina a compra de uma "
                            "Call com a venda de uma Put. O investidor participa da alta do ativo acima do "
                            "strike da Call e assume o risco de queda abaixo do strike da Put. Geralmente "
                            "montada a custo zero (os prêmios se cancelam). É equivalente a ter uma posição "
                            "comprada sintética no ativo, com exposição tanto na alta quanto na queda. "
                            "Indicada para investidores com forte convicção de alta que aceitam o risco "
                            "direcional de queda."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Risk-Reversal.pdf"
                    },
                    {
                        "name": "Compra de Call Spread",
                        "slug": "compra-call-spread",
                        "description": (
                            "A Compra de Call Spread (ou Trava de Alta) consiste na compra de uma Call com "
                            "strike mais baixo e venda de uma Call com strike mais alto. O custo é menor do "
                            "que comprar apenas a Call, pois a venda da Call com strike mais alto financia "
                            "parte da operação. O ganho é limitado à diferença entre os strikes menos o custo, "
                            "e a perda é limitada ao prêmio pago. É indicada quando o investidor acredita em "
                            "uma alta moderada e quer pagar menos pela operação."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Call-Spread.pdf"
                    },
                    {
                        "name": "Seagull",
                        "slug": "seagull",
                        "description": (
                            "A Seagull (Gaivota) é uma estrutura que combina um Call Spread (compra de Call + "
                            "venda de Call com strike mais alto) com a venda de uma Put. A venda da Put "
                            "financia o Call Spread, tornando a operação de custo zero ou muito baixo. O "
                            "investidor participa da alta do ativo entre os dois strikes da Call e assume o "
                            "risco de queda abaixo do strike da Put vendida. É indicada para investidores "
                            "que acreditam na alta do ativo e estão dispostos a aceitar risco na queda "
                            "em troca de custo zero."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Seagull.pdf"
                    }
                ]
            },
            {
                "name": "Participação na queda do ativo",
                "description": "Estratégias para investidores que acreditam na desvalorização do ativo ou desejam se posicionar defensivamente.",
                "structures": [
                    {
                        "name": "Collar sem ativo",
                        "slug": "collar-sem-ativo",
                        "description": (
                            "O Collar sem ativo é uma estratégia de baixa que combina a compra de uma Put "
                            "(para lucrar com a queda) com a venda de uma Call (para financiar a Put). Diferente "
                            "do Collar com ativo, aqui o investidor NÃO possui o ativo-objeto. O investidor "
                            "lucra se o ativo cair abaixo do strike da Put e tem risco limitado se o ativo "
                            "subir acima do strike da Call. É indicada para investidores que acreditam na "
                            "queda de um ativo e desejam montar a posição a custo zero ou muito baixo."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Collar-sem-ativo.pdf"
                    },
                    {
                        "name": "Compra de Put Spread",
                        "slug": "compra-put-spread",
                        "description": (
                            "A Compra de Put Spread (ou Trava de Baixa com Puts) consiste na compra de uma Put "
                            "com strike mais alto e venda de uma Put com strike mais baixo. O custo é menor que "
                            "comprar apenas a Put, pois a venda financia parte da operação. O ganho é limitado "
                            "à diferença entre os strikes menos o custo. É indicada quando o investidor acredita "
                            "em uma queda moderada do ativo e quer limitar o custo da operação. Também pode ser "
                            "usada como hedge parcial de uma carteira de ações."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Put-Spread.pdf"
                    },
                    {
                        "name": "Fence sem ativo",
                        "slug": "fence-sem-ativo",
                        "description": (
                            "O Fence sem ativo é uma variação da estratégia de cerca para investidores que "
                            "NÃO possuem o ativo-objeto e querem se posicionar para uma queda. Combina a "
                            "compra de uma Put (proteção/aposta na queda) com a venda de uma Call (para "
                            "financiar). O investidor lucra com a queda e tem risco na alta. É uma alternativa "
                            "ao Collar sem ativo, geralmente com strikes mais fora do dinheiro."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Fence-sem-ativo.pdf"
                    }
                ]
            }
        ]
    },
    {
        "name": "Exóticas",
        "description": "Estratégias com opções exóticas (barreiras), que são mais baratas que opções tradicionais por terem condições de ativação ou desativação.",
        "strategies": [
            {
                "name": "Participação na alta do ativo",
                "description": "Estratégia para participar na alta usando opções com barreira de knock-in, mais baratas que opções tradicionais.",
                "structures": [
                    {
                        "name": "Compra de Call Up and In",
                        "slug": "call-up-and-in",
                        "description": (
                            "A compra de uma opção de compra (Call) tem o objetivo de gerar ganhos em caso de "
                            "alta de um determinado ativo. A Call Up and In também possibilita ganhos na alta, "
                            "porém apenas se o preço de Knock-in for atingido. Essa característica faz da "
                            "Call Up and In mais barata do que uma Call tradicional. O investidor paga menos "
                            "pela opção, mas precisa que o ativo suba até o nível da barreira para que a "
                            "opção se torne ativa. Indicada para quem espera uma alta expressiva."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Call-Up-and-In.pdf"
                    }
                ]
            },
            {
                "name": "Participação na alta moderada do ativo",
                "description": "Estratégia para participar de uma alta moderada usando opções com barreira de knock-out, mais baratas que opções tradicionais.",
                "structures": [
                    {
                        "name": "Compra de Call Up and Out",
                        "slug": "call-up-and-out",
                        "description": (
                            "A compra de uma opção de compra (Call) tem o objetivo de gerar ganhos em caso de "
                            "alta de um determinado ativo. A Call Up and Out também possibilita ganhos na alta, "
                            "porém, apenas até o preço de Knock-out. Essa característica faz da Call Up and Out "
                            "mais barata do que uma Call tradicional. Se o ativo atingir o nível de Knock-out, "
                            "a opção é desativada e o investidor perde o direito ao ganho. Indicada para quem "
                            "espera uma alta moderada e controlada."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Call-Up-and-Out.pdf"
                    }
                ]
            },
            {
                "name": "Participação na queda do ativo",
                "description": "Estratégia para participar na queda usando opções exóticas com barreira de knock-in.",
                "structures": [
                    {
                        "name": "Compra de Put Down and In",
                        "slug": "put-down-and-in",
                        "description": (
                            "A compra de uma opção de venda (Put) tem o objetivo de gerar ganhos em caso de "
                            "queda de um determinado ativo. A Put Down and In também possibilita ganhos na "
                            "queda, porém apenas se o preço de Knock-in for atingido. Essa característica faz "
                            "da Put Down and In mais barata do que uma Put tradicional. O investidor paga "
                            "menos, mas precisa que o ativo caia até o nível da barreira para ativar a opção. "
                            "Indicada para quem espera uma queda significativa."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Put-Down-and-In.pdf"
                    }
                ]
            },
            {
                "name": "Participação na queda moderada do ativo",
                "description": "Estratégia para participar de uma queda moderada usando opções com barreira de knock-out.",
                "structures": [
                    {
                        "name": "Compra de Put Down and Out",
                        "slug": "put-down-and-out",
                        "description": (
                            "A compra de uma opção de venda (Put) tem o objetivo de gerar ganhos em caso de "
                            "queda de um determinado ativo. A Put Down and Out também possibilita ganhos na "
                            "queda, porém, desde que o preço de Knock-out não tenha sido atingido. Essa "
                            "característica faz da Put Down and Out mais barata do que uma Put tradicional. "
                            "Se o ativo cair além do nível de Knock-out, a opção é desativada. Indicada "
                            "para quem espera uma queda moderada e controlada."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Put-Down-and-Out.pdf"
                    }
                ]
            }
        ]
    },
    {
        "name": "Hedge Cambial",
        "description": "Estratégias para proteção contra variações cambiais, especialmente para empresas e investidores com exposição ao dólar.",
        "strategies": [
            {
                "name": "Termo de Moeda",
                "description": "Instrumento para fixar antecipadamente uma taxa de câmbio em data futura, protegendo contra variações cambiais.",
                "structures": [
                    {
                        "name": "NDF",
                        "slug": "ndf",
                        "description": (
                            "NDF (Non-Deliverable Forward) é um contrato a termo de moedas, negociado em "
                            "mercado de balcão, cujo objetivo é fixar, antecipadamente, uma taxa de câmbio "
                            "em uma data futura. No vencimento, a liquidação ocorre pela diferença entre a "
                            "taxa a termo contratada e a taxa de mercado definida como referência. Não há "
                            "entrega física da moeda, apenas o ajuste financeiro. É indicada para empresas "
                            "com receitas ou despesas em moeda estrangeira que desejam eliminar o risco "
                            "cambial, ou para investidores que querem se posicionar em variações cambiais."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/NDF.pdf"
                    }
                ]
            }
        ]
    },
    {
        "name": "Remuneração de Carteira",
        "description": "Estratégias para gerar renda adicional a partir de uma carteira existente de ações.",
        "strategies": [
            {
                "name": "Remuneração de carteira de Ações",
                "description": "Estratégia clássica de venda coberta para otimizar a rentabilidade de uma carteira de ações existente.",
                "structures": [
                    {
                        "name": "Financiamento",
                        "slug": "financiamento",
                        "description": (
                            "O Financiamento é uma das estratégias mais tradicionais do mercado de renda "
                            "variável. Ela consiste na venda coberta de uma opção de compra (Call), com a "
                            "finalidade de otimização da carteira, proteção parcial contra quedas e operações "
                            "de taxa. O investidor que possui ações vende Calls sobre elas, recebendo um prêmio. "
                            "Se o ativo não subir acima do strike, o investidor mantém as ações e embolsa o prêmio. "
                            "Se subir acima do strike, vende as ações pelo preço fixado. É a forma mais "
                            "conservadora de gerar renda com derivativos."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Financiamento.pdf"
                    }
                ]
            },
            {
                "name": "Ganho com ativos com viés de alta",
                "description": "Estratégia para gerar receita quando se acredita que o ativo tem viés de alta ou pouca probabilidade de queda.",
                "structures": [
                    {
                        "name": "Venda de Put Spread",
                        "slug": "venda-put-spread",
                        "description": (
                            "A venda de Put Spread, também chamada de Trava de Alta, é uma estratégia utilizada "
                            "para se beneficiar de um cenário de alta de um ativo, ou de pouca probabilidade de "
                            "queda. Nessa estrutura, o investidor recebe um prêmio na entrada da operação na "
                            "expectativa de que o ativo objeto se valorize, havendo perdas limitadas caso o ativo "
                            "esteja abaixo de um determinado ponto. É indicada para investidores que desejam gerar "
                            "receita de prêmio com viés otimista sobre o ativo."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Venda-de-Put-Spread.pdf"
                    }
                ]
            },
            {
                "name": "Ganho com ativos com viés de baixa",
                "description": "Estratégia para gerar receita quando se acredita que o ativo tem viés de baixa ou deseja proteger posição comprada.",
                "structures": [
                    {
                        "name": "Venda de Call Spread",
                        "slug": "venda-call-spread",
                        "description": (
                            "A venda de Call Spread, também chamada de Trava de Baixa, é uma estratégia utilizada "
                            "para se beneficiar de um cenário de queda, ou para proteger uma posição comprada no "
                            "ativo objeto. Nessa estrutura, recebe-se um prêmio na entrada da operação, havendo "
                            "perdas no vencimento caso o ativo objeto se encontre acima de determinado preço. "
                            "O risco é limitado à diferença entre os strikes. É indicada para investidores "
                            "com viés neutro ou baixista que querem gerar receita com a operação."
                        ),
                        "pdf_url": "https://conteudos.xpi.com.br/wp-content/uploads/2021/03/Venda-de-Call-Spread.pdf"
                    }
                ]
            }
        ]
    }
]


def get_all_structures():
    """Retorna lista plana de todas as estruturas com seus metadados."""
    structures = []
    for tab in TABS:
        for strategy in tab["strategies"]:
            for structure in strategy["structures"]:
                structures.append({
                    "tab": tab["name"],
                    "tab_description": tab["description"],
                    "strategy": strategy["name"],
                    "strategy_description": strategy["description"],
                    "name": structure["name"],
                    "slug": structure["slug"],
                    "description": structure["description"],
                    "pdf_url": structure["pdf_url"]
                })
    return structures


def get_all_pdf_urls():
    """Retorna dict de slug -> pdf_url para download."""
    return {s["slug"]: s["pdf_url"] for s in get_all_structures()}


if __name__ == "__main__":
    structures = get_all_structures()
    print(f"Total de estruturas: {len(structures)}")
    print(f"\nAgrupamento por aba:")
    from collections import Counter
    tab_counts = Counter(s["tab"] for s in structures)
    for tab, count in tab_counts.items():
        print(f"  {tab}: {count} estruturas")
    print(f"\nEstruturas:")
    for s in structures:
        print(f"  [{s['tab']}] {s['strategy']} > {s['name']}")
