"""
Endpoints para Campanhas Ativas e Templates de Mensagem.
Permite criar campanhas de disparo em massa para assessores.
"""
import json
import io
import re
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database.database import get_db
from database.models import MessageTemplate, Campaign, CampaignDispatch, CampaignStatus, Assessor
from api.endpoints.auth import require_role
from database.models import User

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class TemplateCreate(BaseModel):
    name: str
    content: str
    description: Optional[str] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ColumnMapping(BaseModel):
    assessor_id: str
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
        "created_at": template.created_at.isoformat() if template.created_at else None
    }


@router.post("/templates")
async def create_template(
    data: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Cria um novo template de mensagem."""
    template = MessageTemplate(
        name=data.name,
        content=data.content,
        description=data.description,
        created_by=int(current_user.id),
        is_active=1
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    
    return {
        "id": template.id,
        "name": template.name,
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
    if data.description is not None:
        template.description = data.description
    if data.is_active is not None:
        template.is_active = 1 if data.is_active else 0
    
    db.commit()
    db.refresh(template)
    
    return {"message": "Template atualizado com sucesso"}


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


@router.put("/{campaign_id}/mapping")
async def update_campaign_mapping(
    campaign_id: int,
    column_mapping: dict,
    custom_fields: Optional[List[dict]] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Atualiza o mapeamento de colunas de uma campanha."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    required_fields = ["assessor_id", "client_id", "ativo_saida", "valor_saida", "ativo_compra", "valor_compra"]
    missing = [f for f in required_fields if f not in column_mapping or not column_mapping[f]]
    if missing:
        raise HTTPException(status_code=400, detail=f"Campos obrigatórios faltando: {', '.join(missing)}")
    
    campaign.column_mapping = json.dumps(column_mapping)
    
    if custom_fields:
        custom_mapping = {cf["column_name"]: cf["variable_name"] for cf in custom_fields}
        campaign.custom_fields_mapping = json.dumps(custom_mapping)
    
    db.commit()
    
    return {"message": "Mapeamento atualizado com sucesso"}


@router.put("/{campaign_id}/template")
async def set_campaign_template(
    campaign_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """Define o template de mensagem para a campanha."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    template = db.query(MessageTemplate).filter(MessageTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    
    campaign.template_id = template_id
    db.commit()
    
    return {"message": "Template definido com sucesso"}


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
    
    if not campaign.template_id:
        raise HTTPException(status_code=400, detail="Template não definido para esta campanha")
    
    template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
    if not template:
        raise HTTPException(status_code=400, detail="Template não encontrado")
    
    try:
        column_mapping = json.loads(campaign.column_mapping) if campaign.column_mapping else {}
        custom_mapping = json.loads(campaign.custom_fields_mapping) if campaign.custom_fields_mapping else {}
        data = json.loads(campaign.processed_data) if campaign.processed_data else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Erro nos dados da campanha")
    
    if not column_mapping:
        raise HTTPException(status_code=400, detail="Mapeamento de colunas não definido")
    
    grouped = group_recommendations_by_assessor(data, column_mapping, custom_mapping, db)
    
    campaign.total_assessors = len(grouped)
    db.commit()
    
    messages = []
    for assessor_id, assessor_data in grouped.items():
        message = build_message(template.content, assessor_data, custom_mapping)
        messages.append({
            "assessor_id": assessor_id,
            "assessor_name": assessor_data.get("nome_assessor", ""),
            "assessor_phone": assessor_data.get("telefone", ""),
            "client_count": len(assessor_data.get("clients", {})),
            "recommendation_count": assessor_data.get("total_recommendations", 0),
            "message_preview": message
        })
    
    return {
        "campaign_id": campaign.id,
        "total_assessors": len(messages),
        "total_recommendations": campaign.total_recommendations,
        "messages": messages[:10],
        "template_name": template.name
    }


def group_recommendations_by_assessor(data: List[dict], mapping: dict, custom_mapping: dict, db: Session) -> dict:
    """
    Agrupa recomendações por assessor e, dentro de cada assessor, por cliente.
    """
    grouped = {}
    
    for row in data:
        assessor_id = str(row.get(mapping.get("assessor_id", ""), "")).strip()
        if not assessor_id:
            continue
        
        if assessor_id not in grouped:
            assessor = None
            try:
                assessor_id_int = int(assessor_id)
                assessor = db.query(Assessor).filter(Assessor.id == assessor_id_int).first()
            except (ValueError, TypeError):
                pass
            
            if not assessor:
                assessor = db.query(Assessor).filter(
                    (Assessor.telefone_whatsapp == assessor_id) |
                    (Assessor.nome.ilike(f"%{assessor_id}%"))
                ).first()
            
            grouped[assessor_id] = {
                "assessor_id": assessor_id,
                "nome_assessor": assessor.nome if assessor else assessor_id,
                "telefone": assessor.telefone_whatsapp if assessor else "",
                "clients": {},
                "total_recommendations": 0,
                "custom_fields": {}
            }
            
            for col_name, var_name in custom_mapping.items():
                if col_name in row:
                    grouped[assessor_id]["custom_fields"][var_name] = row[col_name]
        
        client_id = str(row.get(mapping.get("client_id", ""), "")).strip()
        if client_id not in grouped[assessor_id]["clients"]:
            grouped[assessor_id]["clients"][client_id] = []
        
        recommendation = {
            "ativo_saida": row.get(mapping.get("ativo_saida", ""), ""),
            "valor_saida": format_currency(row.get(mapping.get("valor_saida", ""), 0)),
            "ativo_compra": row.get(mapping.get("ativo_compra", ""), ""),
            "valor_compra": format_currency(row.get(mapping.get("valor_compra", ""), 0))
        }
        
        grouped[assessor_id]["clients"][client_id].append(recommendation)
        grouped[assessor_id]["total_recommendations"] += 1
    
    return grouped


def format_currency(value) -> str:
    """Formata valor para moeda brasileira."""
    try:
        if isinstance(value, str):
            value = value.replace("R$", "").replace(".", "").replace(",", ".").strip()
        num = float(value)
        return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return str(value)


def build_message(template_content: str, assessor_data: dict, custom_mapping: dict) -> str:
    """
    Constrói a mensagem final substituindo as variáveis do template.
    """
    from datetime import datetime
    message = template_content
    
    message = message.replace("{{nome_assessor}}", assessor_data.get("nome_assessor", ""))
    message = message.replace("{{assessor_id}}", assessor_data.get("assessor_id", ""))
    message = message.replace("{{data_atual}}", datetime.now().strftime("%d/%m/%Y"))
    
    for var_name, value in assessor_data.get("custom_fields", {}).items():
        message = message.replace(f"{{{{{var_name}}}}}", str(value))
    
    clients_block = build_clients_block(assessor_data.get("clients", {}))
    message = message.replace("{{lista_clientes}}", clients_block)
    
    message = re.sub(r'\{\{[^}]+\}\}', '', message)
    
    return message


def build_clients_block(clients: dict) -> str:
    """
    Constrói o bloco de texto com as recomendações agrupadas por cliente.
    """
    lines = []
    
    for client_id, recommendations in clients.items():
        lines.append(f"**Cliente: {client_id}**")
        for rec in recommendations:
            line = f"• Saia de {rec['valor_saida']} em {rec['ativo_saida']} e compre {rec['valor_compra']} em {rec['ativo_compra']}."
            lines.append(line)
        lines.append("")
    
    return "\n".join(lines).strip()


@router.post("/{campaign_id}/dispatch")
async def dispatch_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao())
):
    """
    Dispara a campanha enviando mensagens via WhatsApp.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    if campaign.status == CampaignStatus.SENT.value:
        raise HTTPException(status_code=400, detail="Esta campanha já foi enviada")
    
    if not campaign.template_id:
        raise HTTPException(status_code=400, detail="Template não definido")
    
    template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
    if not template:
        raise HTTPException(status_code=400, detail="Template não encontrado")
    
    try:
        column_mapping = json.loads(campaign.column_mapping) if campaign.column_mapping else {}
        custom_mapping = json.loads(campaign.custom_fields_mapping) if campaign.custom_fields_mapping else {}
        data = json.loads(campaign.processed_data) if campaign.processed_data else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Erro nos dados da campanha")
    
    campaign.status = CampaignStatus.PROCESSING.value
    db.commit()
    
    grouped = group_recommendations_by_assessor(data, column_mapping, custom_mapping, db)
    
    from services.whatsapp_service import send_whatsapp_message
    import os
    
    waha_url = os.getenv("WAHA_API_URL", "")
    sent_count = 0
    failed_count = 0
    
    for assessor_id, assessor_data in grouped.items():
        message = build_message(template.content, assessor_data, custom_mapping)
        phone = assessor_data.get("telefone", "")
        
        dispatch = CampaignDispatch(
            campaign_id=campaign_id,
            assessor_id=assessor_id,
            assessor_phone=phone,
            assessor_name=assessor_data.get("nome_assessor", ""),
            message_content=message,
            status="pending"
        )
        db.add(dispatch)
        db.flush()
        
        if phone and waha_url:
            try:
                result = send_whatsapp_message(phone, message)
                if result.get("success"):
                    dispatch.status = "sent"
                    dispatch.sent_at = datetime.utcnow()
                    sent_count += 1
                else:
                    dispatch.status = "failed"
                    dispatch.error_message = result.get("error", "Erro desconhecido")
                    failed_count += 1
            except Exception as e:
                dispatch.status = "failed"
                dispatch.error_message = str(e)
                failed_count += 1
        else:
            dispatch.status = "simulated"
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
    
    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "template_id": campaign.template_id,
        "template_name": campaign.template.name if campaign.template else None,
        "original_filename": campaign.original_filename,
        "total_assessors": campaign.total_assessors,
        "total_recommendations": campaign.total_recommendations,
        "messages_sent": campaign.messages_sent,
        "messages_failed": campaign.messages_failed,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "sent_at": campaign.sent_at.isoformat() if campaign.sent_at else None,
        "dispatches": [
            {
                "assessor_id": d.assessor_id,
                "assessor_name": d.assessor_name,
                "status": d.status,
                "error_message": d.error_message,
                "sent_at": d.sent_at.isoformat() if d.sent_at else None
            }
            for d in dispatches
        ]
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
