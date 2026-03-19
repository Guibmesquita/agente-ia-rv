"""
Endpoints para Campanhas Ativas e Templates de Mensagem.
Permite criar campanhas de disparo em massa para assessores.
"""
import json
import io
import re
import asyncio
import random
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database.database import get_db, SessionLocal
from database.models import MessageTemplate, Campaign, CampaignDispatch, CampaignStatus, Assessor, CampaignStructure
from api.endpoints.auth import require_role
from database.models import User

DISPATCH_DELAY_MIN = 3.0
DISPATCH_DELAY_MAX = 10.0
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 3.0

cancelled_campaigns: dict = {}


def get_random_dispatch_delay() -> float:
    """Retorna um delay aleatório entre 3 e 10 segundos para simular envio manual."""
    return random.uniform(DISPATCH_DELAY_MIN, DISPATCH_DELAY_MAX)


def format_cell_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("R$") or not stripped:
            return value
        if stripped.startswith("0") and not stripped.startswith("0."):
            return value
        try:
            num = float(stripped)
        except (ValueError, TypeError):
            return value
        if num == int(num):
            return str(int(num))
        return f"{num:.2f}"
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"
    if isinstance(value, int):
        return str(value)
    return str(value)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def translate_error_to_natural_language(error_code: str, error_msg: str, phone: str = "") -> str:
    """
    Traduz códigos de erro técnicos para linguagem natural amigável.
    """
    translations = {
        "TIMEOUT": f"O servidor do WhatsApp demorou muito para responder. Isso pode indicar que o serviço está sobrecarregado ou indisponível.",
        "CONNECTION_ERROR": "Não foi possível conectar ao servidor do WhatsApp. Verifique se as credenciais Z-API estão corretas e o serviço está online.",
        "HTTP_401": "Credenciais inválidas. O Token ou Client-Token do Z-API pode estar incorreto.",
        "HTTP_403": "Acesso negado. Verifique as permissões da sua instância Z-API.",
        "HTTP_404": "Endpoint não encontrado. Verifique se o Instance ID está correto.",
        "HTTP_500": "Erro interno no servidor do WhatsApp. O serviço Z-API pode estar com problemas.",
        "HTTP_502": "O servidor do WhatsApp está temporariamente indisponível (Bad Gateway).",
        "HTTP_503": "O servidor do WhatsApp está em manutenção ou sobrecarregado.",
        "API_ERROR": f"A API do WhatsApp retornou um erro: {error_msg}",
        "HTTP_ERROR": f"Erro de comunicação com o servidor: {error_msg}",
    }
    
    if error_code in translations:
        base_msg = translations[error_code]
    elif error_code.startswith("HTTP_"):
        base_msg = f"O servidor retornou código de erro {error_code.replace('HTTP_', '')}: {error_msg}"
    else:
        base_msg = f"Erro ao enviar mensagem: {error_msg}"
    
    if "not registered" in error_msg.lower() or "number not exist" in error_msg.lower():
        base_msg = f"O número {phone} não está registrado no WhatsApp ou está inativo."
    elif "session not found" in error_msg.lower():
        base_msg = "A sessão do WhatsApp não foi encontrada. É necessário reconectar o WhatsApp no painel Z-API."
    elif "not connected" in error_msg.lower():
        base_msg = "O WhatsApp não está conectado. Verifique se o celular está online e conectado à internet."
    elif "invalid phone" in error_msg.lower() or "invalid number" in error_msg.lower():
        base_msg = f"O número {phone} está em formato inválido. Verifique se está no padrão correto (ex: 5511999999999)."
    
    return base_msg


def template_has_required_variables(template: str) -> bool:
    """
    Verifica se o template contém as variáveis obrigatórias.
    Aceita variações com e sem espaços, e com uma ou duas chaves.
    """
    if not template:
        return False
    
    # Padrões aceitos para nome_assessor
    has_nome = any([
        "{{nome_assessor}}" in template,
        "{{ nome_assessor }}" in template,
        "{nome_assessor}" in template,
    ])
    
    # Padrões aceitos para lista_clientes
    has_lista = any([
        "{{lista_clientes}}" in template,
        "{{ lista_clientes }}" in template,
        "{lista_clientes}" in template,
    ])
    
    return has_nome and has_lista


# Mensagem padrao usada quando nenhum template e selecionado
DEFAULT_TEMPLATE_CONTENT = """Ola, {{nome_assessor}}!

Seguem as recomendacoes de troca de ativos para seus clientes:

{{lista_clientes}}

Por favor, entre em contato com cada cliente para alinhar as operacoes.

Atenciosamente,
Equipe de Gestao"""


class TemplateCreate(BaseModel):
    name: str
    content: str
    description: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None
    attachment_filename: Optional[str] = None
    variables_used: Optional[List[str]] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None
    attachment_filename: Optional[str] = None
    variables_used: Optional[List[str]] = None


class ColumnMapping(BaseModel):
    assessor_id: str
    assessor_email: str
    client_id: str
    ativo_saida: str
    valor_saida: str
    ativo_compra: str
    valor_compra: str


class CustomFieldMapping(BaseModel):
    column_name: str
    variable_name: str


class CampaignCreate(BaseModel):
    name: str
    template_id: Optional[int] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    template_id: Optional[int] = None
    column_mapping: Optional[dict] = None
    custom_fields_mapping: Optional[dict] = None


class CampaignDispatchRequest(BaseModel):
    campaign_id: int


def require_admin_or_gestao():
    """Dependency that requires admin or gestao_rv role."""
    return require_role(["admin", "gestao_rv"])


@router.get("/templates")
async def list_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Lista todos os templates de mensagem ativos."""
    templates = db.query(MessageTemplate).filter(
        MessageTemplate.is_active == 1
    ).order_by(MessageTemplate.name).all()
    
    return [
        {
            "id": t.id,
            "name": t.name,
            "content": t.content,
            "description": t.description,
            "attachment_url": t.attachment_url,
            "attachment_type": t.attachment_type,
            "attachment_filename": t.attachment_filename,
            "variables_used": json.loads(t.variables_used) if t.variables_used else [],
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None
        }
        for t in templates
    ]


@router.get("/templates/{template_id}")
async def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Busca um template por ID."""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    
    return {
        "id": template.id,
        "name": template.name,
        "content": template.content,
        "description": template.description,
        "is_active": template.is_active == 1,
        "attachment_url": template.attachment_url,
        "attachment_type": template.attachment_type,
        "attachment_filename": template.attachment_filename,
        "variables_used": json.loads(template.variables_used) if template.variables_used else [],
        "created_at": template.created_at.isoformat() if template.created_at else None
    }


def extract_variables_from_content(content: str) -> List[str]:
    """Extrai variáveis no formato {{variavel}} do conteúdo."""
    pattern = r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}'
    matches = re.findall(pattern, content)
    return list(set(matches))


