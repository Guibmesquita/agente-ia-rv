"""
Endpoints para Campanhas Ativas e Templates de Mensagem.
Permite criar campanhas de disparo em massa para assessores.
"""
import json
import io
import re
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database.database import get_db, SessionLocal
from database.models import MessageTemplate, Campaign, CampaignDispatch, CampaignStatus, Assessor
from api.endpoints.auth import require_role
from database.models import User

DISPATCH_DELAY_SECONDS = 5.0
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 3.0

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def translate_error_to_natural_language(error_code: str, error_msg: str, phone: str = "") -> str:
    """
    Traduz códigos de erro técnicos para linguagem natural amigável.
    """
    translations = {
        "TIMEOUT": f"O servidor do WhatsApp demorou muito para responder. Isso pode indicar que o serviço está sobrecarregado ou indisponível.",
        "CONNECTION_ERROR": "Não foi possível conectar ao servidor do WhatsApp. Verifique se a URL do WAHA está correta e se o serviço está online.",
        "HTTP_401": "Credenciais inválidas. A chave de API do WAHA pode estar incorreta ou expirada.",
        "HTTP_403": "Acesso negado. Verifique as permissões da sua chave de API do WAHA.",
        "HTTP_404": "Endpoint não encontrado. Verifique se a URL do WAHA está correta.",
        "HTTP_500": "Erro interno no servidor do WhatsApp. O serviço WAHA pode estar com problemas.",
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
        base_msg = "A sessão do WhatsApp não foi encontrada. É necessário reconectar o WhatsApp no painel WAHA."
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


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


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
            "nome": a.nome,
            "email": a.email,
            "telefone_whatsapp": a.telefone_whatsapp,
            "unidade": a.unidade,
            "equipe": a.equipe
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
    
    required_fields = ["assessor_id", "assessor_email", "client_id", "ativo_saida", "valor_saida", "ativo_compra", "valor_compra"]
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


class CustomTemplateRequest(BaseModel):
    content: str


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
    
    print(f"[DEBUG CUSTOM_TEMPLATE] campaign_id={campaign_id}")
    print(f"[DEBUG CUSTOM_TEMPLATE] content length={len(request.content)}")
    print(f"[DEBUG CUSTOM_TEMPLATE] content first 300 chars: '{request.content[:300]}'")
    
    campaign.custom_template_content = request.content
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
    
    messages = []
    for assessor_id, assessor_data in grouped.items():
        message = build_message(template_content, assessor_data, custom_mapping)
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
        "messages": messages[:5],
        "template_name": template_name
    }


async def preview_campaign_from_base(campaign, db: Session):
    """
    Gera preview para campanhas baseadas em assessores selecionados da base.
    Não tem recomendações de ativos, apenas lista de assessores para disparo.
    """
    template_content = "Ola, {{nome_assessor}}!\n\n"
    template_name = "Mensagem Simples"
    
    if campaign.custom_template_content:
        template_content = str(campaign.custom_template_content)
        template_name = "Mensagem Editada"
    elif campaign.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
        if template:
            template_content = str(template.content)
            template_name = str(template.name)
    
    try:
        data = json.loads(str(campaign.processed_data)) if campaign.processed_data else []
    except json.JSONDecodeError:
        data = []
    
    messages = []
    for assessor in data:
        message = template_content.replace("{{nome_assessor}}", assessor.get("nome", ""))
        message = message.replace("{{ nome_assessor }}", assessor.get("nome", ""))
        message = message.replace("{nome_assessor}", assessor.get("nome", ""))
        message = message.replace("{{lista_clientes}}", "(Sem recomendacoes de ativos)")
        message = message.replace("{{ lista_clientes }}", "(Sem recomendacoes de ativos)")
        message = message.replace("{lista_clientes}", "(Sem recomendacoes de ativos)")
        
        messages.append({
            "assessor_id": str(assessor.get("id", "")),
            "assessor_name": assessor.get("nome", ""),
            "assessor_phone": assessor.get("telefone_whatsapp", ""),
            "client_count": 0,
            "recommendation_count": 0,
            "message_preview": message
        })
    
    return {
        "campaign_id": campaign.id,
        "total_assessors": len(messages),
        "total_recommendations": 0,
        "messages": messages[:5],
        "template_name": template_name,
        "source_type": "base"
    }


