"""
Cliente para a Z-API (WhatsApp API).
Permite enviar e receber mensagens via WhatsApp.
Documentação: https://developer.z-api.io/
"""
import asyncio
import httpx
import os
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class ZAPIClient:
    """Cliente para interação com a Z-API."""
    
    def __init__(self):
        self.instance_id = os.getenv("ZAPI_INSTANCE_ID", "") or settings.ZAPI_INSTANCE_ID
        self.token = os.getenv("ZAPI_TOKEN", "") or settings.ZAPI_TOKEN
        self.client_token = os.getenv("ZAPI_CLIENT_TOKEN", "") or settings.ZAPI_CLIENT_TOKEN
        
        print(f"[Z-API] Inicializado - Instance: {self.instance_id[:8] if self.instance_id else '?'}..., Token configurado: {bool(self.token)}, Client-Token configurado: {bool(self.client_token)}")

    def _get_credentials(self) -> dict:
        """Lê credenciais no momento da chamada para refletir atualizações via save-secrets."""
        return {
            "instance_id": os.getenv("ZAPI_INSTANCE_ID", "") or settings.ZAPI_INSTANCE_ID,
            "token": os.getenv("ZAPI_TOKEN", "") or settings.ZAPI_TOKEN,
            "client_token": os.getenv("ZAPI_CLIENT_TOKEN", "") or settings.ZAPI_CLIENT_TOKEN,
        }

    def _get_base_url(self) -> str:
        """Constrói a URL base com credenciais atuais."""
        creds = self._get_credentials()
        return f"https://api.z-api.io/instances/{creds['instance_id']}/token/{creds['token']}"

    def _get_headers(self) -> dict:
        """Retorna headers de autenticação com credenciais atuais."""
        return {
            "Content-Type": "application/json",
            "Client-Token": self._get_credentials()["client_token"],
        }

    def is_configured(self) -> bool:
        """Verifica se a Z-API está configurada corretamente."""
        creds = self._get_credentials()
        return bool(creds["instance_id"] and creds["token"] and creds["client_token"])
    
    def _normalize_phone(self, phone: str) -> str:
        """
        Normaliza o número de telefone para o formato Z-API.
        Remove caracteres especiais e garante código do país (55) para Brasil.
        """
        if "@lid" in phone:
            return phone
        
        clean = ''.join(filter(str.isdigit, phone))
        if clean.endswith("@c.us"):
            clean = clean.replace("@c.us", "")
        
        if len(clean) == 10 or len(clean) == 11:
            clean = "55" + clean
        
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

    async def _send_with_retry(self, url: str, payload: dict, headers: dict, timeout: float = 30.0) -> dict:
        """
        Envia request POST com até 3 retentativas para falhas transitórias.
        Total de 4 tentativas: 1 inicial + até 3 retries.
        Retry em TimeoutException, ConnectError e status >= 500.
        Status 4xx retorna imediatamente sem retry.
        Backoff entre tentativas: [1s, 3s, 7s].
        """
        backoff_delays = [1, 3, 7]
        last_error = None
        max_retries = 3
        total_attempts = 1 + max_retries

        for attempt in range(total_attempts):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json=payload, headers=headers, timeout=timeout)

                    try:
                        raw_data = response.json() if response.content else {}
                    except Exception:
                        raw_data = {"error": f"Non-JSON response (HTTP {response.status_code})"}

                    if response.status_code >= 500:
                        last_error = self._parse_response(response, raw_data)
                        if attempt < total_attempts - 1:
                            delay = backoff_delays[attempt]
                            logger.warning(f"[Z-API] Retry {attempt+1}/{max_retries} após HTTP {response.status_code}, aguardando {delay}s")
                            await asyncio.sleep(delay)
                            continue
                        return last_error

                    if response.status_code >= 400:
                        result = self._parse_response(response, raw_data)
                        logger.error(f"[Z-API] Erro 4xx (sem retry): HTTP {response.status_code} - {result.get('error')}")
                        return result

                    return self._parse_response(response, raw_data)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                error_type = "Timeout" if isinstance(e, httpx.TimeoutException) else "ConnectError"
                last_error = {
                    "success": False,
                    "error": f"{error_type}: {e}",
                    "error_code": "TIMEOUT" if isinstance(e, httpx.TimeoutException) else "CONNECTION_ERROR"
                }
                if attempt < total_attempts - 1:
                    delay = backoff_delays[attempt]
                    logger.warning(f"[Z-API] Retry {attempt+1}/{max_retries} após {error_type}, aguardando {delay}s")
                    await asyncio.sleep(delay)
                    continue
                return last_error
            except httpx.HTTPError as e:
                return {
                    "success": False,
                    "error": str(e),
                    "error_code": "HTTP_ERROR"
                }

        return last_error or {"success": False, "error": "Max retries exceeded", "error_code": "MAX_RETRIES"}

    def _get_outbox_session(self):
        from database.database import SessionLocal
        return SessionLocal()

    def _ensure_outbox(self, phone: str, message_type: str, dedupe_key: Optional[str] = None) -> tuple:
        """
        Verifica idempotência via tabela outbox_messages.
        Retorna (dedupe_key, idempotent_response_or_None, outbox_record_or_None).
        Se já existe registro SENT com essa chave, retorna resposta idempotente.
        Usa INSERT com tratamento de IntegrityError para atomicidade.
        """
        from database.models import OutboxMessage, OutboxMessageStatus
        from sqlalchemy.exc import IntegrityError
        if not dedupe_key:
            dedupe_key = str(uuid.uuid4())

        db = self._get_outbox_session()
        try:
            outbox = OutboxMessage(
                dedupe_key=dedupe_key,
                phone=phone,
                message_type=message_type,
                status=OutboxMessageStatus.PENDING.value
            )
            db.add(outbox)
            db.commit()
            db.refresh(outbox)
            return dedupe_key, None, outbox
        except IntegrityError:
            db.rollback()
            existing = db.query(OutboxMessage).filter(OutboxMessage.dedupe_key == dedupe_key).first()
            if existing and existing.status == OutboxMessageStatus.SENT.value:
                return dedupe_key, {
                    "success": True,
                    "idempotent": True,
                    "zaap_id": existing.zaap_id,
                    "message_id": None,
                    "raw_response": {"note": "Idempotent: message already sent"}
                }, None
            return dedupe_key, None, existing
        except Exception as e:
            db.rollback()
            logger.error(f"[Z-API] Outbox DB error (fail-closed): {e}")
            return dedupe_key, {
                "success": False,
                "error": f"Outbox persistence failed: {e}",
                "error_code": "OUTBOX_ERROR"
            }, None
        finally:
            db.close()

    def _mark_outbox_sent(self, dedupe_key: str, zaap_id: Optional[str] = None):
        from database.models import OutboxMessage, OutboxMessageStatus
        db = self._get_outbox_session()
        try:
            record = db.query(OutboxMessage).filter(OutboxMessage.dedupe_key == dedupe_key).first()
            if record:
                record.status = OutboxMessageStatus.SENT.value
                record.zaap_id = zaap_id
                record.sent_at = datetime.utcnow()
                db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"[Z-API] Failed to mark outbox sent: {e}")
        finally:
            db.close()

    def _mark_outbox_failed(self, dedupe_key: str):
        from database.models import OutboxMessage, OutboxMessageStatus
        db = self._get_outbox_session()
        try:
            record = db.query(OutboxMessage).filter(OutboxMessage.dedupe_key == dedupe_key).first()
            if record:
                record.status = OutboxMessageStatus.FAILED.value
                db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"[Z-API] Failed to mark outbox failed: {e}")
        finally:
            db.close()
    
    async def send_text(self, to: str, message: str, delay_message: int = 0, delay_typing: int = 0, dedupe_key: Optional[str] = None) -> dict:
        """
        Envia uma mensagem de texto para um número de WhatsApp.
        
        Args:
            to: Número de telefone no formato internacional (ex: 5511999999999)
            message: Texto da mensagem a ser enviada
            delay_message: Delay entre mensagens em segundos (1-15)
            delay_typing: Tempo mostrando "Digitando..." em segundos (1-15)
            dedupe_key: Chave de idempotência (opcional, gera uuid4 se não fornecido)
            
        Returns:
            Resposta da API Z-API com campos padronizados:
            - success: bool
            - zaap_id: str (ID no Z-API)
            - message_id: str (ID no WhatsApp)
            - error: str (se houver erro)
        """
        normalized_phone = self._normalize_phone(to)
        dedupe_key, idempotent_response, _ = self._ensure_outbox(normalized_phone, "text", dedupe_key)
        if idempotent_response:
            return idempotent_response

        url = f"{self._get_base_url()}/send-text"
        payload = {
            "phone": normalized_phone,
            "message": message,
            "messageId": dedupe_key
        }
        if delay_message > 0:
            payload["delayMessage"] = min(max(delay_message, 1), 15)
        if delay_typing > 0:
            payload["delayTyping"] = min(max(delay_typing, 1), 15)

        result = await self._send_with_retry(url, payload, self._get_headers(), timeout=30.0)
        if result.get("success"):
            self._mark_outbox_sent(dedupe_key, result.get("zaap_id"))
        else:
            self._mark_outbox_failed(dedupe_key)
        return result
    
    async def send_composing(self, to: str) -> dict:
        url = f"{self._get_base_url()}/send-action"
        payload = {
            "phone": self._normalize_phone(to),
            "action": "composing"
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=self._get_headers(), timeout=10.0)
                raw_data = response.json() if response.content else {}
                return self._parse_response(response, raw_data)
            except Exception as e:
                print(f"[Z-API] Erro ao enviar composing para {to}: {e}")
                return {"success": False, "error": str(e)}

    async def send_image(self, to: str, image_url: str, caption: str = "", view_once: bool = False, dedupe_key: Optional[str] = None) -> dict:
        """
        Envia uma imagem para um número de WhatsApp.
        
        Args:
            to: Número de telefone no formato internacional
            image_url: URL da imagem ou Base64
            caption: Legenda da imagem (opcional)
            view_once: Se é visualização única
            dedupe_key: Chave de idempotência (opcional)
        """
        normalized_phone = self._normalize_phone(to)
        dedupe_key, idempotent_response, _ = self._ensure_outbox(normalized_phone, "image", dedupe_key)
        if idempotent_response:
            return idempotent_response

        url = f"{self._get_base_url()}/send-image"
        payload = {
            "phone": normalized_phone,
            "image": image_url,
            "viewOnce": view_once,
            "messageId": dedupe_key
        }
        if caption:
            payload["caption"] = caption

        result = await self._send_with_retry(url, payload, self._get_headers(), timeout=60.0)
        if result.get("success"):
            self._mark_outbox_sent(dedupe_key, result.get("zaap_id"))
        else:
            self._mark_outbox_failed(dedupe_key)
        return result
    
    async def send_video(self, to: str, video_url: str, caption: str = "", view_once: bool = False, dedupe_key: Optional[str] = None) -> dict:
        """
        Envia um vídeo para um número de WhatsApp.
        """
        normalized_phone = self._normalize_phone(to)
        dedupe_key, idempotent_response, _ = self._ensure_outbox(normalized_phone, "video", dedupe_key)
        if idempotent_response:
            return idempotent_response

        url = f"{self._get_base_url()}/send-video"
        payload = {
            "phone": normalized_phone,
            "video": video_url,
            "viewOnce": view_once,
            "messageId": dedupe_key
        }
        if caption:
            payload["caption"] = caption

        result = await self._send_with_retry(url, payload, self._get_headers(), timeout=120.0)
        if result.get("success"):
            self._mark_outbox_sent(dedupe_key, result.get("zaap_id"))
        else:
            self._mark_outbox_failed(dedupe_key)
        return result
    
    async def send_audio(self, to: str, audio_url: str, view_once: bool = False, waveform: bool = True, dedupe_key: Optional[str] = None) -> dict:
        """
        Envia um áudio para um número de WhatsApp.
        """
        normalized_phone = self._normalize_phone(to)
        dedupe_key, idempotent_response, _ = self._ensure_outbox(normalized_phone, "audio", dedupe_key)
        if idempotent_response:
            return idempotent_response

        url = f"{self._get_base_url()}/send-audio"
        payload = {
            "phone": normalized_phone,
            "audio": audio_url,
            "viewOnce": view_once,
            "waveform": waveform,
            "messageId": dedupe_key
        }

        result = await self._send_with_retry(url, payload, self._get_headers(), timeout=60.0)
        if result.get("success"):
            self._mark_outbox_sent(dedupe_key, result.get("zaap_id"))
        else:
            self._mark_outbox_failed(dedupe_key)
        return result
    
    async def send_document(self, to: str, document_url: str, filename: str = "", caption: str = "", dedupe_key: Optional[str] = None) -> dict:
        """
        Envia um documento para um número de WhatsApp.
        """
        normalized_phone = self._normalize_phone(to)
        dedupe_key, idempotent_response, _ = self._ensure_outbox(normalized_phone, "document", dedupe_key)
        if idempotent_response:
            return idempotent_response

        extension = "pdf"
        if filename:
            parts = filename.rsplit('.', 1)
            if len(parts) > 1:
                extension = parts[1].lower()
        elif document_url and '.' in document_url:
            extension = document_url.rsplit('.', 1)[-1].lower().split('?')[0]

        url = f"{self._get_base_url()}/send-document/{extension}"
        payload = {
            "phone": normalized_phone,
            "document": document_url,
            "messageId": dedupe_key
        }
        if filename:
            payload["fileName"] = filename
        if caption:
            payload["caption"] = caption

        result = await self._send_with_retry(url, payload, self._get_headers(), timeout=60.0)
        if result.get("success"):
            self._mark_outbox_sent(dedupe_key, result.get("zaap_id"))
        else:
            self._mark_outbox_failed(dedupe_key)
        return result
    
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
        url = f"{self._get_base_url()}/status"
        
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
        url = f"{self._get_base_url()}/qr-code/image"
        
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
        url = f"{self._get_base_url()}/disconnect"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                data = response.json() if response.content else {}
                return {"success": response.status_code == 200, "raw_response": data}
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}
    
    async def restart(self) -> dict:
        """Reinicia a instância do WhatsApp."""
        url = f"{self._get_base_url()}/restart"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                data = response.json() if response.content else {}
                return {"success": response.status_code == 200, "raw_response": data}
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}
    
    async def update_webhook(self, webhook_url: str) -> dict:
        """Atualiza a URL do webhook para receber mensagens."""
        url = f"{self._get_base_url()}/update-webhook-received"
        
        payload = {"value": webhook_url}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, json=payload, headers=self._get_headers(), timeout=10.0)
                data = response.json() if response.content else {}
                return {"success": response.status_code == 200, "raw_response": data}
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}
    
    async def check_phone_exists(self, phone: str) -> dict:
        """
        Verifica se um número tem WhatsApp e obtém o LID correspondente.
        
        Args:
            phone: Número de telefone no formato internacional
            
        Returns:
            Dict com exists, phone e lid
        """
        url = f"{self._get_base_url()}/phone-exists/{self._normalize_phone(phone)}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=10.0)
                if response.status_code == 200:
                    data = response.json() if response.content else {}
                    return {
                        "success": True,
                        "exists": data.get("exists", False),
                        "phone": data.get("phone"),
                        "lid": data.get("lid")
                    }
                else:
                    return {"success": False, "exists": False}
            except Exception as e:
                return {"success": False, "error": str(e), "exists": False}
    
    async def resolve_lid_to_phone(self, lid: str) -> dict:
        """
        Tenta resolver um LID para número de telefone.
        Nota: Esta é uma operação limitada pela Z-API.
        """
        return {"success": False, "error": "LID to phone conversion not supported by WhatsApp"}
    
    async def get_chats(self, page: int = 1, page_size: int = 50) -> dict:
        """
        Busca todos os chats da instância Z-API.
        
        Args:
            page: Número da página (começa em 1)
            page_size: Quantidade de chats por página
            
        Returns:
            Lista de chats com informações de contato
        """
        url = f"{self._get_base_url()}/chats"
        params = {"page": page, "pageSize": page_size}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), params=params, timeout=30.0)
                
                if response.status_code == 200:
                    data = response.json() if response.content else []
                    return {
                        "success": True,
                        "chats": data if isinstance(data, list) else [],
                        "page": page,
                        "page_size": page_size
                    }
                else:
                    data = response.json() if response.content else {}
                    return {
                        "success": False,
                        "error": data.get("error", f"HTTP {response.status_code}"),
                        "chats": []
                    }
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e), "chats": []}
    
    async def get_all_chats(self, max_pages: int = 10) -> dict:
        """
        Busca todos os chats paginando automaticamente.
        
        Args:
            max_pages: Número máximo de páginas a buscar
            
        Returns:
            Lista completa de chats
        """
        all_chats = []
        page = 1
        last_error = None
        
        while page <= max_pages:
            result = await self.get_chats(page=page, page_size=50)
            
            if not result.get("success"):
                last_error = result.get("error", "Erro desconhecido")
                if page == 1:
                    return {
                        "success": False,
                        "error": last_error,
                        "chats": []
                    }
                break
                
            chats = result.get("chats", [])
            if not chats:
                break
                
            all_chats.extend(chats)
            
            if len(chats) < 50:
                break
                
            page += 1
        
        return {
            "success": True,
            "chats": all_chats,
            "total": len(all_chats)
        }
    
    async def get_chat_messages(self, phone_or_lid: str, amount: int = 100, last_message_id: str = None) -> dict:
        """
        Busca mensagens de um chat específico via Z-API.
        
        Args:
            phone_or_lid: Número de telefone ou LID do chat (@lid)
            amount: Quantidade de mensagens a buscar (padrão 100)
            last_message_id: ID da última mensagem para paginação (busca mensagens anteriores a esta)
            
        Returns:
            Lista de mensagens do chat
        """
        identifier = phone_or_lid
        if "@lid" not in phone_or_lid:
            identifier = self._normalize_phone(phone_or_lid)
        
        url = f"{self._get_base_url()}/chat-messages/{identifier}"
        params = {"amount": amount}
        if last_message_id:
            params["lastMessageId"] = last_message_id
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url, 
                    headers=self._get_headers(), 
                    params=params, 
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json() if response.content else []
                    messages = data if isinstance(data, list) else []
                    return {
                        "success": True,
                        "messages": messages,
                        "count": len(messages)
                    }
                else:
                    data = response.json() if response.content else {}
                    return {
                        "success": False,
                        "error": data.get("error", f"HTTP {response.status_code}"),
                        "messages": []
                    }
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e), "messages": []}


    async def enable_notify_sent_by_me(self, enable: bool = True) -> dict:
        """
        Habilita/desabilita notificações de mensagens enviadas pelo próprio celular.
        Quando habilitado, o webhook on-message-received também recebe mensagens com fromMe=true.
        
        Args:
            enable: True para habilitar, False para desabilitar
            
        Returns:
            Resultado da operação
        """
        url = f"{self._get_base_url()}/update-notify-sent-by-me"
        payload = {"value": enable}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.put(url, json=payload, headers=self._get_headers(), timeout=30.0)
                data = response.json() if response.content else {}
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "enabled": enable,
                        "message": f"Notificação de mensagens enviadas {'habilitada' if enable else 'desabilitada'}"
                    }
                else:
                    return {
                        "success": False,
                        "error": data.get("error", f"HTTP {response.status_code}")
                    }
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}
    
    async def get_webhook_settings(self) -> dict:
        """
        Busca configurações atuais dos webhooks da instância.
        """
        url = f"{self._get_base_url()}/webhooks"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self._get_headers(), timeout=30.0)
                data = response.json() if response.content else {}
                
                if response.status_code == 200:
                    return {"success": True, "settings": data}
                else:
                    return {"success": False, "error": data.get("error", f"HTTP {response.status_code}")}
            except httpx.HTTPError as e:
                return {"success": False, "error": str(e)}


zapi_client = ZAPIClient()


class WhatsAppClient(ZAPIClient):
    """Alias para compatibilidade com código legado."""
    pass


whatsapp_client = zapi_client
