"""
Cliente para a Z-API (WhatsApp API).
Permite enviar e receber mensagens via WhatsApp.
Documentação: https://developer.z-api.io/
"""
import httpx
import os
from typing import Optional, Dict, Any
from core.config import get_settings

settings = get_settings()


class ZAPIClient:
    """Cliente para interação com a Z-API."""
    
    def __init__(self):
        self.instance_id = settings.ZAPI_INSTANCE_ID or os.getenv("ZAPI_INSTANCE_ID", "")
        self.token = settings.ZAPI_TOKEN or os.getenv("ZAPI_TOKEN", "")
        self.client_token = settings.ZAPI_CLIENT_TOKEN or os.getenv("ZAPI_CLIENT_TOKEN", "")
        self.base_url = f"https://api.z-api.io/instances/{self.instance_id}/token/{self.token}"
    
    def _get_headers(self) -> dict:
        """Retorna headers de autenticação para a Z-API."""
        return {
            "Content-Type": "application/json",
            "Client-Token": self.client_token
        }
    
    def _normalize_phone(self, phone: str) -> str:
        """Normaliza o número de telefone para o formato Z-API (somente números)."""
        clean = ''.join(filter(str.isdigit, phone))
        if clean.endswith("@c.us"):
            clean = clean.replace("@c.us", "")
        return clean
    
    def _parse_response(self, response: httpx.Response, raw_data: dict) -> dict:
        """Processa a resposta da API e retorna formato padronizado."""
        if response.status_code >= 400:
            error_msg = raw_data.get("error", raw_data.get("message", f"HTTP {response.status_code}"))
            return {
                "success": False,
                "error": error_msg,
                "error_code": f"HTTP_{response.status_code}",
                "raw_response": raw_data,
                "status_code": response.status_code
            }
        
        if raw_data.get("error"):
            return {
                "success": False,
                "error": raw_data.get("error"),
                "error_code": raw_data.get("code", "API_ERROR"),
                "raw_response": raw_data
            }
        
        return {
            "success": True,
            "raw_response": raw_data,
            "zaap_id": raw_data.get("zaapId"),
            "message_id": raw_data.get("messageId", raw_data.get("id"))
        }
    
    async def send_text(self, to: str, message: str, delay_message: int = 0, delay_typing: int = 0) -> dict:
        """
        Envia uma mensagem de texto para um número de WhatsApp.
        
        Args:
            to: Número de telefone no formato internacional (ex: 5511999999999)
            message: Texto da mensagem a ser enviada
            delay_message: Delay entre mensagens em segundos (1-15)
            delay_typing: Tempo mostrando "Digitando..." em segundos (1-15)
            
        Returns:
            Resposta da API Z-API com campos padronizados:
            - success: bool
            - zaap_id: str (ID no Z-API)
            - message_id: str (ID no WhatsApp)
            - error: str (se houver erro)
        """
        url = f"{self.base_url}/send-text"
        
        payload = {
            "phone": self._normalize_phone(to),
            "message": message
        }
        
        if delay_message > 0:
            payload["delayMessage"] = min(max(delay_message, 1), 15)
        if delay_typing > 0:
            payload["delayTyping"] = min(max(delay_typing, 1), 15)
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=30.0)
                raw_data = response.json() if response.content else {}
                return self._parse_response(response, raw_data)
                
            except httpx.TimeoutException:
                return {
                    "success": False,
                    "error": "Timeout ao conectar com o servidor Z-API",
                    "error_code": "TIMEOUT"
                }
            except httpx.ConnectError as e:
                return {
                    "success": False,
                    "error": f"Não foi possível conectar ao servidor Z-API",
                    "error_code": "CONNECTION_ERROR",
                    "details": str(e)
                }
            except httpx.HTTPError as e:
                return {
                    "success": False,
                    "error": str(e),
                    "error_code": "HTTP_ERROR"
                }
    
    async def send_image(self, to: str, image_url: str, caption: str = "", view_once: bool = False) -> dict:
        """
        Envia uma imagem para um número de WhatsApp.
        
        Args:
            to: Número de telefone no formato internacional
            image_url: URL da imagem ou Base64
            caption: Legenda da imagem (opcional)
            view_once: Se é visualização única
        """
        url = f"{self.base_url}/send-image"
        
        payload = {
            "phone": self._normalize_phone(to),
            "image": image_url,
            "viewOnce": view_once
        }
        
        if caption:
            payload["caption"] = caption
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=60.0)
                raw_data = response.json() if response.content else {}
                return self._parse_response(response, raw_data)
            except Exception as e:
                return {"success": False, "error": str(e), "error_code": "EXCEPTION"}
    
    async def send_video(self, to: str, video_url: str, caption: str = "", view_once: bool = False) -> dict:
        """
        Envia um vídeo para um número de WhatsApp.
        
        Args:
            to: Número de telefone no formato internacional
            video_url: URL do vídeo ou Base64
            caption: Legenda do vídeo (opcional)
            view_once: Se é visualização única
        """
        url = f"{self.base_url}/send-video"
        
        payload = {
            "phone": self._normalize_phone(to),
            "video": video_url,
            "viewOnce": view_once
        }
        
        if caption:
            payload["caption"] = caption
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=120.0)
                raw_data = response.json() if response.content else {}
                return self._parse_response(response, raw_data)
            except Exception as e:
                return {"success": False, "error": str(e), "error_code": "EXCEPTION"}
    
    async def send_audio(self, to: str, audio_url: str, view_once: bool = False, waveform: bool = True) -> dict:
        """
        Envia um áudio para um número de WhatsApp.
        
        Args:
            to: Número de telefone no formato internacional
            audio_url: URL do áudio ou Base64
            view_once: Se é visualização única
            waveform: Se deve mostrar ondas sonoras
        """
        url = f"{self.base_url}/send-audio"
        
        payload = {
            "phone": self._normalize_phone(to),
            "audio": audio_url,
            "viewOnce": view_once,
            "waveform": waveform
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=60.0)
                raw_data = response.json() if response.content else {}
                return self._parse_response(response, raw_data)
            except Exception as e:
                return {"success": False, "error": str(e), "error_code": "EXCEPTION"}
    
    async def send_document(self, to: str, document_url: str, filename: str = "", caption: str = "") -> dict:
        """
        Envia um documento para um número de WhatsApp.
        
        Args:
            to: Número de telefone no formato internacional
            document_url: URL do documento ou Base64
            filename: Nome do arquivo
            caption: Descrição do documento (opcional)
        """
        extension = "pdf"
        if filename:
            parts = filename.rsplit('.', 1)
            if len(parts) > 1:
                extension = parts[1].lower()
        elif document_url and '.' in document_url:
            extension = document_url.rsplit('.', 1)[-1].lower().split('?')[0]
        
        url = f"{self.base_url}/send-document/{extension}"
        
        payload = {
            "phone": self._normalize_phone(to),
            "document": document_url
        }
        
        if filename:
            payload["fileName"] = filename
        if caption:
            payload["caption"] = caption
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=60.0)
                raw_data = response.json() if response.content else {}
                return self._parse_response(response, raw_data)
            except Exception as e:
                return {"success": False, "error": str(e), "error_code": "EXCEPTION"}
    
    async def send_file(self, to: str, file_url: str, file_type: str, caption: str = "", filename: str = "") -> dict:
        """
        Método de compatibilidade para enviar arquivos de diferentes tipos.
        
        Args:
            to: Número de telefone no formato internacional
            file_url: URL do arquivo a ser enviado
            file_type: Tipo do arquivo (image, document, video, audio)
            caption: Legenda do arquivo (opcional)
            filename: Nome do arquivo (para documentos)
        """
        if file_type == 'image':
            return await self.send_image(to, file_url, caption)
        elif file_type == 'video':
            return await self.send_video(to, file_url, caption)
        elif file_type == 'audio':
            return await self.send_audio(to, file_url)
        else:
            return await self.send_document(to, file_url, filename, caption)
    
    async def send_message(self, to: str, message: str) -> dict:
        """Alias para send_text para compatibilidade."""
        return await self.send_text(to, message)
    
    async def check_connection(self) -> dict:
        """Verifica a conexão com a Z-API."""
        url = f"{self.base_url}/status"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                data = response.json() if response.content else {}
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "connected": data.get("connected", False),
                        "status": data.get("status", "unknown"),
                        "phone": data.get("phone"),
                        "raw_response": data
                    }
                else:
                    return {
                        "success": False,
                        "error": data.get("error", f"HTTP {response.status_code}"),
                        "raw_response": data
                    }
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}
    
    async def get_qr_code(self) -> dict:
        """Obtém o QR code para conexão."""
        url = f"{self.base_url}/qr-code/image"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                if response.status_code == 200:
                    return {
                        "success": True,
                        "qr_code": response.content
                    }
                else:
                    data = response.json() if response.content else {}
                    return {
                        "success": False,
                        "error": data.get("error", f"HTTP {response.status_code}")
                    }
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}
    
    async def disconnect(self) -> dict:
        """Desconecta a instância do WhatsApp."""
        url = f"{self.base_url}/disconnect"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                data = response.json() if response.content else {}
                return {"success": response.status_code == 200, "raw_response": data}
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}
    
    async def restart(self) -> dict:
        """Reinicia a instância do WhatsApp."""
        url = f"{self.base_url}/restart"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                data = response.json() if response.content else {}
                return {"success": response.status_code == 200, "raw_response": data}
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}
    
    async def update_webhook(self, webhook_url: str) -> dict:
        """Atualiza a URL do webhook para receber mensagens."""
        url = f"{self.base_url}/update-webhook-received"
        
        payload = {"value": webhook_url}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, json=payload, headers=self._get_headers(), timeout=10.0)
                data = response.json() if response.content else {}
                return {"success": response.status_code == 200, "raw_response": data}
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}


zapi_client = ZAPIClient()


class WhatsAppClient(ZAPIClient):
    """Alias para compatibilidade com código legado."""
    pass


whatsapp_client = zapi_client
