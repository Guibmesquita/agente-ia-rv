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
    # Task #222 — Perfil interno usado APENAS pelo modo "Finalizar disparos
    # agora". NÃO é selecionável na criação ou no PATCH /cadence-profile —
    # `list_profiles()` o omite e os endpoints de troca rejeitam "turbo".
    # Intervalos comprimidos (30-90s entre envios), cooldown global mínimo
    # (30s), pausa longa curta (60-90s) e soft cap diário 150 contatos.
    # As travas anti-bloqueio fixas (janela 09-18h seg-sex, pausa 20min após
    # 2 falhas Z-API, freio automático em 3+ falhas consecutivas) continuam
    # ativas. Os intervalos de minutos são fracionários propositais — o
    # planner os converte em segundos via _build_turbo_schedule().
    "turbo": {
        "label": "Turbo (finalizar agora)",
        "description": (
            "Modo turbo seguro — comprime o cronograma com intervalo "
            "30-90s. Defesas anti-bloqueio mínimas mantidas."
        ),
        "interval_min": 1,  # placeholder; turbo usa segundos via _build_turbo_schedule
        "interval_max": 2,
        "pause_min": 1,
        "pause_max": 2,
        "cooldown_seconds": 30,
        "daily_limit": 150,
        # Intervalos REAIS em segundos para o turbo (consumidos pelo planner)
        "interval_seconds_min": 30,
        "interval_seconds_max": 90,
        "long_pause_seconds_min": 60,
        "long_pause_seconds_max": 90,
    },
}

DEFAULT_PROFILE = "conservador"
TURBO_PROFILE_NAME = "turbo"

# Perfis selecionáveis pelo usuário (turbo é interno, ativado via finalize-now)
USER_SELECTABLE_PROFILES = ("conservador", "padrao", "acelerado")


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
    """Lista os perfis selecionáveis pelo usuário (omite o ``turbo`` interno)."""
    return {
        key: {
            "name": key,
            "label": PROFILES[key]["label"],
            "description": PROFILES[key]["description"],
            "interval_min": PROFILES[key]["interval_min"],
            "interval_max": PROFILES[key]["interval_max"],
            "pause_min": PROFILES[key]["pause_min"],
            "pause_max": PROFILES[key]["pause_max"],
            "cooldown_seconds": PROFILES[key]["cooldown_seconds"],
            "daily_limit": PROFILES[key]["daily_limit"],
        }
        for key in USER_SELECTABLE_PROFILES
    }


def is_valid_profile(name: Optional[str]) -> bool:
    """True se ``name`` corresponde a um perfil SELECIONÁVEL pelo usuário.
    O perfil interno ``turbo`` é rejeitado aqui de propósito — só pode ser
    ativado via ``POST /cadence-finalize-now``."""
    if not name:
        return False
    return str(name).strip().lower() in USER_SELECTABLE_PROFILES
