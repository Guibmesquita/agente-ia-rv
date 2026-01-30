"""
Serviço de análise de insights das conversas.
Usa GPT para classificar categoria, produtos mencionados e extrair feedbacks.
"""
import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI
from core.config import get_settings

settings = get_settings()


class InsightAnalyzer:
    """Analisador de insights de conversas usando IA."""
    
    CATEGORIES = [
        "Dúvida sobre Produto",
        "Análise de Mercado",
        "Pedido de Material",
        "Suporte Operacional",
        "Estratégia de Investimento",
        "Informação de Taxas",
        "Rentabilidade e Performance",
        "Alocação de Carteira",
        "Dúvida Técnica",
        "Feedback ou Sugestão",
        "Saudação",
        "Outro"
    ]
    
    def __init__(self):
        self.client = None
        if settings.OPENAI_API_KEY:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    async def analyze_conversation(
        self,
        user_message: str,
        agent_response: str,
        escalated_to_human: bool = False
    ) -> Dict[str, Any]:
        """
        Analisa uma conversa e extrai insights.
        
        Returns:
            Dict com category, products_mentioned, tickers_mentioned, feedback_text, sentiment
        """
        if not self.client:
            return self._fallback_analysis(user_message, agent_response)
        
        try:
            prompt = f"""Analise esta interação entre um assessor financeiro e o agente de IA Stevan.

MENSAGEM DO ASSESSOR:
{user_message}

RESPOSTA DO AGENTE:
{agent_response}

Responda APENAS com um JSON válido no seguinte formato:
{{
    "category": "uma das categorias: {', '.join(self.CATEGORIES)}",
    "products_mentioned": ["lista de produtos financeiros mencionados"],
    "tickers_mentioned": ["lista de tickers/códigos de ativos mencionados, ex: PETR4, VALE3"],
    "has_feedback": true/false,
    "feedback_text": "texto do feedback se houver, ou null",
    "feedback_type": "elogio/sugestao/reclamacao ou null - classifique como: elogio (feedback positivo, agradecimento, satisfação), sugestao (pedido de melhoria, ideia, funcionalidade), reclamacao (crítica, insatisfação, problema)",
    "sentiment": "positivo/negativo/neutro"
}}

Seja preciso na extração de tickers e produtos. Considere como feedback qualquer sugestão, crítica, elogio ou reclamação.
IMPORTANTE para feedback_type: Analise o tom e conteúdo do feedback para classificar corretamente:
- "elogio": Expressões de satisfação, agradecimento, elogios ao serviço ou atendimento
- "sugestao": Pedidos de melhoria, sugestões de novas funcionalidades, ideias construtivas
- "reclamacao": Críticas, insatisfação, problemas relatados, frustrações"""

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é um analisador de dados de conversas. Responda sempre em JSON válido."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content.strip()
            
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                result_text = json_match.group()
            
            result = json.loads(result_text)
            
            return {
                "category": result.get("category", "Outro"),
                "products_mentioned": json.dumps(result.get("products_mentioned", []), ensure_ascii=False),
                "tickers_mentioned": json.dumps(result.get("tickers_mentioned", []), ensure_ascii=False),
                "has_feedback": result.get("has_feedback", False),
                "feedback_text": result.get("feedback_text"),
                "feedback_type": result.get("feedback_type"),
                "sentiment": result.get("sentiment", "neutro")
            }
            
        except Exception as e:
            print(f"[InsightAnalyzer] Erro na análise: {e}")
            return self._fallback_analysis(user_message, agent_response)
    
    def _fallback_analysis(self, user_message: str, agent_response: str) -> Dict[str, Any]:
        """Análise básica sem IA como fallback."""
        
        category = "Outro"
        message_lower = user_message.lower()
        
        if any(word in message_lower for word in ["olá", "oi", "bom dia", "boa tarde", "boa noite"]):
            category = "Saudação"
        elif any(word in message_lower for word in ["taxa", "custo", "preço"]):
            category = "Informação de Taxas"
        elif any(word in message_lower for word in ["rentabilidade", "rendimento", "performance"]):
            category = "Rentabilidade e Performance"
        elif any(word in message_lower for word in ["material", "documento", "pdf", "apresentação"]):
            category = "Pedido de Material"
        elif any(word in message_lower for word in ["produto", "fundo", "fii", "coe"]):
            category = "Dúvida sobre Produto"
        elif any(word in message_lower for word in ["mercado", "ibovespa", "dólar", "economia"]):
            category = "Análise de Mercado"
        elif any(word in message_lower for word in ["estratégia", "alocação", "carteira"]):
            category = "Estratégia de Investimento"
        
        tickers = re.findall(r'\b[A-Z]{4}[0-9]{1,2}\b', user_message.upper())
        
        products = []
        product_patterns = ["fii", "coe", "fundo", "ação", "ações", "etf", "cdb", "lci", "lca"]
        for pattern in product_patterns:
            if pattern in message_lower:
                products.append(pattern.upper())
        
        return {
            "category": category,
            "products_mentioned": json.dumps(products, ensure_ascii=False),
            "tickers_mentioned": json.dumps(tickers, ensure_ascii=False),
            "has_feedback": False,
            "feedback_text": None,
            "feedback_type": None,
            "sentiment": "neutro"
        }


insight_analyzer = InsightAnalyzer()


async def save_conversation_insight(
    db,
    conversation_id: str,
    user_message: str,
    agent_response: str,
    resolved_by_ai: bool = True,
    escalated_to_human: bool = False,
    ticket_id: Optional[int] = None,
    assessor_phone: Optional[str] = None,
    assessor_data: Optional[Dict[str, Any]] = None
):
    """
    Salva um insight de conversa no banco de dados.
    """
    from database.models import ConversationInsight, Assessor
    
    analysis = await insight_analyzer.analyze_conversation(
        user_message, 
        agent_response, 
        escalated_to_human
    )
    
    assessor = None
    if assessor_data:
        assessor = db.query(Assessor).filter(Assessor.id == assessor_data.get('id')).first()
    elif assessor_phone:
        assessor = db.query(Assessor).filter(
            (Assessor.telefone_whatsapp == assessor_phone) |
            (Assessor.lid == assessor_phone)
        ).first()
    
    insight = ConversationInsight(
        conversation_id=conversation_id,
        assessor_id=assessor.id if assessor else None,
        assessor_phone=assessor_phone,
        assessor_name=assessor.nome if assessor else None,
        user_message=user_message,
        agent_response=agent_response,
        category=analysis.get("category"),
        products_mentioned=analysis.get("products_mentioned"),
        tickers_mentioned=analysis.get("tickers_mentioned"),
        resolved_by_ai=resolved_by_ai,
        escalated_to_human=escalated_to_human,
        ticket_created=ticket_id is not None,
        ticket_id=ticket_id,
        feedback_text=analysis.get("feedback_text"),
        feedback_type=analysis.get("feedback_type"),
        sentiment=analysis.get("sentiment"),
        unidade=assessor.unidade if assessor else None,
        equipe=assessor.equipe if assessor else None,
        macro_area=assessor.macro_area if assessor else None,
        broker_responsavel=assessor.broker_responsavel if assessor else None
    )
    
    db.add(insight)
    db.commit()
    db.refresh(insight)
    
    return insight
