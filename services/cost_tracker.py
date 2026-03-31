"""
Central de Custos - Serviço de rastreamento de custos de APIs.
Registra e calcula custos de todas as chamadas a APIs pagas.
"""
import os
from datetime import datetime
from typing import Optional
from database.database import SessionLocal

OPENAI_PRICING = {
    'gpt-4o': {'input': 2.50, 'output': 10.00},
    'gpt-4o-mini': {'input': 0.15, 'output': 0.60},
    'gpt-4-turbo': {'input': 10.00, 'output': 30.00},
    'text-embedding-3-large': {'input': 0.13, 'output': 0.0},
    'text-embedding-3-small': {'input': 0.02, 'output': 0.0},
    'whisper-1': {'per_minute': 0.006},
}

TAVILY_PRICING = {
    'search': 0.01,
}

DEFAULT_EXCHANGE_RATE = 5.80


class CostTracker:
    """Rastreador centralizado de custos de APIs."""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self.exchange_rate = DEFAULT_EXCHANGE_RATE
    
    def track_openai_chat(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        operation: str = 'chat_completion',
        context: Optional[str] = None,
        conversation_id: Optional[str] = None
    ):
        """Registra custo de uma chamada chat completion OpenAI."""
        pricing = OPENAI_PRICING.get(model, OPENAI_PRICING.get('gpt-4o-mini'))
        cost_usd = (prompt_tokens * pricing['input'] / 1_000_000) + (completion_tokens * pricing['output'] / 1_000_000)
        cost_brl = cost_usd * self.exchange_rate
        
        self._save_record(
            service='openai',
            operation=operation,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            cost_brl=cost_brl,
            context=context,
            conversation_id=conversation_id
        )
        
        return {'cost_usd': cost_usd, 'cost_brl': cost_brl}
    
    def track_openai_embedding(
        self,
        model: str,
        total_tokens: int,
        context: Optional[str] = None
    ):
        """Registra custo de uma chamada de embedding."""
        pricing = OPENAI_PRICING.get(model, OPENAI_PRICING.get('text-embedding-3-large'))
        cost_usd = total_tokens * pricing['input'] / 1_000_000
        cost_brl = cost_usd * self.exchange_rate
        
        self._save_record(
            service='openai',
            operation='embedding',
            model=model,
            prompt_tokens=total_tokens,
            completion_tokens=0,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            cost_brl=cost_brl,
            context=context
        )
        
        return {'cost_usd': cost_usd, 'cost_brl': cost_brl}
    
    def track_whisper(
        self,
        duration_seconds: float,
        context: Optional[str] = None,
        conversation_id: Optional[str] = None
    ):
        """Registra custo de uma transcrição Whisper."""
        duration_minutes = duration_seconds / 60.0
        cost_usd = duration_minutes * OPENAI_PRICING['whisper-1']['per_minute']
        cost_brl = cost_usd * self.exchange_rate
        
        self._save_record(
            service='openai',
            operation='transcription',
            model='whisper-1',
            audio_duration_seconds=duration_seconds,
            cost_usd=cost_usd,
            cost_brl=cost_brl,
            context=context,
            conversation_id=conversation_id
        )
        
        return {'cost_usd': cost_usd, 'cost_brl': cost_brl}
    
    def track_tavily_search(
        self,
        query: str,
        context: Optional[str] = None
    ):
        """Registra custo de uma busca Tavily."""
        cost_usd = TAVILY_PRICING['search']
        cost_brl = cost_usd * self.exchange_rate
        
        self._save_record(
            service='tavily',
            operation='web_search',
            model=None,
            cost_usd=cost_usd,
            cost_brl=cost_brl,
            context=context or f'query:{query[:100]}'
        )
        
        return {'cost_usd': cost_usd, 'cost_brl': cost_brl}
    
    def _save_record(self, **kwargs):
        """Salva registro de custo no banco."""
        try:
            from database.models import CostTracking
            db = SessionLocal()
            try:
                record = CostTracking(
                    service=kwargs.get('service'),
                    operation=kwargs.get('operation'),
                    model=kwargs.get('model'),
                    prompt_tokens=kwargs.get('prompt_tokens', 0),
                    completion_tokens=kwargs.get('completion_tokens', 0),
                    total_tokens=kwargs.get('total_tokens', 0),
                    audio_duration_seconds=kwargs.get('audio_duration_seconds'),
                    cost_usd=kwargs.get('cost_usd', 0),
                    cost_brl=kwargs.get('cost_brl', 0),
                    exchange_rate=self.exchange_rate,
                    context=kwargs.get('context'),
                    conversation_id=kwargs.get('conversation_id'),
                    created_at=datetime.utcnow()
                )
                db.add(record)
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"[CostTracker] Erro ao salvar registro: {e}")
            finally:
                db.close()
        except Exception as e:
            print(f"[CostTracker] Erro ao conectar ao banco: {e}")


cost_tracker = CostTracker.get_instance()