def group_recommendations_by_assessor(data: List[dict], mapping: dict, custom_mapping: dict, db: Session) -> dict:
    """
    Agrupa recomendações por assessor e, dentro de cada assessor, por cliente.
    
    Retorna um dicionário onde cada chave é o ID do assessor e o valor contém:
    - assessor_id: identificador do assessor
    - nome_assessor: nome do assessor (buscado na base ou usando o ID)
    - telefone: telefone do assessor
    - clients: dicionário de clientes com suas recomendações
    - total_recommendations: total de recomendações para este assessor
    - custom_fields: campos customizados mapeados
    """
    grouped = {}
    
    # Extrai os nomes das colunas do mapeamento
    col_assessor = mapping.get("assessor_id", "")
    col_assessor_email = mapping.get("assessor_email", "")
    col_client = mapping.get("client_id", "")
    col_ativo_saida = mapping.get("ativo_saida", "")
    col_valor_saida = mapping.get("valor_saida", "")
    col_ativo_compra = mapping.get("ativo_compra", "")
    col_valor_compra = mapping.get("valor_compra", "")
    
    print(f"[GROUPING] Column mapping: assessor={col_assessor}, client={col_client}")
    print(f"[GROUPING] Total rows to process: {len(data)}")
    
    for idx, row in enumerate(data):
        # Obtém o ID do assessor da linha
        assessor_val = row.get(col_assessor, "")
        if assessor_val is None:
            assessor_val = ""
        assessor_id = str(assessor_val).strip()
        
        if not assessor_id:
            print(f"[GROUPING] Row {idx}: No assessor_id found, skipping")
            continue
        
        # Inicializa o grupo do assessor se ainda não existe
        if assessor_id not in grouped:
            # Tenta buscar o assessor na base de dados
            assessor = None
            
            # Primeiro tenta buscar por email (se disponível na planilha)
            email_from_sheet = ""
            if col_assessor_email:
                email_val = row.get(col_assessor_email, "")
                if email_val:
                    email_from_sheet = str(email_val).strip()
                    assessor = db.query(Assessor).filter(Assessor.email == email_from_sheet).first()
            
            # Se não encontrou por email, tenta como ID numérico
            if not assessor:
                try:
                    assessor_id_int = int(assessor_id)
                    assessor = db.query(Assessor).filter(Assessor.id == assessor_id_int).first()
                except (ValueError, TypeError):
                    pass
            
            # Se não encontrou, tenta por telefone ou nome
            if not assessor:
                assessor = db.query(Assessor).filter(
                    (Assessor.telefone_whatsapp == assessor_id) |
                    (Assessor.nome.ilike(f"%{assessor_id}%"))
                ).first()
            
            # Define o nome do assessor
            if assessor:
                nome = assessor.nome
                telefone = assessor.telefone_whatsapp or ""
                email_assessor = assessor.email or email_from_sheet
            else:
                nome = assessor_id
                telefone = ""
                email_assessor = email_from_sheet
            
            grouped[assessor_id] = {
                "assessor_id": assessor_id,
                "email_assessor": email_assessor,
                "nome_assessor": nome,
                "telefone": telefone,
                "clients": {},
                "total_recommendations": 0,
                "custom_fields": {}
            }
            
            # Processa campos customizados
            if custom_mapping:
                for col_name, var_name in custom_mapping.items():
                    if col_name in row and row[col_name]:
                        grouped[assessor_id]["custom_fields"][var_name] = str(row[col_name])
            
            print(f"[GROUPING] New assessor: {assessor_id} -> nome={nome}")
        
        # Obtém o ID do cliente
        client_val = row.get(col_client, "")
        if client_val is None:
            client_val = ""
        client_id = str(client_val).strip()
        
        if not client_id:
            client_id = "Sem ID"
        
        # Inicializa a lista de recomendações do cliente
        if client_id not in grouped[assessor_id]["clients"]:
            grouped[assessor_id]["clients"][client_id] = []
        
        # Cria a recomendação
        recommendation = {
            "ativo_saida": str(row.get(col_ativo_saida, "") or ""),
            "valor_saida": format_currency(row.get(col_valor_saida, 0)),
            "ativo_compra": str(row.get(col_ativo_compra, "") or ""),
            "valor_compra": format_currency(row.get(col_valor_compra, 0))
        }
        
        grouped[assessor_id]["clients"][client_id].append(recommendation)
        grouped[assessor_id]["total_recommendations"] += 1
    
    print(f"[GROUPING] Final result: {len(grouped)} assessors")
    for aid, adata in grouped.items():
        print(f"[GROUPING]   {aid}: nome={adata['nome_assessor']}, clients={len(adata['clients'])}, recs={adata['total_recommendations']}")
    
    return grouped


def format_currency(value) -> str:
    """Formata valor para moeda brasileira."""
    if value is None:
        return "R$ 0,00"
    try:
        if isinstance(value, str):
            # Remove formatação existente
            value = value.replace("R$", "").replace(".", "").replace(",", ".").strip()
            if not value:
                return "R$ 0,00"
        num = float(value)
        return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return str(value) if value else "R$ 0,00"


