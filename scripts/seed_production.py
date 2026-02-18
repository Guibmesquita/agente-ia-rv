"""
Seed do banco de produção com dados exportados do desenvolvimento.
Pode ser chamado como script standalone ou importado como módulo.
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from database.database import SessionLocal
from database.models import Product, Material, ContentBlock, WhatsAppScript, User, Assessor


def parse_datetime(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return None


def seed_table(db, model, records, id_field='id', skip_existing_ids=None):
    if not records:
        return 0
    
    existing_ids = set()
    if skip_existing_ids is None:
        try:
            existing = db.query(getattr(model, id_field)).all()
            existing_ids = {getattr(r, id_field) for r in existing}
        except Exception:
            db.rollback()
    else:
        existing_ids = skip_existing_ids
    
    count = 0
    skipped = 0
    for record in records:
        record_id = record.get(id_field)
        if record_id in existing_ids:
            continue
        
        obj = model()
        for col in model.__table__.columns:
            if col.name in record:
                val = record[col.name]
                col_type = str(col.type)
                if val is not None and ('TIMESTAMP' in col_type or 'DateTime' in col_type or 'DATETIME' in col_type):
                    val = parse_datetime(val)
                setattr(obj, col.name, val)
        
        nested = None
        try:
            nested = db.begin_nested()
            db.add(obj)
            nested.commit()
            count += 1
        except IntegrityError:
            if nested:
                nested.rollback()
            skipped += 1
        except Exception as e:
            if nested:
                try:
                    nested.rollback()
                except Exception:
                    pass
            try:
                db.rollback()
            except Exception:
                pass
            print(f"  Erro inesperado ao inserir {model.__tablename__}: {e}")
            skipped += 1
    
    if skipped > 0:
        print(f"  ({skipped} registros duplicados ignorados)")
    
    return count


def update_sequence(db, table_name, id_column='id'):
    try:
        db.execute(text(f"""
            SELECT setval(
                pg_get_serial_sequence('{table_name}', '{id_column}'),
                COALESCE((SELECT MAX({id_column}) FROM {table_name}), 1)
            )
        """))
    except Exception as e:
        print(f"  Aviso: Não foi possível atualizar sequência de {table_name}: {e}")


def run_seed(seed_file=None):
    if seed_file is None:
        seed_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'seed_data.json')
    
    if not os.path.exists(seed_file):
        print(f"Arquivo de seed não encontrado: {seed_file}")
        return False
    
    print(f"Carregando dados de: {seed_file}")
    with open(seed_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    seed_tickers = [p.get('ticker', '') for p in data.get('products', []) if p.get('ticker') and p.get('ticker') != '__SYSTEM_UNASSIGNED__']
    
    db = SessionLocal()
    try:
        if seed_tickers:
            existing_seed_products = db.query(Product).filter(Product.ticker.in_(seed_tickers)).count()
            if existing_seed_products >= len(seed_tickers):
                print(f"Banco já possui {existing_seed_products}/{len(seed_tickers)} produtos do seed. Pulando seed.")
                return True
            elif existing_seed_products > 0:
                print(f"Banco possui {existing_seed_products}/{len(seed_tickers)} produtos do seed. Completando importação...")
        
        print("\n--- Iniciando seed de produção ---")
        
        seed_ids = {r.get('id') for r in data.get('products', []) if r.get('id')}
        all_valid_tickers = set(seed_tickers) | {'__SYSTEM_UNASSIGNED__'}
        orphan_query = db.query(Product).filter(Product.ticker.notin_(all_valid_tickers))
        if seed_ids:
            orphan_query = orphan_query.filter(Product.id.notin_(seed_ids))
        orphan_products = orphan_query.all()
        if orphan_products:
            for op in orphan_products:
                print(f"  Removendo produto órfão: '{op.name}' (ticker: {op.ticker})")
                db.delete(op)
            db.flush()
        
        tables = [
            (User, 'users', data.get('users', [])),
            (Assessor, 'assessores', data.get('assessores', [])),
            (Product, 'products', data.get('products', [])),
            (Material, 'materials', data.get('materials', [])),
            (ContentBlock, 'content_blocks', data.get('content_blocks', [])),
            (WhatsAppScript, 'whatsapp_scripts', data.get('whatsapp_scripts', [])),
        ]
        
        for model, table_name, records in tables:
            n = seed_table(db, model, records)
            print(f"{table_name}: {n} inseridos")
            update_sequence(db, table_name)
        
        db.commit()
        print("\n--- Seed concluído com sucesso! ---")
        print("Os embeddings serão criados automaticamente na próxima inicialização do app.")
        return True
        
    except Exception as e:
        db.rollback()
        print(f"\nErro durante seed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == '__main__':
    success = run_seed()
    sys.exit(0 if success else 1)
