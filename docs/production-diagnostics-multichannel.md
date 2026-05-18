# Diagnóstico de Entregas Multichannel — Produção

Queries SQL para investigar disparos e conversas em produção (Railway).
Execute via Railway → PostgreSQL → Query ou psql.

## 1. Ver dispatches recentes por canal e status

```sql
SELECT
  cd.id,
  cd.assessor_email,
  cd.assessor_phone,
  cd.status,
  cd.channel_id,
  z.label AS channel_label,
  cd.error_message,
  LEFT(cd.api_response, 300) AS api_response_preview,
  cd.sent_at,
  cd.created_at
FROM campaign_dispatches cd
LEFT JOIN zapi_channels z ON z.id = cd.channel_id
ORDER BY cd.id DESC
LIMIT 30;
```

## 2. Resumo de status por canal (campanha específica)

```sql
SELECT
  cd.channel_id,
  z.label AS channel_label,
  cd.status,
  COUNT(*) AS total
FROM campaign_dispatches cd
LEFT JOIN zapi_channels z ON z.id = cd.channel_id
WHERE cd.campaign_id = <ID_DA_CAMPANHA>
GROUP BY cd.channel_id, z.label, cd.status
ORDER BY cd.channel_id, cd.status;
```

## 3. Canais configurados e sua cobertura de assessores

```sql
SELECT
  z.id,
  z.label,
  z.is_legacy,
  z.is_active,
  z.phone_number,
  COUNT(a.id) AS assessores_com_canal_direto,
  (SELECT COUNT(*) FROM unidade_channel_mapping ucm WHERE ucm.channel_id = z.id) AS unidades_mapeadas
FROM zapi_channels z
LEFT JOIN assessores a ON a.channel_id = z.id
GROUP BY z.id, z.label, z.is_legacy, z.is_active, z.phone_number
ORDER BY z.id;
```

## 4. Quantos assessores têm canal atribuído

```sql
SELECT
  COUNT(*) FILTER (WHERE channel_id IS NOT NULL) AS com_canal_direto,
  COUNT(*) FILTER (WHERE channel_id IS NULL AND unidade IS NOT NULL) AS via_unidade_potencial,
  COUNT(*) FILTER (WHERE channel_id IS NULL) AS sem_canal,
  COUNT(*) AS total
FROM assessores;
```

## 5. Mapeamentos unidade → canal existentes

```sql
SELECT ucm.unidade, ucm.channel_id, z.label AS channel_label
FROM unidade_channel_mapping ucm
LEFT JOIN zapi_channels z ON z.id = ucm.channel_id
ORDER BY ucm.unidade;
```

## 6. Conversas sem canal criadas hoje (verificar impacto pós-correção)

```sql
SELECT
  COUNT(*) FILTER (WHERE channel_id IS NULL) AS sem_canal,
  COUNT(*) FILTER (WHERE channel_id IS NOT NULL) AS com_canal,
  COUNT(*) AS total
FROM conversations
WHERE created_at >= CURRENT_DATE;
```

## 7. Mensagens de campanha com/sem channel_id (verificar impacto pós-correção)

```sql
SELECT
  channel_id,
  z.label AS channel_label,
  COUNT(*) AS total
FROM whatsapp_messages wm
LEFT JOIN zapi_channels z ON z.id = wm.channel_id
WHERE wm.is_from_campaign = true
  AND wm.created_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY wm.channel_id, z.label
ORDER BY wm.channel_id;
```

## 8. Conversas de assessores de um canal específico sem channel_id na conversa

```sql
SELECT
  c.id AS conversation_id,
  c.phone,
  c.channel_id AS conv_channel,
  a.id AS assessor_id,
  a.nome AS assessor_nome,
  a.channel_id AS assessor_channel
FROM conversations c
JOIN assessores a ON a.id = c.assessor_id
WHERE a.channel_id IS NOT NULL
  AND c.channel_id IS NULL
LIMIT 50;
```

## Notas de diagnóstico

- Logs `[DISPATCH-FAIL]` nos logs do Railway contêm: `canal`, `assessor`, `motivo`,
  `detalhe` e `api_response` (parcial) para cada falha de envio Z-API.
- Logs `[CAMPAIGN_MSG]` confirmam persistência bem-sucedida com `canal` e `campanha_id`.
- Logs `[CADENCE]` equivalentes para campanhas com cadência.
