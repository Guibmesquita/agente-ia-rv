"""
Endpoints para gerenciamento da Base de Assessores.
Requer autenticação como admin ou gestao_rv.
"""
import os
import uuid
import shutil
import json
import logging
import traceback
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import pandas as pd
except ImportError:
    pd = None

from database.database import get_db
from database.models import Assessor, CustomFieldDefinition, User
from api.endpoints.auth import require_role

router = APIRouter(prefix="/api/assessores", tags=["assessores"])

require_admin_or_gestao = require_role(["admin", "gestao_rv"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
temp_files = {}


class AssessorBase(BaseModel):
    codigo_ai: Optional[str] = None
    nome: str
    email: str
    telefone_whatsapp: Optional[str] = None
    unidade: Optional[str] = None
    equipe: Optional[str] = None
    broker_responsavel: Optional[str] = None
    custom_fields: Optional[dict] = {}


class AssessorCreate(AssessorBase):
    pass


class AssessorUpdate(BaseModel):
    codigo_ai: Optional[str] = None
    nome: Optional[str] = None
    email: Optional[str] = None
    telefone_whatsapp: Optional[str] = None
    unidade: Optional[str] = None
    equipe: Optional[str] = None
    broker_responsavel: Optional[str] = None
    custom_fields: Optional[dict] = None


class AssessorResponse(AssessorBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomFieldBase(BaseModel):
    slug: str
    label: str
    field_type: str = "text"
    is_required: bool = False
    options: List[str] = []


class CustomFieldCreate(CustomFieldBase):
    pass


class CustomFieldResponse(BaseModel):
    id: int
    slug: str
    label: str
    field_type: str
    is_required: bool
    is_active: bool
    options: List[str] = []
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FieldMapping(BaseModel):
    spreadsheet_column: str
    database_field: str


class UploadPreview(BaseModel):
    columns: List[str]
    sample_data: List[dict]
    total_rows: int
    file_id: str


class UploadConfirm(BaseModel):
    file_id: str
    mappings: List[FieldMapping]
    update_existing: bool = False
    replace_all: bool = False


def parse_custom_fields(assessor):
    """Parse custom_fields from JSON string to dict."""
    result = {
        "id": assessor.id,
        "codigo_ai": assessor.codigo_ai,
        "nome": assessor.nome,
        "email": assessor.email,
        "telefone_whatsapp": assessor.telefone_whatsapp,
        "unidade": assessor.unidade,
        "equipe": assessor.equipe,
        "broker_responsavel": assessor.broker_responsavel,
        "channel_id": assessor.channel_id,
        "channel_label": None,
        "created_at": assessor.created_at,
        "updated_at": assessor.updated_at,
        "custom_fields": {}
    }
    try:
        if assessor.zapi_channel:
            result["channel_label"] = assessor.zapi_channel.label or assessor.zapi_channel.name
    except Exception:
        pass
    if assessor.custom_fields:
        try:
            result["custom_fields"] = json.loads(assessor.custom_fields)
        except:
            result["custom_fields"] = {}
    return result


@router.get("", response_model=List[dict])
async def list_assessores(
    request: Request,
    search: Optional[str] = Query(None),
    unidade: Optional[str] = Query(None),
    equipe: Optional[str] = Query(None),
    broker: Optional[str] = Query(None),
    codigo_ai: Optional[str] = Query(None),
    nome: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    telefone: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    import json
    
    query = db.query(Assessor)
    
    if search:
        query = query.filter(
            or_(
                Assessor.nome.ilike(f"%{search}%"),
                Assessor.telefone_whatsapp.ilike(f"%{search}%")
            )
        )
    if unidade:
        query = query.filter(Assessor.unidade == unidade)
    if equipe:
        query = query.filter(Assessor.equipe == equipe)
    if broker:
        query = query.filter(Assessor.broker_responsavel == broker)
    if codigo_ai:
        query = query.filter(Assessor.codigo_ai.ilike(f"%{codigo_ai}%"))
    if nome:
        query = query.filter(Assessor.nome.ilike(f"%{nome}%"))
    if email:
        query = query.filter(Assessor.email.ilike(f"%{email}%"))
    if telefone:
        query = query.filter(Assessor.telefone_whatsapp.ilike(f"%{telefone}%"))
    
    cf_filters = {k[3:]: v for k, v in request.query_params.items() if k.startswith('cf_') and v}
    
    if cf_filters:
        all_assessores = query.order_by(Assessor.nome).all()
        filtered = []
        for a in all_assessores:
            try:
                cf_data = json.loads(a.custom_fields) if a.custom_fields else {}
            except:
                cf_data = {}
            
            match = True
            for slug, value in cf_filters.items():
                if str(cf_data.get(slug, '')) != value:
                    match = False
                    break
            
            if match:
                filtered.append(a)
        
        return [parse_custom_fields(a) for a in filtered[skip:skip+limit]]
    
    assessores = query.order_by(Assessor.nome).offset(skip).limit(limit).all()
    return [parse_custom_fields(a) for a in assessores]


@router.get("/count")
async def count_assessores(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    return {"count": db.query(Assessor).count()}


@router.get("/filters")
async def get_filter_options(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    import json
    
    unidades = db.query(Assessor.unidade).distinct().filter(Assessor.unidade.isnot(None)).all()
    equipes = db.query(Assessor.equipe).distinct().filter(Assessor.equipe.isnot(None)).all()
    brokers = db.query(Assessor.broker_responsavel).distinct().filter(Assessor.broker_responsavel.isnot(None)).all()
    
    custom_field_defs = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.is_active == 1).all()
    custom_field_values = {}
    
    if custom_field_defs:
        assessores = db.query(Assessor.custom_fields).filter(Assessor.custom_fields.isnot(None)).all()
        for cf in custom_field_defs:
            values = set()
            for (cf_json,) in assessores:
                try:
                    data = json.loads(cf_json) if cf_json else {}
                    if cf.slug in data and data[cf.slug]:
                        values.add(str(data[cf.slug]))
                except:
                    pass
            custom_field_values[cf.slug] = sorted(list(values))
    
    return {
        "unidades": sorted([u[0] for u in unidades if u[0]]),
        "equipes": sorted([e[0] for e in equipes if e[0]]),
        "brokers": sorted([b[0] for b in brokers if b[0]]),
        "custom_fields": custom_field_values
    }


@router.get("/channels")
async def list_active_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Lista canais Z-API ativos para uso nos dropdowns de vinculação de assessores."""
    from database.models import ZAPIChannel
    channels = (
        db.query(ZAPIChannel)
        .filter(ZAPIChannel.is_active == True)
        .order_by(ZAPIChannel.name)
        .all()
    )
    return [
        {"id": c.id, "name": c.name, "label": c.label or c.name}
        for c in channels
    ]


@router.get("/{assessor_id}")
async def get_assessor(assessor_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    assessor = db.query(Assessor).filter(Assessor.id == assessor_id).first()
    if not assessor:
        raise HTTPException(status_code=404, detail="Assessor não encontrado")
    return parse_custom_fields(assessor)


@router.post("")
async def create_assessor(assessor: AssessorCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    existing = db.query(Assessor).filter(Assessor.email == assessor.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Já existe um assessor com este e-mail")
    
    db_assessor = Assessor(
        codigo_ai=assessor.codigo_ai,
        nome=assessor.nome,
        email=assessor.email,
        telefone_whatsapp=assessor.telefone_whatsapp,
        unidade=assessor.unidade,
        equipe=assessor.equipe,
        broker_responsavel=assessor.broker_responsavel,
        custom_fields=json.dumps(assessor.custom_fields or {})
    )
    db.add(db_assessor)
    db.commit()
    db.refresh(db_assessor)
    return parse_custom_fields(db_assessor)


@router.put("/{assessor_id}")
async def update_assessor(assessor_id: int, assessor: AssessorUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    db_assessor = db.query(Assessor).filter(Assessor.id == assessor_id).first()
    if not db_assessor:
        raise HTTPException(status_code=404, detail="Assessor não encontrado")
    
    if assessor.email:
        existing = db.query(Assessor).filter(
            Assessor.email == assessor.email,
            Assessor.id != assessor_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Já existe outro assessor com este e-mail")
    
    update_data = assessor.model_dump(exclude_unset=True)
    phone_changed = "telefone_whatsapp" in update_data and update_data["telefone_whatsapp"] != db_assessor.telefone_whatsapp
    for key, value in update_data.items():
        if key == "custom_fields" and value is not None:
            setattr(db_assessor, key, json.dumps(value))
        else:
            setattr(db_assessor, key, value)
    
    if phone_changed and db_assessor.telefone_whatsapp:
        import re as _re
        from database.models import Conversation
        normalized_phone = _re.sub(r'\D', '', db_assessor.telefone_whatsapp) if db_assessor.telefone_whatsapp else None
        linked_conversations = db.query(Conversation).filter(
            Conversation.assessor_id == db_assessor.id
        ).all()
        for conv in linked_conversations:
            conv.phone = normalized_phone or db_assessor.telefone_whatsapp
        if linked_conversations:
            print(f"[ASSESSOR] Phone sync: {len(linked_conversations)} conversas atualizadas para {normalized_phone or db_assessor.telefone_whatsapp}")
    
    db.commit()
    db.refresh(db_assessor)
    return parse_custom_fields(db_assessor)


class AssessorChannelUpdate(BaseModel):
    channel_id: Optional[int] = None


@router.patch("/{assessor_id}/channel")
async def update_assessor_channel(
    assessor_id: int,
    data: AssessorChannelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Vincula ou desvincula um canal Z-API de um assessor individualmente.
    Passa channel_id=null para remover a vinculação específica (herda o canal da unidade).
    """
    from database.models import ZAPIChannel

    assessor = db.query(Assessor).filter(Assessor.id == assessor_id).first()
    if not assessor:
        raise HTTPException(status_code=404, detail="Assessor não encontrado")

    if data.channel_id is not None:
        channel = db.query(ZAPIChannel).filter(
            ZAPIChannel.id == data.channel_id,
            ZAPIChannel.is_active == True
        ).first()
        if not channel:
            raise HTTPException(
                status_code=404,
                detail=f"Canal {data.channel_id} não encontrado ou está inativo"
            )
        assessor.channel_id = data.channel_id
        logger.info(f"[ASSESSOR] Canal atualizado: assessor_id={assessor_id} → channel_id={data.channel_id} ({channel.label or channel.name})")
    else:
        assessor.channel_id = None
        logger.info(f"[ASSESSOR] Canal desvinculado: assessor_id={assessor_id}")

    db.commit()
    db.refresh(assessor)
    return parse_custom_fields(assessor)


class BulkChannelAssignRequest(BaseModel):
    assessor_ids: List[int]
    channel_id: Optional[int] = None


@router.post("/bulk-channel")
async def bulk_assign_channel(
    data: BulkChannelAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Vincula ou desvincula um canal Z-API de múltiplos assessores de uma vez."""
    from database.models import ZAPIChannel

    unique_ids = list(dict.fromkeys(data.assessor_ids))
    if not unique_ids:
        raise HTTPException(status_code=400, detail="Lista de assessores não pode ser vazia")

    channel = None
    if data.channel_id is not None:
        channel = db.query(ZAPIChannel).filter(
            ZAPIChannel.id == data.channel_id,
            ZAPIChannel.is_active == True
        ).first()
        if not channel:
            raise HTTPException(
                status_code=404,
                detail=f"Canal {data.channel_id} não encontrado ou está inativo"
            )

    updated = 0
    not_found = []
    for assessor_id in unique_ids:
        assessor = db.query(Assessor).filter(Assessor.id == assessor_id).first()
        if not assessor:
            not_found.append(assessor_id)
            continue
        assessor.channel_id = data.channel_id
        updated += 1

    db.commit()

    channel_label = (channel.label or channel.name) if channel else None
    logger.info(
        f"[ASSESSOR] Bulk channel assign: {updated} assessores → channel_id={data.channel_id} "
        f"({channel_label or 'desvinculado'}); não encontrados: {not_found}"
    )

    return {
        "updated": updated,
        "not_found": not_found,
        "channel_id": data.channel_id,
        "channel_label": channel_label
    }


class BulkDeleteByUnitsRequest(BaseModel):
    unidades: List[str]


@router.delete("/bulk-delete-by-units")
async def bulk_delete_by_units(
    data: BulkDeleteByUnitsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    from database.models import Conversation
    from sqlalchemy.exc import IntegrityError

    if not data.unidades:
        raise HTTPException(status_code=400, detail="Lista de unidades não pode ser vazia")

    assessor_ids = [
        a.id for a in db.query(Assessor.id).filter(Assessor.unidade.in_(data.unidades)).all()
    ]

    if not assessor_ids:
        return {"deleted": 0, "conversations_unlinked": 0, "unidades": data.unidades}

    conversations_unlinked = db.query(Conversation).filter(
        Conversation.assessor_id.in_(assessor_ids)
    ).update({"assessor_id": None}, synchronize_session=False)

    deleted = db.query(Assessor).filter(Assessor.id.in_(assessor_ids)).delete(synchronize_session=False)

    db.commit()

    logger.info(f"Bulk delete by units: {data.unidades} — {deleted} assessores excluídos, {conversations_unlinked} conversas desvinculadas")

    return {
        "deleted": deleted,
        "conversations_unlinked": conversations_unlinked,
        "unidades": data.unidades
    }


@router.delete("/{assessor_id}")
async def delete_assessor(assessor_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    from database.models import Conversation
    from sqlalchemy.exc import IntegrityError
    
    db_assessor = db.query(Assessor).filter(Assessor.id == assessor_id).first()
    if not db_assessor:
        raise HTTPException(status_code=404, detail="Assessor não encontrado")
    
    try:
        db.query(Conversation).filter(Conversation.assessor_id == assessor_id).update(
            {"assessor_id": None}, synchronize_session=False
        )
        
        db.delete(db_assessor)
        db.commit()
        return {"message": "Assessor excluído com sucesso"}
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=400, 
            detail="Não foi possível excluir o assessor. Existem dados vinculados a ele."
        )


custom_fields_router = APIRouter(prefix="/api/custom-fields", tags=["custom-fields"])


def parse_custom_field(field):
    """Parse custom field options from JSON string."""
    result = {
        "id": field.id,
        "slug": field.slug,
        "label": field.label,
        "field_type": field.field_type,
        "is_required": bool(field.is_required),
        "is_active": bool(field.is_active),
        "display_order": field.display_order or 0,
        "created_at": field.created_at,
        "options": []
    }
    if field.options:
        try:
            result["options"] = json.loads(field.options)
        except:
            result["options"] = []
    return result


@custom_fields_router.get("")
async def list_custom_fields(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    fields = db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.is_active == 1
    ).order_by(CustomFieldDefinition.display_order, CustomFieldDefinition.id).all()
    return [parse_custom_field(f) for f in fields]


@custom_fields_router.post("")
async def create_custom_field(field: CustomFieldCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    existing = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.slug == field.slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="Já existe um campo com este identificador")
    
    db_field = CustomFieldDefinition(
        slug=field.slug,
        label=field.label,
        field_type=field.field_type,
        is_required=1 if field.is_required else 0,
        options=json.dumps(field.options or [])
    )
    db.add(db_field)
    db.commit()
    db.refresh(db_field)
    return parse_custom_field(db_field)


@custom_fields_router.delete("/{field_id}")
async def delete_custom_field(field_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    db_field = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.id == field_id).first()
    if not db_field:
        raise HTTPException(status_code=404, detail="Campo customizado não encontrado")
    
    db_field.is_active = 0
    db.commit()
    return {"message": "Campo desativado com sucesso"}


class FieldOrderItem(BaseModel):
    id: int
    display_order: int


class FieldOrderUpdate(BaseModel):
    fields: List[FieldOrderItem]


@custom_fields_router.put("/reorder")
async def reorder_custom_fields(order_data: FieldOrderUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    for item in order_data.fields:
        db_field = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.id == item.id).first()
        if db_field:
            db_field.display_order = item.display_order
    db.commit()
    return {"message": "Ordem atualizada com sucesso"}


upload_router = APIRouter(prefix="/api/upload", tags=["upload"])


@upload_router.post("/preview", response_model=UploadPreview)
async def upload_preview(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    if pd is None:
        raise HTTPException(status_code=500, detail="Pandas não está instalado")
    
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="Formato de arquivo não suportado. Use Excel ou CSV.")
    
    file_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path, engine='openpyxl')
        
        temp_files[file_id] = file_path
        
        sample_data = df.head(5).fillna("").to_dict(orient="records")
        
        return UploadPreview(
            columns=list(df.columns),
            sample_data=sample_data,
            total_rows=len(df),
            file_id=file_id
        )
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail=f"Erro ao processar arquivo: {str(e)}")


@upload_router.get("/database-fields")
async def get_database_fields(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    core_fields = [
        {"slug": "codigo_ai", "label": "Código AAI", "required": False},
        {"slug": "nome", "label": "Nome do Assessor", "required": False},
        {"slug": "email", "label": "E-mail", "required": False},
        {"slug": "telefone_whatsapp", "label": "Telefone WhatsApp", "required": True},
        {"slug": "unidade", "label": "Unidade", "required": False},
        {"slug": "equipe", "label": "Equipe", "required": False},
        {"slug": "broker_responsavel", "label": "Broker Responsável", "required": False},
    ]
    
    custom_fields = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.is_active == 1).all()
    for cf in custom_fields:
        core_fields.append({
            "slug": f"custom_{cf.slug}",
            "label": cf.label,
            "required": bool(cf.is_required),
            "is_custom": True
        })
    
    return core_fields


@upload_router.post("/confirm")
async def confirm_upload(data: UploadConfirm, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    logger.info(f"Iniciando confirmação de importação - file_id: {data.file_id}")
    
    if pd is None:
        raise HTTPException(status_code=500, detail="Pandas não está instalado")
    
    file_path = temp_files.get(data.file_id)
    logger.info(f"Arquivo encontrado: {file_path}")
    
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado. Faça o upload novamente.")
    
    try:
        logger.info(f"Lendo arquivo: {file_path}")
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path, engine='openpyxl')
        logger.info(f"Arquivo lido com sucesso. Colunas: {list(df.columns)}, Linhas: {len(df)}")
        
        mapping_dict = {m.spreadsheet_column: m.database_field for m in data.mappings}
        
        created = 0
        updated = 0
        skipped = 0
        deleted = 0
        errors = []
        
        if data.replace_all:
            try:
                deleted = db.query(Assessor).count()
                db.query(Assessor).delete()
                db.commit()
            except Exception as delete_error:
                db.rollback()
                error_msg = str(delete_error)
                if "ForeignKeyViolation" in error_msg or "foreign key constraint" in error_msg:
                    raise HTTPException(
                        status_code=400, 
                        detail="Não é possível substituir todos os registros porque existem conversas ou campanhas vinculadas aos assessores atuais. Desmarque a opção 'Substituir todos' e use 'Atualizar registros existentes' para atualizar os dados sem perder os vínculos."
                    )
                raise
        
        for idx, row in df.iterrows():
            try:
                assessor_data = {"custom_fields": {}}
                
                for col, field in mapping_dict.items():
                    if col not in row:
                        continue
                    value = row[col]
                    if pd.isna(value):
                        value = None
                    elif isinstance(value, (int, float)):
                        value = str(int(value) if value == int(value) else value)
                    elif isinstance(value, str):
                        value = value.strip()
                        if value == "":
                            value = None
                    
                    if field.startswith("custom_"):
                        custom_key = field.replace("custom_", "")
                        assessor_data["custom_fields"][custom_key] = value
                    else:
                        assessor_data[field] = value
                
                telefone = assessor_data.get("telefone_whatsapp")
                if not telefone or str(telefone).strip() == "":
                    errors.append(f"Linha {idx + 2}: Telefone WhatsApp é obrigatório")
                    continue
                
                codigo_ai = assessor_data.get("codigo_ai")
                
                existing = None
                if telefone:
                    existing = db.query(Assessor).filter(
                        Assessor.telefone_whatsapp == telefone
                    ).first()
                
                if not existing and codigo_ai:
                    existing = db.query(Assessor).filter(
                        Assessor.codigo_ai == codigo_ai
                    ).first()
                
                if existing:
                    if data.update_existing:
                        if codigo_ai:
                            conflicting = db.query(Assessor).filter(
                                Assessor.codigo_ai == codigo_ai,
                                Assessor.id != existing.id
                            ).first()
                            if conflicting:
                                errors.append(f"Linha {idx + 2}: Código AAI '{codigo_ai}' já pertence a outro assessor")
                                continue
                        
                        for key, value in assessor_data.items():
                            if key == "custom_fields":
                                try:
                                    current = json.loads(existing.custom_fields or "{}")
                                except:
                                    current = {}
                                current.update(value)
                                existing.custom_fields = json.dumps(current)
                            else:
                                setattr(existing, key, value)
                        updated += 1
                    else:
                        skipped += 1
                    continue
                
                if codigo_ai:
                    existing_by_code = db.query(Assessor).filter(
                        Assessor.codigo_ai == codigo_ai
                    ).first()
                    if existing_by_code:
                        errors.append(f"Linha {idx + 2}: Código AAI '{codigo_ai}' já existe")
                        continue
                
                custom_fields_json = json.dumps(assessor_data.pop("custom_fields", {}))
                new_assessor = Assessor(**assessor_data, custom_fields=custom_fields_json)
                db.add(new_assessor)
                created += 1
                
            except Exception as e:
                errors.append(f"Linha {idx + 2}: {str(e)}")
        
        db.commit()
        
        if data.file_id in temp_files:
            del temp_files[data.file_id]
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "deleted": deleted,
            "errors": errors[:10],
            "total_errors": len(errors)
        }
        
    except Exception as e:
        logger.error(f"Erro ao processar importação: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erro ao processar importação: {str(e)}")
