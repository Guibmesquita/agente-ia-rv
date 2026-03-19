"""
Endpoints para gerenciamento de usuários.
Apenas administradores podem criar, editar e deletar usuários.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
import pandas as pd
import os
import uuid
import tempfile
import re
import secrets

from database.database import get_db
from database.models import User
from database import crud
from core.security import decode_token, get_password_hash

router = APIRouter(prefix="/api/users", tags=["Usuários"])


class UserCreate(BaseModel):
    """Schema para criação de usuário."""
    username: str
    first_name: Optional[str] = None
    full_name: Optional[str] = None
    email: EmailStr
    password: str
    phone: Optional[str] = None
    role: str = "broker"


class UserUpdate(BaseModel):
    """Schema para atualização de usuário."""
    username: Optional[str] = None
    first_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None


class UserResponse(BaseModel):
    """Schema para resposta de usuário."""
    id: int
    username: str
    first_name: Optional[str] = None
    full_name: Optional[str] = None
    email: str
    phone: Optional[str] = None
    role: str
    
    model_config = {"from_attributes": True}


def get_current_admin(request: Request, db: Session = Depends(get_db)):
    """
    Dependency que verifica se o usuário atual é admin.
    Usado para proteger rotas administrativas.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        # Tenta pegar do header Authorization
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado"
        )
    
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )
    
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado. Apenas administradores podem acessar este recurso."
        )
    
    return payload


