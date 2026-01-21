"""
Agente de IA usando a API da OpenAI.
Gera respostas contextualizadas para perguntas dos usuários.
Carrega configurações do banco de dados em tempo real.
"""
from openai import OpenAI
from typing import List, Optional, Tuple
from core.config import get_settings
from services.vector_store import get_vector_store

settings = get_settings()


class OpenAIAgent:
    """Agente de IA para gerar respostas usando GPT."""
    
    def __init__(self):
        self.client = None
        if settings.OPENAI_API_KEY:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    def _get_config_from_db(self):
        """Carrega configuração do agente do banco de dados."""
        from database.database import SessionLocal
        from database.crud import get_agent_config
        
        db = SessionLocal()
        try:
            config = get_agent_config(db)
            if config:
                return {
                    "personality": config.personality,
                    "restrictions": config.restrictions or "",
                    "model": config.model,
                    "temperature": float(config.temperature),
                    "max_tokens": config.max_tokens
                }
        finally:
            db.close()
        
        return None
    
    def _build_system_prompt(self, config: dict = None) -> str:
        """Constrói o prompt do sistema baseado na configuração."""
        if config and config.get("personality"):
            prompt = config["personality"]
            if config.get("restrictions"):
                prompt += f"\n\nRESTRIÇÕES E PROIBIÇÕES:\n{config['restrictions']}"
            return prompt
        
        return """Você é um assistente virtual especializado em assessoria financeira.
Seu papel é ajudar clientes com dúvidas sobre investimentos, produtos financeiros e serviços.

REGRAS IMPORTANTES:
1. Responda sempre de forma educada e profissional.
2. Use o contexto fornecido para basear suas respostas.
3. Se a informação não estiver disponível no contexto, seja honesto e diga que não tem essa informação.
4. Quando não puder ajudar adequadamente, pergunte se o cliente deseja abrir um chamado para falar com um assessor.
5. Mantenha as respostas concisas e objetivas, adequadas para WhatsApp.
6. Nunca invente informações sobre produtos, taxas ou valores.

Para abrir um chamado, o usuário deve responder "SIM" ou "sim" quando perguntado."""
    
    def _build_context(self, documents: List[dict]) -> str:
        """Constrói o contexto a partir dos documentos encontrados."""
        if not documents:
            return "Nenhum contexto relevante encontrado na base de conhecimento."
        
        context_parts = []
        for i, doc in enumerate(documents, 1):
            title = doc.get('metadata', {}).get('title', f'Documento {i}')
            content = doc.get('content', '')
            context_parts.append(f"[{title}]\n{content}")
        
        return "\n\n---\n\n".join(context_parts)
    
    async def generate_response(
        self,
        user_message: str,
        conversation_history: Optional[List[dict]] = None,
        extra_context: Optional[str] = None
    ) -> Tuple[str, bool, dict]:
        """
        Gera uma resposta para a mensagem do usuário.
        
        Args:
            user_message: Mensagem do usuário
            conversation_history: Histórico da conversa (opcional)
            
        Returns:
            Tuple contendo:
            - response: Resposta gerada
            - should_create_ticket: Se deve criar um chamado
            - context_documents: Documentos usados como contexto
        """
        if not self.client:
            return (
                "Desculpe, o serviço de IA não está configurado no momento. "
                "Deseja abrir um chamado para falar com um assessor?",
                False,
                {"intent": "error"}
            )
        
        if user_message.lower().strip() in ['sim', 'yes', 's', 'quero', 'pode ser']:
            return (
                "Perfeito! Estou abrindo um chamado para você. "
                "Um de nossos assessores entrará em contato em breve. "
                "Obrigado pela paciência!",
                True,
                {"intent": "create_ticket"}
            )
        
        config = self._get_config_from_db()
        system_prompt = self._build_system_prompt(config)
        model = config.get("model", "gpt-4o") if config else "gpt-4o"
        temperature = config.get("temperature", 0.7) if config else 0.7
        max_tokens = config.get("max_tokens", 500) if config else 500
        
        vs = get_vector_store()
        context_documents = vs.search(user_message, n_results=3) if vs else []
        context = self._build_context(context_documents)
        
        if extra_context:
            context += f"\n\n{extra_context}"
        
        messages = [{"role": "system", "content": system_prompt}]
        
        if conversation_history:
            messages.extend(conversation_history[-6:])
        
        messages.append({
            "role": "user",
            "content": f"""CONTEXTO DA BASE DE CONHECIMENTO:
{context}

---

PERGUNTA DO CLIENTE:
{user_message}

Responda de forma clara e objetiva. Se não encontrar a informação no contexto, 
pergunte se o cliente deseja abrir um chamado."""
        })
        
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            ai_response = response.choices[0].message.content
            
            suggest_ticket = any(phrase in ai_response.lower() for phrase in [
                "abrir um chamado",
                "falar com um assessor",
                "deseja abrir",
                "quer abrir"
            ])
            
            return ai_response, False, {"intent": "question", "documents": context_documents}
            
        except Exception as e:
            print(f"[OpenAI] Erro ao gerar resposta: {e}")
            return (
                "Desculpe, ocorreu um erro ao processar sua mensagem. "
                "Deseja abrir um chamado para falar com um assessor?",
                False,
                {"intent": "error", "error": str(e)}
            )
    
    def is_available(self) -> bool:
        """Verifica se o agente está configurado e disponível."""
        return self.client is not None


openai_agent = OpenAIAgent()