@router.post("/templates")
async def create_template(
    data: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Cria um novo template de mensagem."""
    variables = data.variables_used or extract_variables_from_content(data.content)
    
    template = MessageTemplate(
        name=data.name,
        content=data.content,
        description=data.description,
        attachment_url=data.attachment_url,
        attachment_type=data.attachment_type,
        attachment_filename=data.attachment_filename,
        variables_used=json.dumps(variables),
        created_by=int(current_user.id),
        is_active=1
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    
    return {
        "id": template.id,
        "name": template.name,
        "variables_used": variables,
        "message": "Template criado com sucesso"
    }


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Atualiza um template existente."""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    
    if data.name is not None:
        template.name = data.name
    if data.content is not None:
        template.content = data.content
        template.variables_used = json.dumps(extract_variables_from_content(data.content))
    if data.description is not None:
        template.description = data.description
    if data.is_active is not None:
        template.is_active = 1 if data.is_active else 0
    if data.attachment_url is not None:
        template.attachment_url = data.attachment_url
    if data.attachment_type is not None:
        template.attachment_type = data.attachment_type
    if data.attachment_filename is not None:
        template.attachment_filename = data.attachment_filename
    if data.variables_used is not None:
        template.variables_used = json.dumps(data.variables_used)
    
    db.commit()
    db.refresh(template)
    
    return {
        "message": "Template atualizado com sucesso",
        "variables_used": json.loads(template.variables_used) if template.variables_used else []
    }


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Remove um template (soft delete)."""
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    
    template.is_active = 0
    db.commit()
    
    return {"message": "Template removido com sucesso"}


import os
import uuid
from pathlib import Path

ATTACHMENTS_DIR = Path("uploads/attachments")
ALLOWED_ATTACHMENT_TYPES = {
    'image/jpeg': 'image',
    'image/png': 'image',
    'image/gif': 'image',
    'image/webp': 'image',
    'video/mp4': 'video',
    'video/quicktime': 'video',
    'audio/mpeg': 'audio',
    'audio/mp3': 'audio',
    'audio/ogg': 'audio',
    'audio/wav': 'audio',
    'application/pdf': 'document',
    'application/msword': 'document',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'document',
    'application/vnd.ms-excel': 'document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'document',
    'text/plain': 'document',
}


@router.post("/attachments/upload")
async def upload_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Faz upload de anexo (imagem, vídeo, áudio ou documento) para campanhas/templates.
    Retorna a URL do arquivo para ser usada no template ou campanha.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome do arquivo inválido")
    
    content_type = file.content_type or 'application/octet-stream'
    
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        allowed_types = list(ALLOWED_ATTACHMENT_TYPES.keys())
        raise HTTPException(
            status_code=400, 
            detail=f"Tipo de arquivo não permitido. Tipos aceitos: imagem (JPEG, PNG, GIF, WebP), vídeo (MP4), áudio (MP3, OGG, WAV), documento (PDF, DOC, DOCX, XLS, XLSX, TXT)"
        )
    
    attachment_type = ALLOWED_ATTACHMENT_TYPES[content_type]
    
    file_ext = Path(file.filename).suffix.lower()
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = ATTACHMENTS_DIR / unique_filename
    
    try:
        contents = await file.read()
        max_size = 50 * 1024 * 1024
        if len(contents) > max_size:
            raise HTTPException(status_code=400, detail="Arquivo muito grande. Tamanho máximo: 50MB")
        
        with open(file_path, 'wb') as f:
            f.write(contents)
        
        file_url = f"/uploads/attachments/{unique_filename}"
        
        return {
            "success": True,
            "url": file_url,
            "type": attachment_type,
            "filename": file.filename,
            "size": len(contents),
            "message": "Arquivo enviado com sucesso"
        }
    except HTTPException:
        raise
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f"Erro ao salvar arquivo: {str(e)}")


@router.delete("/attachments")
async def delete_attachment(
    url: str,
    current_user: User = Depends(require_admin_or_gestao())
):
    """Remove um anexo pelo URL."""
    if not url or not url.startswith("/uploads/attachments/"):
        raise HTTPException(status_code=400, detail="URL de anexo inválida")
    
    filename = url.replace("/uploads/attachments/", "")
    file_path = ATTACHMENTS_DIR / filename
    
    if file_path.exists():
        file_path.unlink()
        return {"message": "Anexo removido com sucesso"}
    else:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")


@router.post("/upload")
async def upload_campaign_file(
    file: UploadFile = File(...),
    campaign_name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Faz upload de arquivo CSV/Excel e retorna as colunas para mapeamento.
    Cria uma campanha em rascunho.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome do arquivo inválido")
    
    filename = file.filename.lower()
    if not (filename.endswith('.csv') or filename.endswith('.xlsx') or filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="Formato inválido. Use CSV ou Excel.")
    
    try:
        contents = await file.read()
        
        if filename.endswith('.csv'):
            import csv
            text = contents.decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(text))
            columns = reader.fieldnames or []
            rows = list(reader)
        else:
            import pandas as pd
            df = pd.read_excel(io.BytesIO(contents))
            columns = df.columns.tolist()
            rows = df.to_dict('records')
        
        campaign = Campaign(
            name=campaign_name,
            status=CampaignStatus.DRAFT.value,
            original_filename=file.filename,
            total_recommendations=len(rows),
            processed_data=json.dumps(rows, default=str),
            created_by=int(current_user.id)
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        
        suggested_mapping = suggest_column_mapping(columns)
        
        return {
            "campaign_id": campaign.id,
            "filename": file.filename,
            "columns": columns,
            "row_count": len(rows),
            "suggested_mapping": suggested_mapping,
            "preview": rows[:5] if rows else []
        }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao processar arquivo: {str(e)}")


def suggest_column_mapping(columns: List[str]) -> dict:
    """Sugere mapeamento automático baseado nos nomes das colunas."""
    mapping = {}
    columns_lower = {c.lower().strip(): c for c in columns}
    
    field_patterns = {
        "assessor_id": ["assessor", "id_assessor", "cod_assessor", "codigo_assessor", "advisor"],
        "assessor_email": ["email", "email_assessor", "e-mail", "mail", "assessor_email"],
        "client_id": ["cliente", "id_cliente", "cod_cliente", "codigo_cliente", "client"],
        "ativo_saida": ["ativo_saida", "saida", "venda", "papel_saida", "ticker_saida"],
        "valor_saida": ["valor_saida", "vl_saida", "valor_venda"],
        "ativo_compra": ["ativo_compra", "compra", "papel_compra", "ticker_compra"],
        "valor_compra": ["valor_compra", "vl_compra", "valor_entrada"]
    }
    
    for field, patterns in field_patterns.items():
        for pattern in patterns:
            if pattern in columns_lower:
                mapping[field] = columns_lower[pattern]
                break
    
    return mapping


class CampaignFromBaseRequest(BaseModel):
    name: str
    assessor_ids: List[int]


@router.post("/from-base")
async def create_campaign_from_base(
    data: CampaignFromBaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Cria uma campanha a partir de assessores selecionados da base.
    Não requer mapeamento de colunas pois os dados já estão estruturados.
    """
    if not data.assessor_ids:
        raise HTTPException(status_code=400, detail="Nenhum assessor selecionado")
    
    assessores = db.query(Assessor).filter(Assessor.id.in_(data.assessor_ids)).all()
    
    if len(assessores) != len(data.assessor_ids):
        raise HTTPException(status_code=400, detail="Um ou mais assessores não foram encontrados")
    
    assessor_data = []
    for a in assessores:
        assessor_data.append({
            "id": a.id,
            "codigo_ai": a.codigo_ai,
            "nome": a.nome,
            "email": a.email,
            "telefone_whatsapp": a.telefone_whatsapp,
            "unidade": a.unidade,
            "equipe": a.equipe,
            "broker_responsavel": a.broker_responsavel
        })
    
    campaign = Campaign(
        name=data.name,
        status=CampaignStatus.DRAFT.value,
        original_filename=None,
        total_recommendations=0,
        total_assessors=len(assessores),
        source_type="base",
        processed_data=json.dumps(assessor_data, default=str),
        created_by=int(current_user.id)
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    
    return {
        "campaign_id": campaign.id,
        "assessor_count": len(assessores),
        "message": "Campanha criada com sucesso"
    }


class CampaignMappingRequest(BaseModel):
    column_mapping: Optional[dict] = None
    custom_fields_mapping: Optional[dict] = None
    message_template: Optional[str] = None
    message_blocks: Optional[dict] = None
    message_header: Optional[str] = None
    message_content_template: Optional[str] = None
    message_footer: Optional[str] = None
    group_by_client: Optional[bool] = False
    content_line_template: Optional[str] = None
    assessor_code_column: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None
    attachment_filename: Optional[str] = None


@router.put("/{campaign_id}/mapping")
async def update_campaign_mapping(
    campaign_id: int,
    request: CampaignMappingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Atualiza o mapeamento de colunas de uma campanha."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    if request.column_mapping:
        campaign.column_mapping = json.dumps(request.column_mapping)
    
    if request.custom_fields_mapping:
        campaign.custom_fields_mapping = json.dumps(request.custom_fields_mapping)
    
    if request.message_template:
        campaign.message_content = request.message_template
    
    if request.message_blocks:
        campaign.message_header = request.message_blocks.get("header", "")
        campaign.message_content_template = request.message_blocks.get("content", "")
        campaign.message_footer = request.message_blocks.get("footer", "")
    
    if request.message_header is not None:
        campaign.message_header = request.message_header
    if request.message_content_template is not None:
        campaign.message_content_template = request.message_content_template
    if request.message_footer is not None:
        campaign.message_footer = request.message_footer
    
    if request.content_line_template:
        campaign.message_content_template = request.content_line_template
    
    campaign.group_by_client = 1 if request.group_by_client else 0
    
    if request.assessor_code_column:
        mapping = json.loads(campaign.column_mapping or "{}")
        mapping["codigo_ai"] = request.assessor_code_column
        campaign.column_mapping = json.dumps(mapping)
    
    if request.attachment_url is not None:
        campaign.attachment_url = request.attachment_url
    if request.attachment_type is not None:
        campaign.attachment_type = request.attachment_type
    if request.attachment_filename is not None:
        campaign.attachment_filename = request.attachment_filename
    
    db.commit()
    
    return {"message": "Mapeamento atualizado com sucesso"}


@router.put("/{campaign_id}/template")
async def set_campaign_template(
    campaign_id: int,
    template_id: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Define o template de mensagem para a campanha."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    if template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template não encontrado")
        campaign.template_id = template_id
    
    db.commit()
    
    return {"message": "Template definido com sucesso"}


class MessageBlocksModel(BaseModel):
    header: Optional[str] = ""
    content: Optional[str] = ""
    footer: Optional[str] = ""


class CustomTemplateRequest(BaseModel):
    content: Optional[str] = None
    message_blocks: Optional[MessageBlocksModel] = None
    message_header: Optional[str] = None
    message_content_template: Optional[str] = None
    message_footer: Optional[str] = None
    content_line_template: Optional[str] = None
    group_by_client: Optional[bool] = False
    client_id_column: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None
    attachment_filename: Optional[str] = None


@router.put("/{campaign_id}/custom-template")
async def set_custom_template(
    campaign_id: int,
    request: CustomTemplateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Define um template customizado (editado) para a campanha."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    header = None
    content_template = None
    footer = None
    
    if request.message_blocks:
        header = request.message_blocks.header or ""
        content_template = request.message_blocks.content or request.content_line_template or ""
        footer = request.message_blocks.footer or ""
    elif request.message_header is not None or request.message_content_template is not None or request.message_footer is not None:
        header = request.message_header or ""
        content_template = request.message_content_template or request.content_line_template or ""
        footer = request.message_footer or ""
    
    if header is not None or content_template is not None or footer is not None:
        campaign.message_header = header
        campaign.message_content_template = content_template or request.content_line_template
        campaign.message_footer = footer
        campaign.group_by_client = 1 if request.group_by_client else 0
        campaign.client_id_column = request.client_id_column
        
        full_content_parts = []
        if header:
            full_content_parts.append(header)
        if content_template:
            full_content_parts.append(content_template)
        if footer:
            full_content_parts.append(footer)
        campaign.custom_template_content = "\n\n".join(full_content_parts) if full_content_parts else request.content
    elif request.content:
        campaign.custom_template_content = request.content
    
    if request.attachment_url is not None:
        campaign.attachment_url = request.attachment_url
    if request.attachment_type is not None:
        campaign.attachment_type = request.attachment_type
    if request.attachment_filename is not None:
        campaign.attachment_filename = request.attachment_filename
    
    db.commit()
    
    return {"message": "Template customizado salvo com sucesso"}


@router.get("/{campaign_id}/preview")
async def preview_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Gera preview das mensagens agrupadas por assessor.
    Aplica a lógica de agrupamento e substitui variáveis.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    source_type = getattr(campaign, 'source_type', 'upload') or 'upload'
    
    if source_type == "base":
        return await preview_campaign_from_base(campaign, db)
    
    # Usa template customizado se existir, senao template salvo, senao mensagem padrao
    template_content = DEFAULT_TEMPLATE_CONTENT
    template_name = "Mensagem Padrao"
    
    if campaign.custom_template_content:
        candidate = str(campaign.custom_template_content)
        if template_has_required_variables(candidate):
            template_content = candidate
            template_name = "Mensagem Editada"
        else:
            print(f"[PREVIEW] Template customizado não contém variáveis obrigatórias, usando padrão")
    elif campaign.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
        if template:
            candidate = str(template.content)
            if template_has_required_variables(candidate):
                template_content = candidate
                template_name = str(template.name)
            else:
                print(f"[PREVIEW] Template salvo não contém variáveis obrigatórias, usando padrão")
    
    try:
        column_mapping = json.loads(str(campaign.column_mapping)) if campaign.column_mapping else {}
        custom_mapping = json.loads(str(campaign.custom_fields_mapping)) if campaign.custom_fields_mapping else {}
        data = json.loads(str(campaign.processed_data)) if campaign.processed_data else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Erro nos dados da campanha")
    
    print(f"[DEBUG PREVIEW] campaign_id={campaign_id}")
    print(f"[DEBUG PREVIEW] column_mapping={column_mapping}")
    print(f"[DEBUG PREVIEW] custom_mapping={custom_mapping}")
    print(f"[DEBUG PREVIEW] data rows count={len(data)}")
    if data:
        print(f"[DEBUG PREVIEW] first row keys={list(data[0].keys())}")
        print(f"[DEBUG PREVIEW] first row sample={data[0]}")
    
    if not column_mapping:
        raise HTTPException(status_code=400, detail="Mapeamento de colunas não definido")
    
    grouped = group_recommendations_by_assessor(data, column_mapping, custom_mapping, db)
    print(f"[DEBUG PREVIEW] grouped keys={list(grouped.keys())}")
    if grouped:
        first_key = list(grouped.keys())[0]
        print(f"[DEBUG PREVIEW] first assessor data={grouped[first_key]}")
    
    campaign.total_assessors = len(grouped)
    db.commit()
    
    content_line_template = campaign.message_content_template or ""
    
    messages = []
    first_example = None
    
    for idx, (assessor_id, assessor_data) in enumerate(grouped.items()):
        message = build_message(template_content, assessor_data, custom_mapping, content_line_template)
        messages.append({
            "assessor_id": assessor_id,
            "assessor_name": assessor_data.get("nome_assessor", ""),
            "assessor_phone": assessor_data.get("telefone", ""),
            "client_count": len(assessor_data.get("clients", {})),
            "recommendation_count": assessor_data.get("total_recommendations", 0),
            "message_preview": message
        })
        
        if idx == 0:
            clients_data = assessor_data.get("clients", {})
            
            header_template = campaign.message_header or ""
            content_template = campaign.message_content_template or ""
            footer_template = campaign.message_footer or ""
            
            import unicodedata
            
            def normalize_var_name(name: str) -> str:
                """Remove acentos e normaliza nome de variável."""
                if not name:
                    return ""
                normalized = unicodedata.normalize('NFKD', str(name))
                ascii_text = normalized.encode('ASCII', 'ignore').decode('ASCII')
                return ascii_text.lower().replace(' ', '_').replace('-', '_')
            
            def is_formatted_currency(value) -> bool:
                """Verifica se o valor já está formatado como moeda."""
                if not isinstance(value, str):
                    return False
                return value.strip().startswith("R$")
            
            def replace_vars(text, data):
                result = text
                normalized_data = {}
                for key, value in data.items():
                    if isinstance(value, (dict, list)):
                        continue
                    norm_key = normalize_var_name(key)
                    str_value = format_cell_value(value)
                    
                    if norm_key in normalized_data:
                        existing = normalized_data[norm_key]
                        if is_formatted_currency(existing) and not is_formatted_currency(str_value):
                            continue
                    
                    normalized_data[norm_key] = str_value
                    normalized_data[str(key)] = str_value
                
                import re
                pattern = r'\{\{\s*([^}]+?)\s*\}\}'
                def replacer(match):
                    var_name = match.group(1).strip()
                    normalized_name = normalize_var_name(var_name)
                    if normalized_name in normalized_data:
                        return normalized_data[normalized_name]
                    if var_name in normalized_data:
                        return normalized_data[var_name]
                    return match.group(0)
                
                result = re.sub(pattern, replacer, result)
                return result
            
            nome_assessor = assessor_data.get("nome_assessor", "") or assessor_data.get("nome", "")
            primeiro_nome = str(nome_assessor).split()[0] if nome_assessor else ""
            
            extra_vars = {
                "nome_assessor": nome_assessor,
                "primeiro_nome": primeiro_nome,
                "nome": nome_assessor
            }
            
            header_rendered = replace_vars(header_template, assessor_data)
            header_rendered = replace_vars(header_rendered, extra_vars)
            
            content_lines = []
            total_recs = 0
            has_custom_template = bool(content_template and content_template.strip())
            for client_id, client_info in clients_data.items():
                recommendations = client_info.get("recommendations", [])
                if recommendations:
                    if not has_custom_template:
                        content_lines.append(f"*Cliente: {client_id}*")
                    for rec in recommendations:
                        line = replace_vars(content_template, rec)
                        line = replace_vars(line, assessor_data)
                        line = replace_vars(line, extra_vars)
                        if line.strip():
                            if has_custom_template:
                                content_lines.append(line)
                            else:
                                content_lines.append(f"• {line}")
                        total_recs += 1
                    content_lines.append("")
            
            footer_rendered = replace_vars(footer_template, assessor_data)
            footer_rendered = replace_vars(footer_rendered, extra_vars)
            
            first_example = {
                "assessor_name": assessor_data.get("nome_assessor", "Assessor"),
                "assessor_id": assessor_id,
                "recommendation_count": total_recs,
                "header_rendered": header_rendered,
                "content_lines": content_lines,
                "footer_rendered": footer_rendered
            }
    
    return {
        "campaign_id": campaign.id,
        "total_assessors": len(messages),
        "total_recommendations": campaign.total_recommendations,
        "messages": messages[:5],
        "template_name": template_name,
        "first_example": first_example
    }


async def preview_campaign_from_base(campaign, db: Session):
    """
    Gera preview para campanhas baseadas em assessores selecionados da base.
    Não tem recomendações de ativos, apenas lista de assessores para disparo.
    Mostra exatamente o que o usuário preencheu, sem dados de exemplo.
    """
    header_template = campaign.message_header or ""
    content_template = campaign.message_content_template or ""
    footer_template = campaign.message_footer or ""
    
    template_name = "Mensagem Personalizada"
    if not header_template and not content_template and not footer_template:
        if campaign.custom_template_content:
            content_template = str(campaign.custom_template_content)
            template_name = "Mensagem Editada"
        elif campaign.template_id:
            template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
            if template:
                content_template = str(template.content)
                template_name = str(template.name)
    
    try:
        data = json.loads(str(campaign.processed_data)) if campaign.processed_data else []
    except json.JSONDecodeError:
        data = []
    
    first_example = {
        "assessor_name": "Assessor Exemplo",
        "header_rendered": header_template.strip() if header_template.strip() else None,
        "content_lines": [content_template.strip()] if content_template.strip() else [],
        "footer_rendered": footer_template.strip() if footer_template.strip() else None,
        "header_empty": not header_template.strip(),
        "content_empty": not content_template.strip(),
        "footer_empty": not footer_template.strip()
    }
    
    messages = []
    
    for idx, assessor in enumerate(data):
        variables = build_assessor_variables(assessor)
        
        header_rendered = replace_variables_generic(header_template, variables)
        content_rendered = replace_variables_generic(content_template, variables)
        footer_rendered = replace_variables_generic(footer_template, variables)
        
        message_parts = []
        if header_rendered.strip():
            message_parts.append(header_rendered.strip())
        if content_rendered.strip():
            message_parts.append(content_rendered.strip())
        if footer_rendered.strip():
            message_parts.append(footer_rendered.strip())
        
        full_message = "\n\n".join(message_parts) if message_parts else "(Mensagem vazia)"
        
        if idx == 0:
            first_example = {
                "assessor_name": assessor.get("nome", "Assessor"),
                "header_rendered": header_rendered.strip() if header_rendered.strip() else None,
                "content_lines": [content_rendered.strip()] if content_rendered.strip() else [],
                "footer_rendered": footer_rendered.strip() if footer_rendered.strip() else None,
                "header_empty": not header_template.strip(),
                "content_empty": not content_template.strip(),
                "footer_empty": not footer_template.strip()
            }
        
        messages.append({
            "assessor_id": str(assessor.get("id", "")),
            "assessor_name": assessor.get("nome", ""),
            "assessor_phone": assessor.get("telefone_whatsapp", ""),
            "client_count": 0,
            "recommendation_count": 0,
            "message_preview": full_message
        })
    
    return {
        "campaign_id": campaign.id,
        "total_assessors": len(messages),
        "total_recommendations": 0,
        "messages": messages[:5],
        "template_name": template_name,
        "source_type": "base",
        "first_example": first_example
    }


def group_recommendations_by_assessor(data: List[dict], mapping: dict, custom_mapping: dict, db: Session) -> dict:
    """
    Agrupa recomendações por assessor.
    
    Suporta dois modos:
    1. Modo legado: usa assessor_id/assessor_email para identificar assessores e constrói lista_clientes
    2. Modo codigo_ai: usa codigo_ai para vincular com base interna e disponibiliza variáveis da planilha
    
    Retorna um dicionário com dados do assessor e recomendações agrupadas.
    """
    grouped = {}
    
    col_codigo_ai = mapping.get("codigo_ai", "")
    col_assessor = mapping.get("assessor_id", "")
    col_assessor_email = mapping.get("assessor_email", "")
    col_client = mapping.get("client_id", "")
    col_ativo_saida = mapping.get("ativo_saida", "")
    col_valor_saida = mapping.get("valor_saida", "")
    col_ativo_compra = mapping.get("ativo_compra", "")
    col_valor_compra = mapping.get("valor_compra", "")
    
    def find_column(row, possible_names):
        """Busca uma coluna pelos possíveis nomes (com e sem acentos)."""
        for name in possible_names:
            if name in row:
                return name
        return None
    
    ativo_saida_names = ["Ativo saída", "Ativo Saída", "ativo_saida", "ativo saida", "ATIVO SAÍDA", "Ativo Saida"]
    valor_saida_names = ["Valor saída", "Valor Saída", "valor_saida", "valor saida", "VALOR SAÍDA", "Valor Saida"]
    ativo_compra_names = ["Ativo compra", "Ativo Compra", "ativo_compra", "ativo compra", "ATIVO COMPRA", "Ativo Entrada"]
    valor_compra_names = ["Valor compra", "Valor Compra", "valor_compra", "valor compra", "VALOR COMPRA", "Valor Entrada"]
    
    use_codigo_ai_mode = bool(col_codigo_ai) and not col_assessor
    
    print(f"[GROUPING] Column mapping: codigo_ai={col_codigo_ai}, assessor={col_assessor}")
    print(f"[GROUPING] Mode: {'codigo_ai' if use_codigo_ai_mode else 'legacy'}")
    print(f"[GROUPING] Total rows to process: {len(data)}")
    
    for idx, row in enumerate(data):
        if use_codigo_ai_mode:
            codigo_ai_val = row.get(col_codigo_ai, "")
            if codigo_ai_val is None:
                codigo_ai_val = ""
            key = str(codigo_ai_val).strip()
        else:
            assessor_val = row.get(col_assessor, "")
            if assessor_val is None:
                assessor_val = ""
            key = str(assessor_val).strip()
        
        if not key:
            print(f"[GROUPING] Row {idx}: No key found, skipping")
            continue
        
        if key not in grouped:
            if use_codigo_ai_mode:
                assessor = db.query(Assessor).filter(Assessor.codigo_ai == key).first()
            else:
                assessor = None
                email_from_sheet = ""
                if col_assessor_email:
                    email_val = row.get(col_assessor_email, "")
                    if email_val:
                        email_from_sheet = str(email_val).strip()
                        assessor = db.query(Assessor).filter(Assessor.email == email_from_sheet).first()
                
                if not assessor:
                    try:
                        assessor_id_int = int(key)
                        assessor = db.query(Assessor).filter(Assessor.id == assessor_id_int).first()
                    except (ValueError, TypeError):
                        pass
                
                if not assessor:
                    assessor = db.query(Assessor).filter(
                        (Assessor.telefone_whatsapp == key) |
                        (Assessor.nome.ilike(f"%{key}%"))
                    ).first()
            
            if assessor:
                grouped[key] = {
                    "codigo_ai": assessor.codigo_ai or "",
                    "nome": assessor.nome or "",
                    "email": assessor.email or "",
                    "telefone_whatsapp": assessor.telefone_whatsapp or "",
                    "telefone": assessor.telefone_whatsapp or "",
                    "unidade": assessor.unidade or "",
                    "equipe": assessor.equipe or "",
                    "broker_responsavel": assessor.broker_responsavel or "",
                    "nome_assessor": assessor.nome or "",
                    "assessor_id": key,
                    "email_assessor": assessor.email or "",
                    "clients": {},
                    "total_recommendations": 0,
                    "custom_fields": {},
                    "spreadsheet_data": {}
                }
            else:
                grouped[key] = {
                    "codigo_ai": key if use_codigo_ai_mode else "",
                    "nome": key if not use_codigo_ai_mode else "",
                    "email": "",
                    "telefone_whatsapp": "",
                    "telefone": "",
                    "unidade": "",
                    "equipe": "",
                    "broker_responsavel": "",
                    "nome_assessor": key if not use_codigo_ai_mode else "",
                    "assessor_id": key,
                    "email_assessor": "",
                    "clients": {},
                    "total_recommendations": 0,
                    "custom_fields": {},
                    "spreadsheet_data": {}
                }
                print(f"[GROUPING] Warning: Assessor not found for key={key}")
            
            print(f"[GROUPING] New assessor: {key} -> nome={grouped[key]['nome']}")
        
        for col_name, col_val in row.items():
            if col_name not in grouped[key]["spreadsheet_data"]:
                grouped[key]["spreadsheet_data"][col_name] = col_val
        
        if isinstance(custom_mapping, dict):
            for col_name, var_name in custom_mapping.items():
                if col_name in row and row[col_name]:
                    grouped[key]["custom_fields"][var_name] = str(row[col_name])
        elif isinstance(custom_mapping, list):
            for custom_item in custom_mapping:
                if isinstance(custom_item, dict):
                    col_name = custom_item.get("column_name", "")
                    var_name = custom_item.get("variable_name", "")
                    if col_name in row and row[col_name]:
                        grouped[key]["custom_fields"][var_name] = str(row[col_name])
        
        if col_client:
            client_val = row.get(col_client, "")
            if client_val is None:
                client_val = ""
            client_id = str(client_val).strip()
            
            if not client_id:
                client_id = "Sem ID"
            
            if client_id not in grouped[key]["clients"]:
                grouped[key]["clients"][client_id] = {"client_id": client_id, "recommendations": []}
            
            real_col_ativo_saida = col_ativo_saida or find_column(row, ativo_saida_names)
            real_col_valor_saida = col_valor_saida or find_column(row, valor_saida_names)
            real_col_ativo_compra = col_ativo_compra or find_column(row, ativo_compra_names)
            real_col_valor_compra = col_valor_compra or find_column(row, valor_compra_names)
            
            recommendation = {
                "ativo_saida": str(row.get(real_col_ativo_saida, "") or "") if real_col_ativo_saida else "",
                "valor_saida": format_currency(row.get(real_col_valor_saida, 0)) if real_col_valor_saida else "R$ 0,00",
                "ativo_compra": str(row.get(real_col_ativo_compra, "") or "") if real_col_ativo_compra else "",
                "valor_compra": format_currency(row.get(real_col_valor_compra, 0)) if real_col_valor_compra else "R$ 0,00",
                "client_id": client_id
            }
            
            mapped_currency_cols = set()
            if real_col_valor_saida:
                mapped_currency_cols.add(real_col_valor_saida)
            if real_col_valor_compra:
                mapped_currency_cols.add(real_col_valor_compra)
            
            protected_keys = {"ativo_saida", "valor_saida", "ativo_compra", "valor_compra", "client_id"}
            for col_name, col_val in row.items():
                if col_name in protected_keys:
                    continue
                if col_name in mapped_currency_cols:
                    recommendation[col_name] = format_currency(col_val)
                else:
                    recommendation[col_name] = col_val
            
            grouped[key]["clients"][client_id]["recommendations"].append(recommendation)
            grouped[key]["total_recommendations"] += 1
    
    print(f"[GROUPING] Final result: {len(grouped)} assessors")
    for aid, adata in grouped.items():
        client_count = len(adata.get('clients', {}))
        rec_count = adata.get('total_recommendations', 0)
        print(f"[GROUPING]   {aid}: nome={adata['nome']}, clients={client_count}, recs={rec_count}")
    
    return grouped


def is_currency_value(value) -> bool:
    """Detecta se um valor parece ser monetário (R$ ou número grande)."""
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value >= 100
    if isinstance(value, str):
        s = str(value).strip()
        if "R$" in s:
            return True
        cleaned = s.replace(".", "").replace(",", ".")
        try:
            num = float(cleaned)
            return num >= 100
        except (ValueError, TypeError):
            return False
    return False


def format_currency(value) -> str:
    """Formata valor para moeda brasileira."""
    if value is None:
        return "R$ 0,00"
    if isinstance(value, str) and "R$" in value:
        return value
    try:
        if isinstance(value, str):
            value = value.replace("R$", "").replace(".", "").replace(",", ".").strip()
            if not value:
                return "R$ 0,00"
        num = float(value)
        return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return str(value) if value else "R$ 0,00"


def build_message(template_content: str, assessor_data: dict, custom_mapping: dict, content_template: str = None) -> str:
    """
    Constrói a mensagem final substituindo as variáveis do template.
    
    Variáveis suportadas:
    - Variáveis da base interna: {{codigo_ai}}, {{nome}}, {{email}}, {{telefone_whatsapp}}, 
      {{unidade}}, {{equipe}}, {{broker_responsavel}}
    - Variáveis da planilha importada: qualquer coluna detectada
    - Campos customizados definidos no mapeamento
    - {{data_atual}} - Data atual (DD/MM/YYYY)
    
    Args:
        content_template: Template para cada linha de recomendação (bloco repetível).
                         Se fornecido, cada recomendação será processada com este template.
    """
    if not template_content:
        template_content = DEFAULT_TEMPLATE_CONTENT
    
    message = str(template_content)
    
    print(f"[BUILD_MSG] Input template (first 200 chars): {message[:200]}")
    if content_template:
        print(f"[BUILD_MSG] Content template for blocks: {content_template[:100]}")
    
    nome = str(assessor_data.get("nome", "") or "")
    primeiro_nome = nome.split()[0] if nome else ""
    
    base_vars = {
        "codigo_ai": str(assessor_data.get("codigo_ai", "") or ""),
        "nome": nome,
        "primeiro_nome": primeiro_nome,
        "email": str(assessor_data.get("email", "") or ""),
        "telefone_whatsapp": str(assessor_data.get("telefone_whatsapp", "") or ""),
        "telefone": str(assessor_data.get("telefone", "") or ""),
        "unidade": str(assessor_data.get("unidade", "") or ""),
        "equipe": str(assessor_data.get("equipe", "") or ""),
        "broker_responsavel": str(assessor_data.get("broker_responsavel", "") or ""),
        "nome_assessor": nome,
        "assessor_id": str(assessor_data.get("codigo_ai", "") or ""),
    }
    
    for var_name, value in base_vars.items():
        for pattern in [f"{{{{{var_name}}}}}", f"{{{{ {var_name} }}}}", f"{{{var_name}}}"]:
            message = message.replace(pattern, value)
    
    data_atual = datetime.now().strftime("%d/%m/%Y")
    for pattern in ["{{data_atual}}", "{{ data_atual }}", "{data_atual}"]:
        message = message.replace(pattern, data_atual)
    
    spreadsheet_data = assessor_data.get("spreadsheet_data", {})
    if spreadsheet_data:
        print(f"[BUILD_MSG] Spreadsheet data keys: {list(spreadsheet_data.keys())}")
        for col_name, col_value in spreadsheet_data.items():
            val_str = format_cell_value(col_value)
            for pattern in [f"{{{{{col_name}}}}}", f"{{{{ {col_name} }}}}", f"{{{col_name}}}"]:
                message = message.replace(pattern, val_str)
    
    custom_fields = assessor_data.get("custom_fields", {})
    for var_name, value in custom_fields.items():
        val_str = format_cell_value(value)
        for pattern in [f"{{{{{var_name}}}}}", f"{{{{ {var_name} }}}}", f"{{{var_name}}}"]:
            message = message.replace(pattern, val_str)
    
    clients = assessor_data.get("clients", {})
    if clients:
        clients_block = build_clients_block(clients, content_template)
        for pattern in ["{{lista_clientes}}", "{{ lista_clientes }}", "{lista_clientes}"]:
            message = message.replace(pattern, clients_block)
    
    message = re.sub(r'\{\{[^}]+\}\}', '', message)
    
    print(f"[BUILD_MSG] Final message (first 300 chars): {message[:300]}")
    
    return message


def build_clients_block(clients: dict, content_template: str = None) -> str:
    """
    Constrói o bloco de texto com as recomendações agrupadas por cliente.
    
    Se content_template for fornecido, usa esse template para cada recomendação,
    substituindo todas as variáveis disponíveis. Caso contrário, usa formato padrão.
    
    Formato padrão:
    **Cliente: 12345**
    • Saia de R$ 10.000 em PETR4 e compre R$ 10.000 em VALE3.
    
    **Cliente: 67890**
    • Saia de R$ 20.000 em ITSA4 e compre R$ 20.000 em WEGE3.
    """
    import unicodedata
    
    def normalize_var_name(name: str) -> str:
        """Remove acentos e normaliza nome de variável."""
        if not name:
            return ""
        normalized = unicodedata.normalize('NFKD', str(name))
        ascii_text = normalized.encode('ASCII', 'ignore').decode('ASCII')
        return ascii_text.lower().replace(' ', '_').replace('-', '_')
    
    def replace_vars_in_text(text: str, data: dict) -> str:
        """Substitui variáveis no texto usando os dados fornecidos."""
        if not text:
            return ""
        result = str(text)
        normalized_data = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                continue
            str_value = format_cell_value(value)
            norm_key = normalize_var_name(key)
            normalized_data[norm_key] = str_value
            normalized_data[str(key)] = str_value
        
        pattern = r'\{\{\s*([^}]+?)\s*\}\}'
        def replacer(match):
            var_name = match.group(1).strip()
            normalized_name = normalize_var_name(var_name)
            if normalized_name in normalized_data:
                return normalized_data[normalized_name]
            if var_name in normalized_data:
                return normalized_data[var_name]
            return match.group(0)
        
        result = re.sub(pattern, replacer, result)
        return result
    
    if not clients:
        print("[BUILD_CLIENTS] No clients provided!")
        return "(Nenhuma recomendação encontrada)"
    
    lines = []
    has_custom_template = bool(content_template and content_template.strip())
    
    for client_id, client_data in clients.items():
        if not client_id:
            client_id = "Sem ID"
        
        if not has_custom_template:
            lines.append(f"*Cliente: {client_id}*")
        
        if isinstance(client_data, dict):
            recommendations = client_data.get("recommendations", [])
        else:
            recommendations = client_data if isinstance(client_data, list) else []
        
        for rec in recommendations:
            if has_custom_template:
                line = replace_vars_in_text(content_template, rec)
                if line.strip():
                    lines.append(line)
            else:
                ativo_saida = rec.get('ativo_saida', 'N/A')
                valor_saida = rec.get('valor_saida', 'R$ 0,00')
                ativo_compra = rec.get('ativo_compra', 'N/A')
                valor_compra = rec.get('valor_compra', 'R$ 0,00')
                
                line = f"• Saia de {valor_saida} em {ativo_saida} e compre {valor_compra} em {ativo_compra}."
                lines.append(line)
        
        lines.append("")
    
    result = "\n".join(lines).strip()
    print(f"[BUILD_CLIENTS] Generated block with {len(lines)} lines for {len(clients)} clients")
    return result


def build_structured_message(
    header: str,
    content_template: str,
    footer: str,
    assessor_data: dict,
    data_rows: list,
    group_by_client: bool = False,
    client_id_column: str = None
) -> str:
    """
    Constrói mensagem estruturada com 3 blocos: cabeçalho, conteúdo repetível, rodapé.
    
    Args:
        header: Texto do cabeçalho (pode conter variáveis do assessor)
        content_template: Template de uma linha de conteúdo (repetido para cada linha/grupo)
        footer: Texto do rodapé (pode conter variáveis do assessor)
        assessor_data: Dados do assessor (codigo_ai, nome, email, etc.)
        data_rows: Lista de linhas de dados do arquivo
        group_by_client: Se True, agrupa linhas por cliente antes de construir
        client_id_column: Nome da coluna para agrupar por cliente
    
    Returns:
        Mensagem final consolidada
    """
    from datetime import datetime
    import unicodedata
    import re
    
    def normalize_var_name(name: str) -> str:
        """Remove acentos e normaliza nome de variável."""
        if not name:
            return ""
        normalized = unicodedata.normalize('NFKD', str(name))
        ascii_text = normalized.encode('ASCII', 'ignore').decode('ASCII')
        return ascii_text.lower().replace(' ', '_').replace('-', '_')
    
    def is_formatted_currency(value) -> bool:
        """Verifica se o valor já está formatado como moeda."""
        if not isinstance(value, str):
            return False
        return value.strip().startswith("R$")
    
    def replace_vars(text: str, vars_dict: dict) -> str:
        """Substitui variáveis no texto, normalizando acentos e priorizando valores formatados."""
        if not text:
            return ""
        result = str(text)
        normalized_data = {}
        for key, value in vars_dict.items():
            if isinstance(value, (dict, list)):
                continue
            norm_key = normalize_var_name(key)
            str_value = format_cell_value(value)
            
            if norm_key in normalized_data:
                existing = normalized_data[norm_key]
                if is_formatted_currency(existing) and not is_formatted_currency(str_value):
                    continue
            
            normalized_data[norm_key] = str_value
            normalized_data[str(key)] = str_value
        
        pattern = r'\{\{\s*([^}]+?)\s*\}\}'
        def replacer(match):
            var_name = match.group(1).strip()
            normalized_name = normalize_var_name(var_name)
            if normalized_name in normalized_data:
                return normalized_data[normalized_name]
            if var_name in normalized_data:
                return normalized_data[var_name]
            return match.group(0)
        
        result = re.sub(pattern, replacer, result)
        return result
    
    base_vars = {
        "codigo_ai": str(assessor_data.get("codigo_ai", "") or ""),
        "nome": str(assessor_data.get("nome", "") or ""),
        "nome_assessor": str(assessor_data.get("nome", "") or ""),
        "email": str(assessor_data.get("email", "") or ""),
        "telefone_whatsapp": str(assessor_data.get("telefone_whatsapp", "") or ""),
        "telefone": str(assessor_data.get("telefone", "") or ""),
        "unidade": str(assessor_data.get("unidade", "") or ""),
        "equipe": str(assessor_data.get("equipe", "") or ""),
        "broker_responsavel": str(assessor_data.get("broker_responsavel", "") or ""),
        "data_atual": datetime.now().strftime("%d/%m/%Y"),
    }
    
    header_text = replace_vars(header or "", base_vars)
    footer_text = replace_vars(footer or "", base_vars)
    
    content_lines = []
    
    if group_by_client and client_id_column and data_rows:
        grouped = {}
        for row in data_rows:
            client_id = str(row.get(client_id_column, "Sem ID") or "Sem ID")
            if client_id not in grouped:
                grouped[client_id] = []
            grouped[client_id].append(row)
        
        has_custom_template = bool(content_template and content_template.strip())
        for client_id, client_rows in grouped.items():
            if not has_custom_template:
                content_lines.append(f"**Cliente: {client_id}**")
            for row in client_rows:
                row_vars = {**base_vars, **row}
                line = replace_vars(content_template or "", row_vars)
                if line.strip():
                    content_lines.append(line)
            content_lines.append("")
    else:
        for row in data_rows:
            row_vars = {**base_vars, **row}
            line = replace_vars(content_template or "", row_vars)
            if line.strip():
                content_lines.append(line)
    
    content_block = "\n".join(content_lines).strip()
    
    message_parts = []
    if header_text.strip():
        message_parts.append(header_text.strip())
    if content_block:
        message_parts.append(content_block)
    if footer_text.strip():
        message_parts.append(footer_text.strip())
    
    final_message = "\n\n".join(message_parts)
    
    final_message = re.sub(r'\{\{[^}]+\}\}', '', final_message)
    
    return final_message


@router.post("/{campaign_id}/dispatch")
async def dispatch_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Dispara a campanha enviando mensagens via WhatsApp.
    Valida conexão Z-API antes de iniciar o envio.
    """
    from services.whatsapp_client import ZAPIClient
    
    zapi = ZAPIClient()
    if not zapi.is_configured():
        missing = []
        if not zapi.instance_id:
            missing.append("ZAPI_INSTANCE_ID")
        if not zapi.token:
            missing.append("ZAPI_TOKEN")
        if not zapi.client_token:
            missing.append("ZAPI_CLIENT_TOKEN")
        raise HTTPException(
            status_code=400, 
            detail=f"Z-API não configurada corretamente. Faltam: {', '.join(missing)}. Configure em Integrações."
        )
    
    connection_check = await zapi.check_connection()
    if not connection_check.get("success"):
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao conectar com Z-API: {connection_check.get('error', 'Erro desconhecido')}. Verifique as credenciais em Integrações."
        )
    
    if not connection_check.get("connected", False):
        raise HTTPException(
            status_code=400,
            detail="WhatsApp desconectado. Acesse Integrações e escaneie o QR Code para reconectar antes de enviar a campanha."
        )
    
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    if campaign.status == CampaignStatus.SENT.value:
        raise HTTPException(status_code=400, detail="Esta campanha já foi enviada")
    
    # Check source_type to route to correct dispatch function
    source_type = getattr(campaign, 'source_type', 'upload') or 'upload'
    
    if source_type in ["base", "base_assessores"]:
        return await dispatch_campaign_from_base(campaign, db)
    
    # Usa template customizado se existir, senao template salvo, senao mensagem padrao
    template_content = DEFAULT_TEMPLATE_CONTENT
    
    if campaign.custom_template_content:
        candidate = str(campaign.custom_template_content)
        if template_has_required_variables(candidate):
            template_content = candidate
    elif campaign.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
        if template:
            candidate = str(template.content)
            if template_has_required_variables(candidate):
                template_content = candidate
    
    try:
        column_mapping = json.loads(str(campaign.column_mapping)) if campaign.column_mapping else {}
        custom_mapping = json.loads(str(campaign.custom_fields_mapping)) if campaign.custom_fields_mapping else {}
        data = json.loads(str(campaign.processed_data)) if campaign.processed_data else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Erro nos dados da campanha")
    
    campaign.status = CampaignStatus.PROCESSING.value
    db.commit()
    
    grouped = group_recommendations_by_assessor(data, column_mapping, custom_mapping, db)
    
    from services.whatsapp_client import zapi_client
    import os
    
    zapi_configured = zapi_client.is_configured()
    sent_count = 0
    failed_count = 0
    content_line_template = campaign.message_content_template or ""
    
    for assessor_id, assessor_data in grouped.items():
        message = build_message(template_content, assessor_data, custom_mapping, content_line_template)
        phone = assessor_data.get("telefone", "")
        
        dispatch = CampaignDispatch(
            campaign_id=campaign_id,
            assessor_id=assessor_id,
            assessor_email=assessor_data.get("email_assessor", ""),
            assessor_phone=phone,
            assessor_name=assessor_data.get("nome_assessor", ""),
            message_content=message,
            status="pending"
        )
        db.add(dispatch)
        db.flush()
        
        if phone and zapi_configured:
            try:
                result = await zapi_client.send_text(phone, message, delay_typing=2)
                dispatch.api_response = json.dumps(result, ensure_ascii=False, default=str)
                
                if result.get("success"):
                    dispatch.status = "sent"
                    dispatch.sent_at = datetime.utcnow()
                    sent_count += 1
                    _persist_campaign_message(db, phone, message, campaign.name)
                else:
                    dispatch.status = "failed"
                    error_code = result.get("error_code", "UNKNOWN")
                    error_msg = result.get("error", "Erro desconhecido")
                    dispatch.error_message = error_msg
                    dispatch.error_details = translate_error_to_natural_language(error_code, error_msg, phone)
                    failed_count += 1
            except Exception as e:
                dispatch.status = "failed"
                dispatch.error_message = str(e)
                dispatch.error_details = f"Erro inesperado ao enviar mensagem: {str(e)}"
                failed_count += 1
        else:
            if not phone:
                dispatch.status = "failed"
                dispatch.error_message = "Telefone não informado"
                dispatch.error_details = f"O assessor '{assessor_data.get('nome_assessor', 'Desconhecido')}' não possui número de telefone cadastrado na planilha ou na base de assessores."
                failed_count += 1
            elif not zapi_configured:
                dispatch.status = "simulated"
                dispatch.error_details = "Disparo simulado - Z-API não configurado"
                dispatch.sent_at = datetime.utcnow()
                sent_count += 1
    
    campaign.status = CampaignStatus.SENT.value
    campaign.messages_sent = sent_count
    campaign.messages_failed = failed_count
    campaign.sent_at = datetime.utcnow()
    campaign.total_assessors = len(grouped)
    db.commit()
    
    return {
        "message": "Campanha disparada com sucesso",
        "total_assessors": len(grouped),
        "messages_sent": sent_count,
        "messages_failed": failed_count
    }


@router.get("/{campaign_id}/dispatch-stream")
async def dispatch_campaign_stream(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Dispara a campanha com streaming de progresso via SSE.
    Envia mensagens uma a uma com delay para evitar sobrecarga.
    Valida conexão Z-API antes de iniciar o envio.
    """
    from services.whatsapp_client import ZAPIClient
    
    zapi = ZAPIClient()
    if not zapi.is_configured():
        missing = []
        if not zapi.instance_id:
            missing.append("ZAPI_INSTANCE_ID")
        if not zapi.token:
            missing.append("ZAPI_TOKEN")
        if not zapi.client_token:
            missing.append("ZAPI_CLIENT_TOKEN")
        raise HTTPException(
            status_code=400, 
            detail=f"Z-API não configurada. Faltam: {', '.join(missing)}. Configure em Integrações."
        )
    
    connection_check = await zapi.check_connection()
    if not connection_check.get("success") or not connection_check.get("connected", False):
        error_msg = connection_check.get("error", "WhatsApp desconectado")
        raise HTTPException(
            status_code=400,
            detail=f"Conexão Z-API indisponível: {error_msg}. Verifique em Integrações antes de enviar."
        )
    
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    if campaign.status == CampaignStatus.SENT.value:
        raise HTTPException(status_code=400, detail="Esta campanha já foi enviada")
    
    source_type = getattr(campaign, 'source_type', 'upload') or 'upload'
    
    if source_type in ["base", "base_assessores"]:
        return await dispatch_campaign_from_base(campaign, db)
    
    header_template = campaign.message_header or ""
    content_template = campaign.message_content_template or ""
    footer_template = campaign.message_footer or ""
    use_blocks = bool(header_template.strip() or content_template.strip() or footer_template.strip())
    
    template_content = DEFAULT_TEMPLATE_CONTENT
    
    if not use_blocks:
        if campaign.custom_template_content:
            candidate = str(campaign.custom_template_content)
            if template_has_required_variables(candidate):
                template_content = candidate
        elif campaign.template_id:
            template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
            if template:
                candidate = str(template.content)
                if template_has_required_variables(candidate):
                    template_content = candidate
    
    try:
        column_mapping = json.loads(str(campaign.column_mapping)) if campaign.column_mapping else {}
        custom_mapping = json.loads(str(campaign.custom_fields_mapping)) if campaign.custom_fields_mapping else {}
        data = json.loads(str(campaign.processed_data)) if campaign.processed_data else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Erro nos dados da campanha")
    
    grouped = group_recommendations_by_assessor(data, column_mapping, custom_mapping, db)
    total_assessors = len(grouped)
    
    if total_assessors == 0:
        campaign.status = CampaignStatus.SENT.value
        campaign.messages_sent = 0
        campaign.messages_failed = 0
        campaign.sent_at = datetime.utcnow()
        campaign.total_assessors = 0
        db.commit()
        
        async def empty_generator():
            yield f"data: {json.dumps({'type': 'start', 'total': 0})}\n\n"
            yield f"data: {json.dumps({'type': 'complete', 'total': 0, 'sent_count': 0, 'failed_count': 0})}\n\n"
        
        return StreamingResponse(
            empty_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )
    
    campaign.status = CampaignStatus.PROCESSING.value
    campaign.total_assessors = total_assessors
    db.commit()
    
    attachment_url = campaign.attachment_url
    attachment_type = campaign.attachment_type
    attachment_filename = campaign.attachment_filename
    
    content_line_template = campaign.message_content_template or ""
    
    async def generate_events():
        from services.whatsapp_client import zapi_client
        from core.config import get_public_domain
        import os
        
        zapi_configured = zapi_client.is_configured()
        replit_domain = get_public_domain()
        sent_count = 0
        failed_count = 0
        current_index = 0
        cancelled = False
        
        try:
            yield f"data: {json.dumps({'type': 'start', 'total': total_assessors})}\n\n"
            
            for assessor_id, assessor_data in grouped.items():
                current_index += 1
                
                if use_blocks:
                    wrapper_parts = []
                    if header_template.strip():
                        wrapper_parts.append(header_template.strip())
                    
                    if content_template.strip() and "{{lista_clientes}}" in content_template:
                        wrapper_parts.append(content_template.strip())
                    else:
                        wrapper_parts.append("{{lista_clientes}}")
                    
                    if footer_template.strip():
                        wrapper_parts.append(footer_template.strip())
                    
                    wrapper_template = "\n\n".join(wrapper_parts)
                    message = build_message(wrapper_template, assessor_data, custom_mapping, content_line_template)
                else:
                    message = build_message(template_content, assessor_data, custom_mapping, content_line_template)
                
                phone = assessor_data.get("telefone", "")
                assessor_name = assessor_data.get("nome_assessor", "")
                
                db_session = SessionLocal()
                try:
                    dispatch = CampaignDispatch(
                        campaign_id=campaign_id,
                        assessor_id=assessor_id,
                        assessor_email=assessor_data.get("email_assessor", ""),
                        assessor_phone=phone,
                        assessor_name=assessor_name,
                        message_content=message,
                        status="pending"
                    )
                    db_session.add(dispatch)
                    db_session.flush()
                    
                    status = "pending"
                    error_msg = ""
                    attempt = 1
                    
                    if phone and zapi_configured:
                        while attempt <= MAX_RETRY_ATTEMPTS:
                            try:
                                if attachment_url and attachment_type:
                                    full_attachment_url = f"https://{replit_domain}{attachment_url}" if replit_domain and attachment_url.startswith('/') else attachment_url
                                    if attachment_type == "image":
                                        result = await zapi_client.send_image(phone, full_attachment_url, message)
                                    elif attachment_type == "video":
                                        result = await zapi_client.send_video(phone, full_attachment_url, message)
                                    elif attachment_type == "audio":
                                        result = await zapi_client.send_audio(phone, full_attachment_url)
                                    else:
                                        result = await zapi_client.send_document(phone, full_attachment_url, attachment_filename or "", message)
                                else:
                                    result = await zapi_client.send_text(phone, message, delay_typing=2)
                                dispatch.api_response = json.dumps(result, ensure_ascii=False, default=str)
                                
                                if result.get("success"):
                                    dispatch.status = "sent"
                                    dispatch.sent_at = datetime.utcnow()
                                    sent_count += 1
                                    status = "sent"
                                    _persist_campaign_message(db_session, phone, message, campaign.name)
                                    break
                                else:
                                    error_code = result.get("error_code", "UNKNOWN")
                                    error_msg = result.get("error", "Erro desconhecido")
                                    
                                    is_retryable = (
                                        error_code.startswith("HTTP_5") or 
                                        "500" in error_code or
                                        "502" in error_code or
                                        "503" in error_code or
                                        error_code in ["TIMEOUT", "CONNECTION_ERROR", "HTTP_ERROR"]
                                    )
                                    
                                    if is_retryable and attempt < MAX_RETRY_ATTEMPTS:
                                        retry_data = {
                                            'type': 'retry',
                                            'current': current_index,
                                            'total': total_assessors,
                                            'assessor_name': assessor_name,
                                            'attempt': attempt,
                                            'max_attempts': MAX_RETRY_ATTEMPTS,
                                            'error': error_msg
                                        }
                                        yield f"data: {json.dumps(retry_data, ensure_ascii=False)}\n\n"
                                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                                        attempt += 1
                                        continue
                                    else:
                                        dispatch.status = "failed"
                                        dispatch.error_message = error_msg
                                        dispatch.error_details = translate_error_to_natural_language(error_code, error_msg, phone)
                                        if attempt > 1:
                                            dispatch.error_details += f" (após {attempt} tentativas)"
                                        failed_count += 1
                                        status = "failed"
                                        break
                            except Exception as e:
                                error_msg = str(e)
                                
                                if attempt < MAX_RETRY_ATTEMPTS:
                                    retry_data = {
                                        'type': 'retry',
                                        'current': current_index,
                                        'total': total_assessors,
                                        'assessor_name': assessor_name,
                                        'attempt': attempt,
                                        'max_attempts': MAX_RETRY_ATTEMPTS,
                                        'error': error_msg
                                    }
                                    yield f"data: {json.dumps(retry_data, ensure_ascii=False)}\n\n"
                                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                                    attempt += 1
                                    continue
                                else:
                                    dispatch.status = "failed"
                                    dispatch.error_message = error_msg
                                    dispatch.error_details = f"Erro inesperado ao enviar mensagem: {error_msg}"
                                    if attempt > 1:
                                        dispatch.error_details += f" (após {attempt} tentativas)"
                                    failed_count += 1
                                    status = "failed"
                                    break
                    else:
                        if not phone:
                            dispatch.status = "failed"
                            dispatch.error_message = "Telefone não informado"
                            dispatch.error_details = f"O assessor '{assessor_name}' não possui número de telefone cadastrado."
                            failed_count += 1
                            status = "failed"
                            error_msg = "Telefone não informado"
                        elif not zapi_configured:
                            dispatch.status = "simulated"
                            dispatch.error_details = "Disparo simulado - Z-API não configurado"
                            dispatch.sent_at = datetime.utcnow()
                            sent_count += 1
                            status = "simulated"
                    
                    db_session.commit()
                    
                    percent = round((current_index / total_assessors) * 100, 1)
                    progress_data = {
                        'type': 'progress',
                        'current': current_index,
                        'total': total_assessors,
                        'percent': percent,
                        'assessor_name': assessor_name,
                        'assessor_phone': phone,
                        'status': status,
                        'error': error_msg,
                        'sent_count': sent_count,
                        'failed_count': failed_count,
                        'attempts_made': attempt
                    }
                    yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"
                    
                finally:
                    db_session.close()
                
                if current_index < total_assessors:
                    delay = get_random_dispatch_delay()
                    await asyncio.sleep(delay)
        
        except asyncio.CancelledError:
            cancelled = True
        finally:
            db_final = SessionLocal()
            try:
                campaign_final = db_final.query(Campaign).filter(Campaign.id == campaign_id).first()
                if campaign_final:
                    campaign_final.status = CampaignStatus.SENT.value
                    campaign_final.messages_sent = sent_count
                    campaign_final.messages_failed = failed_count
                    campaign_final.sent_at = datetime.utcnow()
                    db_final.commit()
            finally:
                db_final.close()
        
        if not cancelled:
            complete_data = {
                'type': 'complete',
                'total': total_assessors,
                'sent_count': sent_count,
                'failed_count': failed_count
            }
            yield f"data: {json.dumps(complete_data)}\n\n"
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


def replace_variables_generic(text: str, variables: dict) -> str:
    """
    Substitui variáveis no texto de forma genérica.
    Suporta formatos: {{var}}, {{ var }}, {var}
    Normaliza nomes de variáveis (remove acentos, lowercase, underscores).
    """
    if not text:
        return ""
    
    def normalize_var_name(name: str) -> str:
        import unicodedata
        normalized = unicodedata.normalize('NFKD', name.lower())
        normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
        normalized = normalized.replace(' ', '_').replace('-', '_')
        return normalized
    
    normalized_vars = {}
    for key, value in variables.items():
        str_value = format_cell_value(value)
        normalized_vars[key] = str_value
        normalized_vars[normalize_var_name(key)] = str_value
    
    result = text
    
    pattern = r'\{\{\s*([^}]+?)\s*\}\}'
    def replacer(match):
        var_name = match.group(1).strip()
        normalized_name = normalize_var_name(var_name)
        if var_name in normalized_vars:
            return normalized_vars[var_name]
        if normalized_name in normalized_vars:
            return normalized_vars[normalized_name]
        return match.group(0)
    
    result = re.sub(pattern, replacer, result)
    
    pattern_simple = r'\{([^{}]+)\}'
    def replacer_simple(match):
        var_name = match.group(1).strip()
        normalized_name = normalize_var_name(var_name)
        if var_name in normalized_vars:
            return normalized_vars[var_name]
        if normalized_name in normalized_vars:
            return normalized_vars[normalized_name]
        return match.group(0)
    
    result = re.sub(pattern_simple, replacer_simple, result)
    
    return result


def build_assessor_variables(assessor: dict) -> dict:
    """
    Constrói dicionário completo de variáveis a partir dos dados do assessor.
    Inclui aliases comuns para facilitar o uso de variáveis.
    """
    variables = {}
    
    print(f"[BUILD_VARS] Input assessor keys: {list(assessor.keys())}")
    print(f"[BUILD_VARS] nome value: {assessor.get('nome', 'NOT_FOUND')}")
    
    for key, value in assessor.items():
        str_value = format_cell_value(value)
        variables[key] = str_value
    
    nome = assessor.get("nome", "")
    primeiro_nome = str(nome).split()[0] if nome else ""
    variables["primeiro_nome"] = primeiro_nome
    variables["nome_assessor"] = str(nome) if nome else ""
    variables["assessor"] = str(nome) if nome else ""
    
    print(f"[BUILD_VARS] primeiro_nome calculated: '{primeiro_nome}' from nome: '{nome}'")
    
    telefone = assessor.get("telefone_whatsapp", "") or assessor.get("telefone", "")
    variables["telefone"] = str(telefone) if telefone else ""
    variables["whatsapp"] = str(telefone) if telefone else ""
    variables["celular"] = str(telefone) if telefone else ""
    
    email = assessor.get("email", "")
    variables["email_assessor"] = str(email) if email else ""
    
    codigo = assessor.get("codigo_ai", "")
    variables["codigo"] = str(codigo) if codigo else ""
    variables["codigo_assessor"] = str(codigo) if codigo else ""
    
    unidade = assessor.get("unidade", "")
    variables["escritorio"] = str(unidade) if unidade else ""
    
    equipe = assessor.get("equipe", "")
    variables["time"] = str(equipe) if equipe else ""
    
    broker = assessor.get("broker_responsavel", "")
    variables["broker"] = str(broker) if broker else ""
    
    variables["data_atual"] = datetime.now().strftime("%d/%m/%Y")
    variables["data"] = datetime.now().strftime("%d/%m/%Y")
    
    variables["lista_clientes"] = "(Campanha informativa)"
    
    return variables


async def dispatch_campaign_from_base(campaign, db: Session):
    """
    Dispara campanha baseada em assessores selecionados da base.
    Envia mensagem usando os blocos de header, content e footer definidos na campanha.
    """
    from services.whatsapp_client import zapi_client
    import os
    
    header_template = campaign.message_header or ""
    content_template = campaign.message_content_template or ""
    footer_template = campaign.message_footer or ""
    
    if not header_template and not content_template and not footer_template:
        if campaign.custom_template_content:
            content_template = str(campaign.custom_template_content)
        elif campaign.template_id:
            template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
            if template:
                content_template = str(template.content)
        else:
            content_template = "Ola, {{nome_assessor}}!"
    
    try:
        data = json.loads(str(campaign.processed_data)) if campaign.processed_data else []
    except json.JSONDecodeError:
        data = []
    
    total_assessors = len(data)
    
    if total_assessors == 0:
        campaign.status = CampaignStatus.SENT.value
        campaign.messages_sent = 0
        campaign.messages_failed = 0
        campaign.sent_at = datetime.utcnow()
        campaign.total_assessors = 0
        db.commit()
        
        async def empty_generator():
            yield f"data: {json.dumps({'type': 'start', 'total': 0})}\n\n"
            yield f"data: {json.dumps({'type': 'complete', 'total': 0, 'sent_count': 0, 'failed_count': 0})}\n\n"
        
        return StreamingResponse(
            empty_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )
    
    campaign.status = CampaignStatus.PROCESSING.value
    campaign.total_assessors = total_assessors
    db.commit()
    
    attachment_url = campaign.attachment_url
    attachment_type = campaign.attachment_type
    attachment_filename = campaign.attachment_filename
    
    async def generate_events():
        from core.config import get_public_domain
        zapi_configured = zapi_client.is_configured()
        replit_domain = get_public_domain()
        sent_count = 0
        failed_count = 0
        current_index = 0
        cancelled = False
        
        try:
            yield f"data: {json.dumps({'type': 'start', 'total': total_assessors})}\n\n"
            
            for assessor in data:
                db_check = SessionLocal()
                try:
                    campaign_check = db_check.query(Campaign).filter(Campaign.id == campaign.id).first()
                    should_cancel = (
                        cancelled_campaigns.get(campaign.id, False) or 
                        (campaign_check and campaign_check.status in ["cancelling", "cancelled"])
                    )
                    if should_cancel:
                        cancelled = True
                        cancel_data = {
                            'type': 'cancelled',
                            'current': current_index,
                            'total': total_assessors,
                            'sent_count': sent_count,
                            'failed_count': failed_count,
                            'message': 'Envio cancelado pelo usuário'
                        }
                        yield f"data: {json.dumps(cancel_data, ensure_ascii=False)}\n\n"
                        break
                finally:
                    db_check.close()
                
                current_index += 1
                assessor_name = assessor.get("nome", "")
                phone = assessor.get("telefone_whatsapp", "") or assessor.get("telefone", "")
                
                variables = build_assessor_variables(assessor)
                
                message_parts = []
                
                header_rendered = replace_variables_generic(header_template, variables)
                if header_rendered.strip():
                    message_parts.append(header_rendered.strip())
                
                content_rendered = replace_variables_generic(content_template, variables)
                if content_rendered.strip():
                    message_parts.append(content_rendered.strip())
                
                footer_rendered = replace_variables_generic(footer_template, variables)
                if footer_rendered.strip():
                    message_parts.append(footer_rendered.strip())
                
                message = "\n\n".join(message_parts)
                
                leftover_pattern = r'\{\{[^}]+\}\}'
                message = re.sub(leftover_pattern, '', message)
                
                db_session = SessionLocal()
                try:
                    dispatch = CampaignDispatch(
                        campaign_id=campaign.id,
                        assessor_id=str(assessor.get("id", "")),
                        assessor_email=assessor.get("email", ""),
                        assessor_phone=phone,
                        assessor_name=assessor_name,
                        message_content=message,
                        status="pending"
                    )
                    db_session.add(dispatch)
                    db_session.flush()
                    
                    status = "pending"
                    error_msg = ""
                    attempt = 1
                    
                    if phone and zapi_configured:
                        while attempt <= MAX_RETRY_ATTEMPTS:
                            try:
                                if attachment_url and attachment_type:
                                    full_attachment_url = f"https://{replit_domain}{attachment_url}" if replit_domain and attachment_url.startswith('/') else attachment_url
                                    if attachment_type == "image":
                                        result = await zapi_client.send_image(phone, full_attachment_url, message)
                                    elif attachment_type == "video":
                                        result = await zapi_client.send_video(phone, full_attachment_url, message)
                                    elif attachment_type == "audio":
                                        result = await zapi_client.send_audio(phone, full_attachment_url)
                                    else:
                                        result = await zapi_client.send_document(phone, full_attachment_url, attachment_filename or "", message)
                                else:
                                    result = await zapi_client.send_text(phone, message, delay_typing=2)
                                dispatch.api_response = json.dumps(result, ensure_ascii=False, default=str)
                                
                                if result.get("success"):
                                    dispatch.status = "sent"
                                    dispatch.sent_at = datetime.utcnow()
                                    sent_count += 1
                                    status = "sent"
                                    _persist_campaign_message(db_session, phone, message, campaign.name)
                                    break
                                else:
                                    error_code = result.get("error_code", "UNKNOWN")
                                    error_msg = result.get("error", "Erro desconhecido")
                                    
                                    is_retryable = (
                                        error_code.startswith("HTTP_5") or 
                                        "500" in error_code or
                                        "502" in error_code or
                                        "503" in error_code or
                                        error_code in ["TIMEOUT", "CONNECTION_ERROR", "HTTP_ERROR"]
                                    )
                                    
                                    if is_retryable and attempt < MAX_RETRY_ATTEMPTS:
                                        await asyncio.sleep(RETRY_DELAY_SECONDS)
                                        attempt += 1
                                        continue
                                    else:
                                        dispatch.status = "failed"
                                        dispatch.error_message = error_msg
                                        dispatch.error_details = translate_error_to_natural_language(error_code, error_msg, phone)
                                        failed_count += 1
                                        status = "failed"
                                        break
                            except Exception as e:
                                error_msg = str(e)
                                if attempt < MAX_RETRY_ATTEMPTS:
                                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                                    attempt += 1
                                else:
                                    dispatch.status = "failed"
                                    dispatch.error_message = error_msg
                                    dispatch.error_details = f"Erro de conexao: {error_msg}"
                                    failed_count += 1
                                    status = "failed"
                                    break
                    else:
                        if not phone:
                            dispatch.status = "failed"
                            dispatch.error_message = "Telefone não informado"
                            dispatch.error_details = "O assessor não possui telefone WhatsApp cadastrado"
                            failed_count += 1
                            status = "failed"
                            error_msg = "Telefone não informado"
                        elif not zapi_configured:
                            dispatch.status = "simulated"
                            dispatch.error_details = "Disparo simulado - Z-API não configurado"
                            dispatch.sent_at = datetime.utcnow()
                            sent_count += 1
                            status = "simulated"
                    
                    db_session.commit()
                    
                    percent = round((current_index / total_assessors) * 100, 1)
                    progress_data = {
                        'type': 'progress',
                        'current': current_index,
                        'total': total_assessors,
                        'percent': percent,
                        'assessor_name': assessor_name,
                        'assessor_phone': phone,
                        'status': status,
                        'error': error_msg,
                        'sent_count': sent_count,
                        'failed_count': failed_count,
                        'attempts_made': attempt
                    }
                    yield f"data: {json.dumps(progress_data, ensure_ascii=False)}\n\n"
                    
                finally:
                    db_session.close()
                
                if current_index < total_assessors:
                    delay = get_random_dispatch_delay()
                    await asyncio.sleep(delay)
        
        except asyncio.CancelledError:
            cancelled = True
        finally:
            if campaign.id in cancelled_campaigns:
                del cancelled_campaigns[campaign.id]
            
            db_final = SessionLocal()
            try:
                campaign_final = db_final.query(Campaign).filter(Campaign.id == campaign.id).first()
                if campaign_final:
                    if cancelled or campaign_final.status == "cancelling":
                        campaign_final.status = "cancelled"
                    elif campaign_final.status in [CampaignStatus.PROCESSING.value, "processing", "sending"]:
                        campaign_final.status = CampaignStatus.SENT.value
                    campaign_final.messages_sent = sent_count
                    campaign_final.messages_failed = failed_count
                    campaign_final.sent_at = datetime.utcnow()
                    db_final.commit()
            finally:
                db_final.close()
        
        if not cancelled:
            complete_data = {
                'type': 'complete',
                'total': total_assessors,
                'sent_count': sent_count,
                'failed_count': failed_count
            }
            yield f"data: {json.dumps(complete_data)}\n\n"
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/{campaign_id}/cancel")
async def cancel_campaign_dispatch(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Cancela o disparo de uma campanha em andamento."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    if campaign.status not in [CampaignStatus.PROCESSING.value, "processing", "sending"]:
        raise HTTPException(status_code=409, detail="A campanha não está em andamento")
    
    cancelled_campaigns[campaign_id] = True
    
    campaign.status = "cancelling"
    db.commit()
    
    return {"success": True, "message": "Solicitação de cancelamento enviada"}


@router.get("/")
async def list_campaigns(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Lista todas as campanhas com paginação."""
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).offset(skip).limit(limit).all()
    
    return [
        {
            "id": c.id,
            "name": c.name,
            "status": c.status,
            "original_filename": c.original_filename,
            "total_assessors": c.total_assessors,
            "total_recommendations": c.total_recommendations,
            "messages_sent": c.messages_sent,
            "messages_failed": c.messages_failed,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "sent_at": c.sent_at.isoformat() if c.sent_at else None,
            "template_name": c.template.name if c.template else None
        }
        for c in campaigns
    ]


class CampaignStructureCreate(BaseModel):
    name: str
    ticker: Optional[str] = None
    structure_type: str
    campaign_slug: str
    key_data: Optional[dict] = None
    diagram_filename: Optional[str] = None
    material_id: Optional[int] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None


class CampaignStructureUpdate(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    structure_type: Optional[str] = None
    campaign_slug: Optional[str] = None
    key_data: Optional[dict] = None
    diagram_filename: Optional[str] = None
    material_id: Optional[int] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_active: Optional[bool] = None


def _structure_to_dict(s: CampaignStructure) -> dict:
    import json as _json
    return {
        "id": s.id,
        "name": s.name,
        "ticker": s.ticker,
        "structure_type": s.structure_type,
        "campaign_slug": s.campaign_slug,
        "key_data": _json.loads(s.key_data) if s.key_data else {},
        "diagram_filename": s.diagram_filename,
        "material_id": s.material_id,
        "valid_from": s.valid_from.isoformat() if s.valid_from else None,
        "valid_until": s.valid_until.isoformat() if s.valid_until else None,
        "is_active": s.is_active == 1,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("/structures")
async def list_campaign_structures(
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    query = db.query(CampaignStructure)
    if active_only:
        now = datetime.utcnow()
        query = query.filter(
            CampaignStructure.is_active == 1,
            (CampaignStructure.valid_from.is_(None)) | (CampaignStructure.valid_from <= now),
            (CampaignStructure.valid_until.is_(None)) | (CampaignStructure.valid_until >= now),
        )
    structures = query.order_by(CampaignStructure.created_at.desc()).all()
    return {"structures": [_structure_to_dict(s) for s in structures]}


@router.get("/active-structures")
async def get_active_campaign_structures(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    now = datetime.utcnow()
    structures = db.query(CampaignStructure).filter(
        CampaignStructure.is_active == 1,
        (CampaignStructure.valid_from.is_(None)) | (CampaignStructure.valid_from <= now),
        (CampaignStructure.valid_until.is_(None)) | (CampaignStructure.valid_until >= now),
    ).order_by(CampaignStructure.name).all()
    return {"structures": [_structure_to_dict(s) for s in structures]}


@router.get("/derivative-slugs")
async def list_derivative_slugs(
    current_user: User = Depends(require_admin_or_gestao())
):
    from scripts.xpi_derivatives.derivatives_dataset import get_all_structures
    structures = get_all_structures()
    return {
        "slugs": [
            {"slug": s["slug"], "name": s["name"], "tab": s["tab"]}
            for s in structures
        ]
    }


@router.post("/structures")
async def create_campaign_structure(
    data: CampaignStructureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    existing = db.query(CampaignStructure).filter(
        CampaignStructure.campaign_slug == data.campaign_slug
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Já existe uma estrutura com esse slug")

    structure = CampaignStructure(
        name=data.name,
        ticker=data.ticker,
        structure_type=data.structure_type,
        campaign_slug=data.campaign_slug,
        key_data=json.dumps(data.key_data) if data.key_data else "{}",
        diagram_filename=data.diagram_filename,
        material_id=data.material_id,
        valid_from=datetime.fromisoformat(data.valid_from) if data.valid_from else None,
        valid_until=datetime.fromisoformat(data.valid_until) if data.valid_until else None,
        is_active=1,
        created_by=int(current_user.id),
    )
    db.add(structure)
    db.commit()
    db.refresh(structure)
    return {"success": True, "structure": _structure_to_dict(structure)}


@router.get("/structures/{structure_id}")
async def get_campaign_structure(
    structure_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    structure = db.query(CampaignStructure).filter(CampaignStructure.id == structure_id).first()
    if not structure:
        raise HTTPException(status_code=404, detail="Estrutura não encontrada")
    return _structure_to_dict(structure)


@router.put("/structures/{structure_id}")
async def update_campaign_structure(
    structure_id: int,
    data: CampaignStructureUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    structure = db.query(CampaignStructure).filter(CampaignStructure.id == structure_id).first()
    if not structure:
        raise HTTPException(status_code=404, detail="Estrutura não encontrada")

    if data.name is not None:
        structure.name = data.name
    if data.ticker is not None:
        structure.ticker = data.ticker
    if data.structure_type is not None:
        structure.structure_type = data.structure_type
    if data.campaign_slug is not None:
        existing = db.query(CampaignStructure).filter(
            CampaignStructure.campaign_slug == data.campaign_slug,
            CampaignStructure.id != structure_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Slug já em uso")
        structure.campaign_slug = data.campaign_slug
    if data.key_data is not None:
        structure.key_data = json.dumps(data.key_data)
    if data.diagram_filename is not None:
        structure.diagram_filename = data.diagram_filename
    if data.material_id is not None:
        structure.material_id = data.material_id
    if data.valid_from is not None:
        structure.valid_from = datetime.fromisoformat(data.valid_from) if data.valid_from else None
    if data.valid_until is not None:
        structure.valid_until = datetime.fromisoformat(data.valid_until) if data.valid_until else None
    if data.is_active is not None:
        structure.is_active = 1 if data.is_active else 0

    db.commit()
    db.refresh(structure)
    return {"success": True, "structure": _structure_to_dict(structure)}


@router.delete("/structures/{structure_id}")
async def delete_campaign_structure(
    structure_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    structure = db.query(CampaignStructure).filter(CampaignStructure.id == structure_id).first()
    if not structure:
        raise HTTPException(status_code=404, detail="Estrutura não encontrada")

    structure.is_active = 0
    db.commit()
    return {"success": True, "message": "Estrutura desativada"}


@router.post("/structures/{structure_id}/diagram")
async def upload_campaign_diagram(
    structure_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    structure = db.query(CampaignStructure).filter(CampaignStructure.id == structure_id).first()
    if not structure:
        raise HTTPException(status_code=404, detail="Estrutura não encontrada")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome do arquivo inválido")

    import os
    slug = structure.campaign_slug
    ext = os.path.splitext(file.filename)[1].lower() or ".png"
    diagram_name = f"{slug}{ext}"
    diagram_dir = os.path.join("static", "derivatives_diagrams")
    os.makedirs(diagram_dir, exist_ok=True)
    diagram_path = os.path.join(diagram_dir, diagram_name)

    contents = await file.read()
    with open(diagram_path, "wb") as f:
        f.write(contents)

    structure.diagram_filename = diagram_name
    db.commit()

    return {
        "success": True,
        "diagram_filename": diagram_name,
        "message": f"Diagrama salvo em {diagram_path}"
    }


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Busca uma campanha por ID."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    dispatches = db.query(CampaignDispatch).filter(
        CampaignDispatch.campaign_id == campaign_id
    ).all()
    
    try:
        column_mapping = json.loads(str(campaign.column_mapping)) if campaign.column_mapping else {}
        custom_fields_mapping = json.loads(str(campaign.custom_fields_mapping)) if campaign.custom_fields_mapping else {}
        processed_data = json.loads(str(campaign.processed_data)) if campaign.processed_data else []
    except json.JSONDecodeError:
        column_mapping = {}
        custom_fields_mapping = {}
        processed_data = []
    
    file_columns = []
    if processed_data and len(processed_data) > 0:
        file_columns = list(processed_data[0].keys())
    
    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "template_id": campaign.template_id,
        "template_name": campaign.template.name if campaign.template else None,
        "custom_template_content": campaign.custom_template_content,
        "original_filename": campaign.original_filename,
        "column_mapping": column_mapping,
        "custom_fields_mapping": custom_fields_mapping,
        "file_columns": file_columns,
        "total_assessors": campaign.total_assessors,
        "total_recommendations": campaign.total_recommendations,
        "messages_sent": campaign.messages_sent,
        "messages_failed": campaign.messages_failed,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "sent_at": campaign.sent_at.isoformat() if campaign.sent_at else None,
        "has_data": len(processed_data) > 0,
        "dispatches": [
            {
                "assessor_id": d.assessor_id,
                "assessor_name": d.assessor_name,
                "assessor_phone": d.assessor_phone,
                "status": d.status,
                "error_message": d.error_message,
                "sent_at": d.sent_at.isoformat() if d.sent_at else None
            }
            for d in dispatches
        ]
    }


@router.get("/{campaign_id}/failures")
async def get_campaign_failures(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Retorna análise detalhada das falhas de uma campanha.
    Agrupa falhas por tipo e fornece descrição em linguagem natural.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    failed_dispatches = db.query(CampaignDispatch).filter(
        CampaignDispatch.campaign_id == campaign_id,
        CampaignDispatch.status == "failed"
    ).all()
    
    if not failed_dispatches:
        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.name,
            "total_failures": 0,
            "failures": [],
            "summary": "Nenhuma falha registrada nesta campanha."
        }
    
    failures = []
    error_categories = {}
    
    for d in failed_dispatches:
        error_msg = d.error_message or "Erro desconhecido"
        error_detail = d.error_details or translate_error_to_natural_language("UNKNOWN", error_msg, d.assessor_phone or "")
        
        category = "Outro"
        if "timeout" in error_msg.lower():
            category = "Timeout"
        elif "connection" in error_msg.lower() or "conectar" in error_msg.lower():
            category = "Conexao"
        elif "401" in error_msg or "403" in error_msg or "credenciais" in error_detail.lower():
            category = "Autenticacao"
        elif "telefone" in error_msg.lower() or "phone" in error_msg.lower() or "numero" in error_msg.lower():
            category = "Numero Invalido"
        elif "session" in error_msg.lower() or "sessao" in error_detail.lower():
            category = "Sessao WhatsApp"
        
        if category not in error_categories:
            error_categories[category] = 0
        error_categories[category] += 1
        
        api_response_parsed = None
        if d.api_response:
            try:
                api_response_parsed = json.loads(d.api_response)
            except json.JSONDecodeError:
                api_response_parsed = d.api_response
        
        failures.append({
            "assessor_name": d.assessor_name or "Desconhecido",
            "assessor_phone": d.assessor_phone or "Nao informado",
            "error_message": error_msg,
            "error_details": error_detail,
            "category": category,
            "api_response": api_response_parsed
        })
    
    summary_parts = []
    for cat, count in sorted(error_categories.items(), key=lambda x: -x[1]):
        if cat == "Conexao":
            summary_parts.append(f"{count} falha(s) de conexao com o servidor Z-API")
        elif cat == "Autenticacao":
            summary_parts.append(f"{count} falha(s) de autenticacao (chave de API)")
        elif cat == "Numero Invalido":
            summary_parts.append(f"{count} numero(s) de telefone invalido(s) ou ausente(s)")
        elif cat == "Sessao WhatsApp":
            summary_parts.append(f"{count} problema(s) com a sessao do WhatsApp")
        elif cat == "Timeout":
            summary_parts.append(f"{count} timeout(s) - servidor demorou para responder")
        else:
            summary_parts.append(f"{count} outro(s) erro(s)")
    
    summary = "Resumo das falhas: " + "; ".join(summary_parts) + "." if summary_parts else "Nenhuma falha categorizada."
    
    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.name,
        "total_failures": len(failed_dispatches),
        "categories": error_categories,
        "summary": summary,
        "failures": failures
    }


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Remove uma campanha e seus dispatches."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    if campaign.status == CampaignStatus.PROCESSING.value:
        raise HTTPException(status_code=400, detail="Não é possível excluir uma campanha em processamento")
    
    db.delete(campaign)
    db.commit()
    
    return {"message": "Campanha excluída com sucesso"}


@router.get("/{campaign_id}/debug")
async def debug_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Endpoint de diagnóstico para verificar dados da campanha.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    template_content = DEFAULT_TEMPLATE_CONTENT
    template_source = "default"
    
    if campaign.custom_template_content:
        template_content = str(campaign.custom_template_content)
        template_source = "custom"
    elif campaign.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
        if template:
            template_content = str(template.content)
            template_source = f"template_{campaign.template_id}"
    
    try:
        column_mapping = json.loads(str(campaign.column_mapping)) if campaign.column_mapping else {}
        custom_mapping = json.loads(str(campaign.custom_fields_mapping)) if campaign.custom_fields_mapping else {}
        data = json.loads(str(campaign.processed_data)) if campaign.processed_data else []
    except json.JSONDecodeError as e:
        return {"error": f"JSON decode error: {str(e)}"}
    
    grouped = {}
    if column_mapping and data:
        grouped = group_recommendations_by_assessor(data, column_mapping, custom_mapping, db)
    
    content_line_template = campaign.message_content_template or ""
    sample_message = ""
    if grouped:
        first_key = list(grouped.keys())[0]
        sample_message = build_message(template_content, grouped[first_key], custom_mapping, content_line_template)
    
    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.name,
        "status": campaign.status,
        "template_source": template_source,
        "template_content_preview": template_content[:500] if template_content else None,
        "template_has_nome_assessor": "{{nome_assessor}}" in template_content if template_content else False,
        "template_has_lista_clientes": "{{lista_clientes}}" in template_content if template_content else False,
        "column_mapping": column_mapping,
        "custom_mapping": custom_mapping,
        "data_rows_count": len(data),
        "data_first_row": data[0] if data else None,
        "data_first_row_keys": list(data[0].keys()) if data else [],
        "grouped_assessors_count": len(grouped),
        "grouped_keys": list(grouped.keys())[:5],
        "first_assessor_data": grouped[list(grouped.keys())[0]] if grouped else None,
        "sample_message_preview": sample_message[:500] if sample_message else None
    }


def _persist_campaign_message(db_session: Session, phone: str, message: str, campaign_name: str = ""):
    if not phone or not message:
        return
    try:
        from database.models import WhatsAppMessage, MessageDirection, MessageType, SenderType, Conversation
        clean_phone = ''.join(filter(str.isdigit, phone))
        if not clean_phone:
            return

        conversation = db_session.query(Conversation).filter(
            Conversation.phone == clean_phone
        ).first()
        if not conversation:
            conversation = Conversation(phone=clean_phone)
            db_session.add(conversation)
            db_session.flush()

        tag = f"[Campanha: {campaign_name}] " if campaign_name else ""
        record = WhatsAppMessage(
            chat_id=clean_phone,
            phone=clean_phone,
            direction=MessageDirection.OUTBOUND.value,
            message_type=MessageType.TEXT.value,
            from_me=True,
            body=f"{tag}{message}",
            ai_response=None,
            ai_intent="campaign_dispatch",
            sender_type=SenderType.BOT.value,
            conversation_id=conversation.id,
        )
        db_session.add(record)
        db_session.commit()
        print(f"[CAMPAIGN_MSG] Mensagem de campanha salva no histórico de {clean_phone}")
    except Exception as e:
        print(f"[CAMPAIGN_MSG] Erro ao salvar mensagem de campanha: {e}")
        try:
            db_session.rollback()
        except Exception:
            pass
