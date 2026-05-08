"""
Perfis de velocidade da cadência de envio de campanhas WhatsApp (Task #220).

Cada perfil define:
- ``interval_min`` / ``interval_max``: faixa de minutos entre envios consecutivos
  (sorteada com ``random.randint``).
- ``pause_min`` / ``pause_max``: duração da pausa longa que ocorre a cada bloco
  de 10 a 12 envios.
- ``cooldown_seconds``: cooldown global entre dois disparos quaisquer aplicado
  pelo motor (``run_cadence_tick``), independente de qual campanha está ativa.
- ``daily_limit``: limite diário sugerido quando o usuário não preenche um
  valor explícito ao criar a campanha.

As travas anti-bloqueio fixas (janela 09h-18h seg-sex, pausa de almoço,
pausa de 20min após 2 falhas Z-API consecutivas, randomização) NÃO são
configuráveis e permanecem iguais para todos os perfis.

O perfil padrão é ``conservador`` — replica exatamente o comportamento que
o sistema tinha antes da Task #220, então é seguro para campanhas em curso.
"""

from typing import Dict, Any, Optional


PROFILES: Dict[str, Dict[str, Any]] = {
    "conservador": {
        "label": "Conservador",
        "description": (
            "Mais lento, menor risco de bloqueio. Recomendado para números "
            "novos ou pouco aquecidos. (8-25 min entre envios)"
        ),
        "interval_min": 8,
        "interval_max": 25,
        "pause_min": 15,
        "pause_max": 30,
        "cooldown_seconds": 480,
        "daily_limit": 50,
    },
    "padrao": {
        "label": "Padrão",
        "description": (
            "Equilíbrio entre velocidade e segurança. Para números já "
            "aquecidos com histórico estável. (4-12 min entre envios)"
        ),
        "interval_min": 4,
        "interval_max": 12,
        "pause_min": 10,
        "pause_max": 20,
        "cooldown_seconds": 240,
        "daily_limit": 80,
    },
    "acelerado": {
        "label": "Acelerado",
        "description": (
            "Mais rápido, exige número bem aquecido. Use só se o número "
            "já enviou volume alto sem bloqueios. (2-6 min entre envios)"
        ),
        "interval_min": 2,
        "interval_max": 6,
        "pause_min": 8,
        "pause_max": 15,
        "cooldown_seconds": 120,
        "daily_limit": 120,
    },
}

DEFAULT_PROFILE = "conservador"


def get_profile(name: Optional[str]) -> Dict[str, Any]:
    """
    Retorna o dicionário de configuração do perfil. Se o nome for inválido,
    nulo ou desconhecido, devolve o perfil padrão (conservador) — nunca
    levanta exceção, pois isso é chamado dentro do motor de envio.
    """
    if not name:
        return PROFILES[DEFAULT_PROFILE]
    key = str(name).strip().lower()
    return PROFILES.get(key, PROFILES[DEFAULT_PROFILE])


def list_profiles() -> Dict[str, Dict[str, Any]]:
    """Lista todos os perfis disponíveis (para serialização em endpoints)."""
    return {
        key: {
            "name": key,
            "label": cfg["label"],
            "description": cfg["description"],
            "interval_min": cfg["interval_min"],
            "interval_max": cfg["interval_max"],
            "pause_min": cfg["pause_min"],
            "pause_max": cfg["pause_max"],
            "cooldown_seconds": cfg["cooldown_seconds"],
            "daily_limit": cfg["daily_limit"],
        }
        for key, cfg in PROFILES.items()
    }


def is_valid_profile(name: Optional[str]) -> bool:
    """True se ``name`` corresponde a um perfil conhecido."""
    if not name:
        return False
    return str(name).strip().lower() in PROFILES
