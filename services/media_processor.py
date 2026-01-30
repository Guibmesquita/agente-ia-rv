"""
Serviço de processamento de mídia para o agente de WhatsApp.
Responsável por transcrever áudios, analisar imagens e extrair texto de documentos.
Todas as mídias passam pelo pipeline completo da IA após processamento.
"""
import httpx
import tempfile
import os
from typing import Optional, Tuple
from openai import OpenAI
from core.config import get_settings

settings = get_settings()


class MediaProcessor:
    """Processador de mídia usando OpenAI (Whisper e GPT-4 Vision)."""
    
    def __init__(self):
        self.client = None
        if settings.OPENAI_API_KEY:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    async def download_media(self, media_url: str, timeout: float = 60.0) -> Optional[bytes]:
        """
        Baixa mídia de uma URL (áudio, imagem ou documento).
        
        Args:
            media_url: URL da mídia (geralmente do Z-API)
            timeout: Timeout em segundos
            
        Returns:
            Bytes do arquivo ou None se falhar
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(media_url, timeout=timeout, follow_redirects=True)
                if response.status_code == 200:
                    return response.content
                else:
                    print(f"[MediaProcessor] Erro ao baixar mídia: HTTP {response.status_code}")
                    return None
        except Exception as e:
            print(f"[MediaProcessor] Erro ao baixar mídia: {e}")
            return None
    
    async def transcribe_audio(self, media_url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Transcreve áudio usando OpenAI Whisper.
        
        Args:
            media_url: URL do arquivo de áudio
            
        Returns:
            Tuple (texto transcrito, erro se houver)
        """
        if not self.client:
            return None, "OpenAI não configurado"
        
        try:
            print(f"[MediaProcessor] Baixando áudio: {media_url[:50]}...")
            audio_content = await self.download_media(media_url)
            
            if not audio_content:
                return None, "Não foi possível baixar o áudio"
            
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_file:
                temp_file.write(audio_content)
                temp_path = temp_file.name
            
            try:
                print(f"[MediaProcessor] Transcrevendo áudio ({len(audio_content)} bytes)...")
                
                with open(temp_path, "rb") as audio_file:
                    transcript = self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="pt"
                    )
                
                transcription = transcript.text.strip()
                print(f"[MediaProcessor] Transcrição: {transcription[:100]}...")
                
                return transcription, None
                
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
        except Exception as e:
            print(f"[MediaProcessor] Erro ao transcrever áudio: {e}")
            return None, str(e)
    
    async def analyze_image(self, media_url: str, caption: str = "") -> Tuple[Optional[str], Optional[str]]:
        """
        Analisa imagem usando GPT-4 Vision.
        
        Args:
            media_url: URL da imagem
            caption: Legenda opcional enviada junto com a imagem
            
        Returns:
            Tuple (descrição/análise da imagem, erro se houver)
        """
        if not self.client:
            return None, "OpenAI não configurado"
        
        try:
            print(f"[MediaProcessor] Analisando imagem: {media_url[:50]}...")
            
            user_context = ""
            if caption:
                user_context = f"\n\nO usuário enviou esta legenda junto com a imagem: \"{caption}\""
            
            prompt = f"""Analise esta imagem no contexto de uma conversa de suporte financeiro/investimentos.

Descreva:
1. O que você vê na imagem (gráfico, documento, print de tela, foto, etc)
2. Informações relevantes visíveis (valores, datas, nomes de ativos, indicadores)
3. Se for um documento/relatório, extraia os dados principais

Se a imagem contém texto, transcreva as partes importantes.
Se for um gráfico financeiro, descreva a tendência e dados visíveis.
Se for um print de corretora/app, identifique a plataforma e informações mostradas.{user_context}

Responda de forma concisa e objetiva, focando nas informações úteis para o suporte."""

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": media_url,
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1000
            )
            
            analysis = response.choices[0].message.content.strip()
            print(f"[MediaProcessor] Análise de imagem: {analysis[:100]}...")
            
            return analysis, None
            
        except Exception as e:
            print(f"[MediaProcessor] Erro ao analisar imagem: {e}")
            return None, str(e)
    
    async def extract_document_text(self, media_url: str, filename: str = "") -> Tuple[Optional[str], Optional[str]]:
        """
        Extrai texto de documento (PDF, DOC, etc).
        Para PDFs, usa GPT-4 Vision se possível.
        
        Args:
            media_url: URL do documento
            filename: Nome do arquivo
            
        Returns:
            Tuple (texto extraído/análise, erro se houver)
        """
        if not self.client:
            return None, "OpenAI não configurado"
        
        try:
            print(f"[MediaProcessor] Processando documento: {filename or media_url[:50]}...")
            
            extension = ""
            if filename:
                parts = filename.rsplit(".", 1)
                if len(parts) > 1:
                    extension = parts[1].lower()
            
            doc_content = await self.download_media(media_url)
            if not doc_content:
                return None, "Não foi possível baixar o documento"
            
            doc_type = "documento"
            if extension == "pdf":
                doc_type = "PDF"
            elif extension in ["doc", "docx"]:
                doc_type = "documento Word"
            elif extension in ["xls", "xlsx"]:
                doc_type = "planilha Excel"
            elif extension == "txt":
                try:
                    text_content = doc_content.decode("utf-8")
                    if len(text_content) > 2000:
                        text_content = text_content[:2000] + "... (texto truncado)"
                    return f"Conteúdo do arquivo de texto:\n\n{text_content}", None
                except:
                    pass
            
            description = (
                f"O usuário enviou um {doc_type}"
                + (f" chamado '{filename}'" if filename else "")
                + f" ({len(doc_content)} bytes). "
                "Infelizmente não consigo ler o conteúdo interno deste tipo de arquivo diretamente. "
                "Se você puder me dizer sobre o que é o documento ou qual sua dúvida sobre ele, posso ajudar."
            )
            
            return description, None
            
        except Exception as e:
            print(f"[MediaProcessor] Erro ao processar documento: {e}")
            return None, str(e)
    
    def format_transcription_for_ai(self, transcription: str, media_type: str = "áudio") -> str:
        """
        Formata o conteúdo extraído da mídia para ser processado pela IA.
        
        Args:
            transcription: Texto transcrito/extraído
            media_type: Tipo da mídia original
            
        Returns:
            Mensagem formatada para o pipeline da IA
        """
        if media_type == "áudio":
            return f"[Mensagem de áudio transcrita]: {transcription}"
        elif media_type == "imagem":
            return f"[Análise de imagem enviada]: {transcription}"
        elif media_type == "documento":
            return f"[Documento enviado]: {transcription}"
        else:
            return transcription


media_processor = MediaProcessor()
