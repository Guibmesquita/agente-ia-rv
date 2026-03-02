"""
Script para configurar os webhooks da Z-API.
Registra o endpoint de webhook do sistema na instância Z-API.
"""
import os
import httpx

def configure_webhooks():
    instance_id = os.getenv("ZAPI_INSTANCE_ID")
    token = os.getenv("ZAPI_TOKEN")
    client_token = os.getenv("ZAPI_CLIENT_TOKEN")
    
    if not all([instance_id, token, client_token]):
        print("Erro: Credenciais Z-API não configuradas")
        print(f"  ZAPI_INSTANCE_ID: {'OK' if instance_id else 'MISSING'}")
        print(f"  ZAPI_TOKEN: {'OK' if token else 'MISSING'}")
        print(f"  ZAPI_CLIENT_TOKEN: {'OK' if client_token else 'MISSING'}")
        return False
    
    base_url = os.getenv("APP_BASE_URL", "")
    if not base_url:
        domain = os.getenv("REPLIT_DEV_DOMAIN", "")
        if domain:
            base_url = f"https://{domain}"
    if not base_url:
        print("Erro: APP_BASE_URL nao configurado")
        return False
    
    webhook_url = f"{base_url.rstrip('/')}/api/webhook/zapi"
    
    url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/update-every-webhooks"
    
    headers = {
        "Client-Token": client_token,
        "Content-Type": "application/json"
    }
    
    payload = {
        "value": webhook_url,
        "notifySentByMe": True
    }
    
    print(f"Configurando webhooks Z-API...")
    print(f"  URL do webhook: {webhook_url}")
    print(f"  Endpoint Z-API: {url}")
    
    try:
        with httpx.Client(timeout=30) as client:
            response = client.put(url, headers=headers, json=payload)
            
            print(f"  Status: {response.status_code}")
            print(f"  Resposta: {response.text}")
            
            if response.status_code == 200:
                print("\nWebhooks configurados com sucesso!")
                return True
            else:
                print(f"\nErro ao configurar webhooks: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"\nErro de conexão: {e}")
        return False

if __name__ == "__main__":
    configure_webhooks()