def build_message(template_content: str, assessor_data: dict, custom_mapping: dict) -> str:
    """
    Constrói a mensagem final substituindo as variáveis do template.
    
    Variáveis suportadas:
    - {{nome_assessor}} - Nome do assessor
    - {{assessor_id}} - ID do assessor
    - {{data_atual}} - Data atual (DD/MM/YYYY)
    - {{lista_clientes}} - Bloco formatado com recomendações por cliente
    - Campos customizados definidos no mapeamento
    """
    # Garante que temos uma string válida
    if not template_content:
        template_content = DEFAULT_TEMPLATE_CONTENT
    
    message = str(template_content)
    
    # Extrai dados do assessor
    nome_assessor = str(assessor_data.get("nome_assessor", "") or "")
    assessor_id_val = str(assessor_data.get("assessor_id", "") or "")
    clients = assessor_data.get("clients", {})
    custom_fields = assessor_data.get("custom_fields", {})
    
    print(f"[BUILD_MSG] Input template (first 200 chars): {message[:200]}")
    print(f"[BUILD_MSG] nome_assessor='{nome_assessor}'")
    print(f"[BUILD_MSG] assessor_id='{assessor_id_val}'")
    print(f"[BUILD_MSG] clients count={len(clients)}")
    print(f"[BUILD_MSG] custom_fields={custom_fields}")
    
    # SUBSTITUIÇÕES PRINCIPAIS
    # Tenta múltiplas variações de formatação para máxima compatibilidade
    
    # 1. Nome do assessor
    for pattern in ["{{nome_assessor}}", "{{ nome_assessor }}", "{nome_assessor}"]:
        message = message.replace(pattern, nome_assessor)
    
    # 2. ID do assessor
    for pattern in ["{{assessor_id}}", "{{ assessor_id }}", "{assessor_id}"]:
        message = message.replace(pattern, assessor_id_val)
    
    # 3. Data atual
    data_atual = datetime.now().strftime("%d/%m/%Y")
    for pattern in ["{{data_atual}}", "{{ data_atual }}", "{data_atual}"]:
        message = message.replace(pattern, data_atual)
    
    # 4. Campos customizados
    for var_name, value in custom_fields.items():
        val_str = str(value) if value else ""
        for pattern in [f"{{{{{var_name}}}}}", f"{{{{ {var_name} }}}}", f"{{{var_name}}}"]:
            message = message.replace(pattern, val_str)
    
    # 5. Lista de clientes (mais importante!)
    clients_block = build_clients_block(clients)
    print(f"[BUILD_MSG] clients_block length={len(clients_block)}")
    if clients_block:
        print(f"[BUILD_MSG] clients_block preview: {clients_block[:300]}")
    
    for pattern in ["{{lista_clientes}}", "{{ lista_clientes }}", "{lista_clientes}"]:
        message = message.replace(pattern, clients_block)
    
    # Remove variáveis não substituídas
    message = re.sub(r'\{\{[^}]+\}\}', '', message)
    
    print(f"[BUILD_MSG] Final message (first 300 chars): {message[:300]}")
    
    return message


