"""
Cliente para a API WAHA (WhatsApp HTTP API).
Permite enviar e receber mensagens via WhatsApp.
"""
import httpx
from typing import Optional
from core.config import get_settings

settings = get_settings()


class WhatsAppClient:
    """Cliente para interação com a API WAHA."""
    
    def __init__(self):
        self.base_url = settings.WAHA_API_URL.rstrip('/')
        self.api_key = settings.WAHA_API_KEY
        self.session = settings.WAHA_SESSION
    
    def _get_headers(self) -> dict:
        """Retorna headers de autenticação para a API WAHA."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers
    
    async def send_message(self, to: str, message: str) -> dict:
        """
        Envia uma mensagem de texto para um número de WhatsApp.
        
        Args:
            to: Número de telefone no formato internacional (ex: 5511999999999@c.us)
            message: Texto da mensagem a ser enviada
            
        Returns:
            Resposta da API WAHA
        """
        url = f"{self.base_url}/api/sendText"
        payload = {
            "chatId": to if "@c.us" in to else f"{to}@c.us",
            "text": message,
            "session": self.session
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=30.0)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                return {"error": str(e), "success": False}
    
    async def send_seen(self, chat_id: str) -> dict:
        """Marca uma mensagem como lida."""
        url = f"{self.base_url}/api/sendSeen"
        payload = {
            "chatId": chat_id,
            "session": self.session
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=30.0)
                return response.json()
            except httpx.HTTPError as e:
                return {"error": str(e)}
    
    async def start_typing(self, chat_id: str) -> dict:
        """Inicia indicador de digitação."""
        url = f"{self.base_url}/api/startTyping"
        payload = {
            "chatId": chat_id,
            "session": self.session
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=30.0)
                return response.json()
            except httpx.HTTPError as e:
                return {"error": str(e)}
    
    async def stop_typing(self, chat_id: str) -> dict:
        """Para indicador de digitação."""
        url = f"{self.base_url}/api/stopTyping"
        payload = {
            "chatId": chat_id,
            "session": self.session
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=30.0)
                return response.json()
            except httpx.HTTPError as e:
                return {"error": str(e)}
    
    async def check_connection(self) -> dict:
        """Verifica a conexão com a API WAHA."""
        url = f"{self.base_url}/api/sessions"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                response.raise_for_status()
                return {"success": True, "sessions": response.json()}
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}


# Instância global do cliente
whatsapp_client = WhatsAppClient()
