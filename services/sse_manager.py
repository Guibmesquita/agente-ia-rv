"""
Gerenciador de Server-Sent Events para notificações em tempo real.
"""
import asyncio
import json
from typing import Dict, Set
from datetime import datetime


class SSEManager:
    """Gerencia conexões SSE para notificações em tempo real."""
    
    def __init__(self):
        self.connections: Dict[str, Set[asyncio.Queue]] = {}
    
    async def subscribe(self, channel: str) -> asyncio.Queue:
        """Inscreve um cliente em um canal."""
        if channel not in self.connections:
            self.connections[channel] = set()
        
        queue = asyncio.Queue()
        self.connections[channel].add(queue)
        print(f"[SSE] Cliente inscrito no canal '{channel}'. Total: {len(self.connections[channel])}")
        return queue
    
    def unsubscribe(self, channel: str, queue: asyncio.Queue):
        """Remove inscrição de um cliente."""
        if channel in self.connections:
            self.connections[channel].discard(queue)
            print(f"[SSE] Cliente removido do canal '{channel}'. Restantes: {len(self.connections[channel])}")
            if not self.connections[channel]:
                del self.connections[channel]
    
    async def broadcast(self, channel: str, event_type: str, data: dict):
        """Envia mensagem para todos os clientes de um canal."""
        if channel not in self.connections:
            return
        
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        disconnected = set()
        for queue in self.connections[channel]:
            try:
                await queue.put(message)
            except Exception as e:
                print(f"[SSE] Erro ao enviar para cliente: {e}")
                disconnected.add(queue)
        
        for queue in disconnected:
            self.connections[channel].discard(queue)
        
        print(f"[SSE] Broadcast '{event_type}' para {len(self.connections[channel])} clientes no canal '{channel}'")
    
    async def notify_new_message(self, conversation_id: int, message_data: dict):
        """Notifica sobre nova mensagem em uma conversa."""
        await self.broadcast("conversations", "new_message", {
            "conversation_id": conversation_id,
            "message": message_data
        })
    
    async def notify_conversation_update(self, conversation_id: int):
        """Notifica sobre atualização em uma conversa."""
        await self.broadcast("conversations", "conversation_updated", {
            "conversation_id": conversation_id
        })


sse_manager = SSEManager()


def get_sse_manager() -> SSEManager:
    return sse_manager
