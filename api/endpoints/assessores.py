"""
Endpoints para gerenciamento da Base de Assessores.
Requer autenticação como admin ou gestao_rv.
"""
import os
import uuid
import shutil
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from datetime import datetime

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
        "created_at": assessor.created_at,
        "updated_at": assessor.updated_at,
        "custom_fields": {}
    }
    if assessor.custom_fields:
        try:
            result["custom_fields"] = json.loads(assessor.custom_fields)
        except:
            result["custom_fields"] = {}
    return result


@router.get("", response_model=List[dict])
async def list_assessores(
    search: Optional[str] = Query(None),
    unidade: Optional[str] = Query(None),
    equipe: Optional[str] = Query(None),
    broker: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
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
    
    assessores = query.order_by(Assessor.nome).offset(skip).limit(limit).all()
    return [parse_custom_fields(a) for a in assessores]


@router.get("/count")
async def count_assessores(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    return {"count": db.query(Assessor).count()}


@router.get("/filters")
async def get_filter_options(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    unidades = db.query(Assessor.unidade).distinct().filter(Assessor.unidade.isnot(None)).all()
    equipes = db.query(Assessor.equipe).distinct().filter(Assessor.equipe.isnot(None)).all()
    brokers = db.query(Assessor.broker_responsavel).distinct().filter(Assessor.broker_responsavel.isnot(None)).all()
    
    return {
        "unidades": sorted([u[0] for u in unidades if u[0]]),
        "equipes": sorted([e[0] for e in equipes if e[0]]),
        "brokers": sorted([b[0] for b in brokers if b[0]])
    }


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
    for key, value in update_data.items():
        if key == "custom_fields" and value is not None:
            setattr(db_assessor, key, json.dumps(value))
        else:
            setattr(db_assessor, key, value)
    
    db.commit()
    db.refresh(db_assessor)
    return parse_custom_fields(db_assessor)


@router.delete("/{assessor_id}")
async def delete_assessor(assessor_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_gestao)):
    db_assessor = db.query(Assessor).filter(Assessor.id == assessor_id).first()
    if not db_assessor:
        raise HTTPException(status_code=404, detail="Assessor não encontrado")
    
    db.delete(db_assessor)
    db.commit()
    return {"message": "Assessor excluído com sucesso"}


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
    fields = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.is_active == 1).all()
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
            df = pd.read_excel(file_path)
        
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
        {"slug": "nome", "label": "Nome do Assessor", "required": True},
        {"slug": "email", "label": "E-mail", "required": True},
        {"slug": "telefone_whatsapp", "label": "Telefone WhatsApp", "required": False},
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
    if pd is None:
        raise HTTPException(status_code=500, detail="Pandas não está instalado")
    
    file_path = temp_files.get(data.file_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado. Faça o upload novamente.")
    
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
        
        mapping_dict = {m.spreadsheet_column: m.database_field for m in data.mappings}
        
        created = 0
        updated = 0
        errors = []
        
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
                        value = str(value)
                    
                    if field.startswith("custom_"):
                        custom_key = field.replace("custom_", "")
                        assessor_data["custom_fields"][custom_key] = value
                    else:
                        assessor_data[field] = value
                
                if not assessor_data.get("nome"):
                    errors.append(f"Linha {idx + 2}: Nome é obrigatório")
                    continue
                
                if not assessor_data.get("email"):
                    errors.append(f"Linha {idx + 2}: E-mail é obrigatório")
                    continue
                
                if data.update_existing and assessor_data.get("email"):
                    existing = db.query(Assessor).filter(
                        Assessor.email == assessor_data["email"]
                    ).first()
                    
                    if existing:
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
            "errors": errors[:10],
            "total_errors": len(errors)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar importação: {str(e)}")