@router.get("/", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Lista todos os usuários (apenas admin)."""
    users = crud.get_users(db, skip=skip, limit=limit)
    return users


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Cria um novo usuário (apenas admin)."""
    # Verifica se username já existe
    existing_user = crud.get_user_by_username(db, user.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de usuário já existe"
        )
    
    # Verifica se email já existe
    existing_email = crud.get_user_by_email(db, user.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email já cadastrado"
        )
    
    if user.phone and user.phone.strip():
        existing_phone = db.query(User).filter(User.phone == user.phone).first()
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Já existe um usuário com este telefone"
            )
    
    new_user = crud.create_user(
        db,
        username=user.username,
        email=user.email,
        password=user.password,
        phone=user.phone,
        role=user.role
    )
    return new_user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Busca um usuário por ID (apenas admin)."""
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Atualiza um usuário (apenas admin)."""
    update_data = user_update.model_dump(exclude_unset=True)
    
    if "email" in update_data and update_data["email"]:
        existing = db.query(User).filter(
            User.email == update_data["email"],
            User.id != user_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Já existe um usuário com este e-mail"
            )
    
    if "phone" in update_data and update_data["phone"] and update_data["phone"].strip():
        existing = db.query(User).filter(
            User.phone == update_data["phone"],
            User.id != user_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Já existe um usuário com este telefone"
            )
    
    if "username" in update_data and update_data["username"]:
        existing = db.query(User).filter(
            User.username == update_data["username"],
            User.id != user_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Já existe um usuário com este nome de usuário"
            )
    
    user = crud.update_user(db, user_id, **update_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Deleta um usuário (apenas admin)."""
    success = crud.delete_user(db, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )
    return None


temp_user_files: Dict[str, str] = {}

class UserImportConfirm(BaseModel):
    file_id: str
    mapping: Dict[str, str]
    update_existing: bool = False

def normalize_phone(phone: Any) -> Optional[str]:
    """Normaliza telefone removendo caracteres especiais."""
    if phone is None or (isinstance(phone, float) and pd.isna(phone)):
        return None
    phone_str = str(phone).strip()
    if phone_str == "" or phone_str.lower() == "nan":
        return None
    phone_str = re.sub(r'[^\d]', '', phone_str)
    if phone_str.endswith('.0'):
        phone_str = phone_str[:-2]
    return phone_str if phone_str else None

def normalize_value(value: Any) -> Optional[str]:
    """Normaliza valor removendo espaços e tratando vazios."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    val_str = str(value).strip()
    if val_str == "" or val_str.lower() == "nan":
        return None
    return val_str


@router.post("/import/upload")
async def upload_users_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin)
):
    """Upload de arquivo Excel/CSV para importação de usuários."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo não fornecido")
    
    ext = file.filename.split('.')[-1].lower()
    if ext not in ['xlsx', 'xls', 'csv']:
        raise HTTPException(
            status_code=400, 
            detail="Formato não suportado. Use Excel (.xlsx, .xls) ou CSV"
        )
    
    file_id = str(uuid.uuid4())
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"user_import_{file_id}.{ext}")
    
    content = await file.read()
    with open(file_path, 'wb') as f:
        f.write(content)
    
    temp_user_files[file_id] = file_path
    
    return {"file_id": file_id, "filename": file.filename}


@router.get("/import/preview/{file_id}")
async def preview_users_file(
    file_id: str,
    current_user: dict = Depends(get_current_admin)
):
    """Retorna preview do arquivo para mapeamento de colunas."""
    if file_id not in temp_user_files:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    
    file_path = temp_user_files[file_id]
    
    try:
        if file_path.endswith('.csv'):
            df_full = pd.read_csv(file_path)
        else:
            df_full = pd.read_excel(file_path)
        
        columns = df_full.columns.tolist()
        total_rows = len(df_full)
        preview = df_full.head(5).fillna('').to_dict('records')
        
        return {
            "columns": columns,
            "preview": preview,
            "total_rows": total_rows
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler arquivo: {str(e)}")


@router.post("/import/confirm")
async def confirm_users_import(
    data: UserImportConfirm,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Confirma a importação de usuários com mapeamento de colunas."""
    if data.file_id not in temp_user_files:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    
    file_path = temp_user_files[data.file_id]
    
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler arquivo: {str(e)}")
    
    role_map = {
        "administrador": "admin",
        "admin": "admin",
        "gestor": "gestao_rv",
        "gestão": "gestao_rv",
        "gestao": "gestao_rv",
        "broker": "broker",
        "assessor": "broker"
    }
    
    created = 0
    updated = 0
    skipped = 0
    errors = []
    
    for idx, row in df.iterrows():
        try:
            user_data = {}
            
            for target_field, source_col in data.mapping.items():
                if not source_col or source_col not in row.index:
                    continue
                
                value = row[source_col]
                
                if target_field == "phone":
                    user_data["phone"] = normalize_phone(value)
                elif target_field == "role":
                    role_str = normalize_value(value)
                    if role_str:
                        role_lower = role_str.lower()
                        user_data["role"] = role_map.get(role_lower, "broker")
                    else:
                        user_data["role"] = "broker"
                else:
                    user_data[target_field] = normalize_value(value)
            
            email = user_data.get("email")
            if not email or str(email).strip() == "":
                errors.append(f"Linha {idx + 2}: E-mail é obrigatório")
                continue
            
            phone = user_data.get("phone")
            
            existing = None
            if email:
                existing = db.query(User).filter(User.email == email).first()
            
            if not existing and phone:
                existing = db.query(User).filter(User.phone == phone).first()
            
            if existing:
                if data.update_existing:
                    if phone:
                        conflicting = db.query(User).filter(
                            User.phone == phone,
                            User.id != existing.id
                        ).first()
                        if conflicting:
                            errors.append(f"Linha {idx + 2}: Telefone '{phone}' já pertence a outro usuário")
                            continue
                    
                    for key, value in user_data.items():
                        if key not in ["password"] and value is not None:
                            setattr(existing, key, value)
                    updated += 1
                else:
                    skipped += 1
                continue
            
            if phone:
                existing_by_phone = db.query(User).filter(User.phone == phone).first()
                if existing_by_phone:
                    errors.append(f"Linha {idx + 2}: Telefone '{phone}' já existe")
                    continue
            
            username = user_data.get("username")
            if not username:
                first_name = user_data.get("first_name", "")
                full_name = user_data.get("full_name", "")
                if first_name:
                    username = first_name.lower().replace(" ", "_")
                elif full_name:
                    username = full_name.split()[0].lower() if full_name.split() else "user"
                else:
                    username = email.split("@")[0] if email else f"user_{idx}"
            
            base_username = username
            counter = 1
            while db.query(User).filter(User.username == username).first():
                username = f"{base_username}_{counter}"
                counter += 1
            
            random_password = secrets.token_urlsafe(32)
            hashed_password = get_password_hash(random_password)
            
            new_user = User(
                username=username,
                first_name=user_data.get("first_name"),
                full_name=user_data.get("full_name"),
                email=email,
                hashed_password=hashed_password,
                phone=phone,
                role=user_data.get("role", "broker")
            )
            db.add(new_user)
            created += 1
            
        except Exception as e:
            errors.append(f"Linha {idx + 2}: {str(e)}")
    
    db.commit()
    
    if data.file_id in temp_user_files:
        del temp_user_files[data.file_id]
    if os.path.exists(file_path):
        os.remove(file_path)
    
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "success": len(errors) == 0 or created > 0 or updated > 0
    }