def build_clients_block(clients: dict) -> str:
    """
    Constrói o bloco de texto com as recomendações agrupadas por cliente.
    
    Formato:
    **Cliente: 12345**
    • Saia de R$ 10.000 em PETR4 e compre R$ 10.000 em VALE3.
    
    **Cliente: 67890**
    • Saia de R$ 20.000 em ITSA4 e compre R$ 20.000 em WEGE3.
    """
    if not clients:
        print("[BUILD_CLIENTS] No clients provided!")
        return "(Nenhuma recomendação encontrada)"
    
    lines = []
    
    for client_id, recommendations in clients.items():
        if not client_id:
            client_id = "Sem ID"
        
        lines.append(f"**Cliente: {client_id}**")
        
        for rec in recommendations:
            ativo_saida = rec.get('ativo_saida', 'N/A')
            valor_saida = rec.get('valor_saida', 'R$ 0,00')
            ativo_compra = rec.get('ativo_compra', 'N/A')
            valor_compra = rec.get('valor_compra', 'R$ 0,00')
            
            line = f"• Saia de {valor_saida} em {ativo_saida} e compre {valor_compra} em {ativo_compra}."
            lines.append(line)
        
        lines.append("")  # Linha em branco entre clientes
    
    result = "\n".join(lines).strip()
    print(f"[BUILD_CLIENTS] Generated block with {len(lines)} lines for {len(clients)} clients")
    return result


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
    
    from services.whatsapp_client import whatsapp_client
    import os
    
    waha_url = os.getenv("WAHA_API_URL", "")
    sent_count = 0
    failed_count = 0
    
    for assessor_id, assessor_data in grouped.items():
        message = build_message(template_content, assessor_data, custom_mapping)
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
        
        if phone and waha_url:
            try:
                result = await whatsapp_client.send_message(phone, message)
                dispatch.api_response = json.dumps(result, ensure_ascii=False, default=str)
                
                if result.get("success"):
                    dispatch.status = "sent"
                    dispatch.sent_at = datetime.utcnow()
                    sent_count += 1
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
            elif not waha_url:
                dispatch.status = "simulated"
                dispatch.error_details = "Disparo simulado - WAHA não configurado"
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
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    
    if campaign.status == CampaignStatus.SENT.value:
        raise HTTPException(status_code=400, detail="Esta campanha já foi enviada")
    
    source_type = getattr(campaign, 'source_type', 'upload') or 'upload'
    
    if source_type == "base":
        return await dispatch_campaign_from_base(campaign, db)
    
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
    
    async def generate_events():
        from services.whatsapp_client import whatsapp_client
        import os
        
        waha_url = os.getenv("WAHA_API_URL", "")
        sent_count = 0
        failed_count = 0
        current_index = 0
        cancelled = False
        
        try:
            yield f"data: {json.dumps({'type': 'start', 'total': total_assessors})}\n\n"
            
            for assessor_id, assessor_data in grouped.items():
                current_index += 1
                message = build_message(template_content, assessor_data, custom_mapping)
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
                    
                    if phone and waha_url:
                        while attempt <= MAX_RETRY_ATTEMPTS:
                            try:
                                result = await whatsapp_client.send_message(phone, message)
                                dispatch.api_response = json.dumps(result, ensure_ascii=False, default=str)
                                
                                if result.get("success"):
                                    dispatch.status = "sent"
                                    dispatch.sent_at = datetime.utcnow()
                                    sent_count += 1
                                    status = "sent"
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
                        elif not waha_url:
                            dispatch.status = "simulated"
                            dispatch.error_details = "Disparo simulado - WAHA não configurado"
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
                    await asyncio.sleep(DISPATCH_DELAY_SECONDS)
        
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


async def dispatch_campaign_from_base(campaign, db: Session):
    """
    Dispara campanha baseada em assessores selecionados da base.
    Envia mensagem simples para cada assessor sem lista de clientes.
    """
    from services.whatsapp_client import whatsapp_client
    import os
    
    template_content = "Ola, {{nome_assessor}}!\n\n"
    
    if campaign.custom_template_content:
        template_content = str(campaign.custom_template_content)
    elif campaign.template_id:
        template = db.query(MessageTemplate).filter(MessageTemplate.id == campaign.template_id).first()
        if template:
            template_content = str(template.content)
    
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
    
    async def generate_events():
        waha_url = os.getenv("WAHA_API_URL", "")
        sent_count = 0
        failed_count = 0
        current_index = 0
        cancelled = False
        
        try:
            yield f"data: {json.dumps({'type': 'start', 'total': total_assessors})}\n\n"
            
            for assessor in data:
                current_index += 1
                assessor_name = assessor.get("nome", "")
                phone = assessor.get("telefone_whatsapp", "")
                
                message = template_content.replace("{{nome_assessor}}", assessor_name)
                message = message.replace("{{ nome_assessor }}", assessor_name)
                message = message.replace("{nome_assessor}", assessor_name)
                message = message.replace("{{lista_clientes}}", "(Campanha sem recomendacoes de ativos)")
                message = message.replace("{{ lista_clientes }}", "(Campanha sem recomendacoes de ativos)")
                message = message.replace("{lista_clientes}", "(Campanha sem recomendacoes de ativos)")
                
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
                    
                    if phone and waha_url:
                        while attempt <= MAX_RETRY_ATTEMPTS:
                            try:
                                result = await whatsapp_client.send_message(phone, message)
                                dispatch.api_response = json.dumps(result, ensure_ascii=False, default=str)
                                
                                if result.get("success"):
                                    dispatch.status = "sent"
                                    dispatch.sent_at = datetime.utcnow()
                                    sent_count += 1
                                    status = "sent"
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
                        elif not waha_url:
                            dispatch.status = "simulated"
                            dispatch.error_details = "Disparo simulado - WAHA não configurado"
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
                    await asyncio.sleep(DISPATCH_DELAY_SECONDS)
        
        except asyncio.CancelledError:
            cancelled = True
        finally:
            db_final = SessionLocal()
            try:
                campaign_final = db_final.query(Campaign).filter(Campaign.id == campaign.id).first()
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
            summary_parts.append(f"{count} falha(s) de conexao com o servidor WAHA")
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
    
    sample_message = ""
    if grouped:
        first_key = list(grouped.keys())[0]
        sample_message = build_message(template_content, grouped[first_key], custom_mapping)
    
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
