"""
Exporta dados do banco de desenvolvimento para arquivos JSON.
Usado para migrar dados para produção.
"""
import os
import sys
import json
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.database import SessionLocal
from database.models import Product, Material, ContentBlock, WhatsAppScript, User, Assessor

def json_serial(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def export_table(db, model, exclude_filter=None):
    query = db.query(model)
    if exclude_filter:
        query = query.filter(exclude_filter)
    rows = query.all()
    
    result = []
    for row in rows:
        d = {}
        for col in row.__table__.columns:
            val = getattr(row, col.name)
            if val is not None:
                if isinstance(val, (datetime, date)):
                    d[col.name] = val.isoformat()
                else:
                    d[col.name] = val
            else:
                d[col.name] = None
        result.append(d)
    return result

def main():
    db = SessionLocal()
    try:
        export = {}
        
        products = export_table(db, Product)
        export['products'] = products
        print(f"Produtos: {len(products)}")
        
        materials = export_table(db, Material)
        export['materials'] = materials
        print(f"Materiais: {len(materials)}")
        
        blocks = export_table(db, ContentBlock)
        export['content_blocks'] = blocks
        print(f"Blocos: {len(blocks)}")
        
        scripts = export_table(db, WhatsAppScript)
        export['whatsapp_scripts'] = scripts
        print(f"Scripts: {len(scripts)}")
        
        users = export_table(db, User)
        export['users'] = users
        print(f"Usuários: {len(users)}")
        
        assessores = export_table(db, Assessor)
        export['assessores'] = assessores
        print(f"Assessores: {len(assessores)}")
        
        output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'seed_data.json')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export, f, ensure_ascii=False, default=json_serial, indent=2)
        
        print(f"\nDados exportados para: {output_path}")
        print(f"Tamanho: {os.path.getsize(output_path) / 1024:.1f} KB")
        
    finally:
        db.close()

if __name__ == '__main__':
    main()
