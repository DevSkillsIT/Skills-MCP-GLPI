-- Extract GLPI tickets as raw JSONL (one JSON object per line) for the KB.
-- Adapted from scripts/glpi_export_db_tickets/build.sql: same nested
-- requesters/technicians/follow-ups/solutions, plus a recency window and a
-- resolved-status filter so only useful, current solutions are indexed.
--
-- HTML stays raw and names are included; cleaning/normalization happens in
-- ticket_document.py. date_mod is exposed for the incremental change gate.
--
-- Placeholders are substituted by ingest_tickets.py before the SQL is piped to
-- the remote mysql client (the MySQL CLI has no bind-parameter support):
--   __MAX_AGE_MONTHS__  -> integer (recency window, e.g. 18)
--   __STATUS_LIST__     -> comma-separated GLPI status codes (e.g. 5,6)
SELECT JSON_OBJECT(
  'id',               t.id,
  'titulo',           t.name,
  'data_abertura',    t.date,
  'data_solucao',     t.solvedate,
  'data_fechamento',  t.closedate,
  'data_modificacao', t.date_mod,
  'status_cod',       t.status,
  'tipo_cod',         t.type,
  'urgencia_cod',     t.urgency,
  'impacto_cod',      t.impact,
  'prioridade_cod',   t.priority,
  'categoria',        cat.completename,
  'localizacao',      loc.completename,
  'entidade',         ent.completename,
  'origem',           req.name,
  'tempo_total_seg',  t.actiontime,
  'descricao_html',   t.content,
  'solicitantes', (
      SELECT JSON_ARRAYAGG(COALESCE(NULLIF(TRIM(CONCAT(COALESCE(u.realname,''),' ',COALESCE(u.firstname,''))),''), u.name))
      FROM glpi_tickets_users tu JOIN glpi_users u ON u.id=tu.users_id
      WHERE tu.tickets_id=t.id AND tu.type=1),
  'tecnicos', (
      SELECT JSON_ARRAYAGG(COALESCE(NULLIF(TRIM(CONCAT(COALESCE(u.realname,''),' ',COALESCE(u.firstname,''))),''), u.name))
      FROM glpi_tickets_users tu JOIN glpi_users u ON u.id=tu.users_id
      WHERE tu.tickets_id=t.id AND tu.type=2),
  'observadores', (
      SELECT JSON_ARRAYAGG(COALESCE(NULLIF(TRIM(CONCAT(COALESCE(u.realname,''),' ',COALESCE(u.firstname,''))),''), u.name))
      FROM glpi_tickets_users tu JOIN glpi_users u ON u.id=tu.users_id
      WHERE tu.tickets_id=t.id AND tu.type=3),
  'grupos_atribuidos', (
      SELECT JSON_ARRAYAGG(g.completename)
      FROM glpi_groups_tickets gt JOIN glpi_groups g ON g.id=gt.groups_id
      WHERE gt.tickets_id=t.id AND gt.type=2),
  'acompanhamentos', (
      SELECT JSON_ARRAYAGG(JSON_OBJECT(
                'data',       f.date,
                'autor',      COALESCE(NULLIF(TRIM(CONCAT(COALESCE(fu.realname,''),' ',COALESCE(fu.firstname,''))),''), fu.name),
                'privado',    f.is_private,
                'texto_html', f.content))
      FROM glpi_itilfollowups f LEFT JOIN glpi_users fu ON fu.id=f.users_id
      WHERE f.itemtype='Ticket' AND f.items_id=t.id),
  'solucoes', (
      SELECT JSON_ARRAYAGG(JSON_OBJECT(
                'data',       s.date_creation,
                'autor',      COALESCE(NULLIF(TRIM(CONCAT(COALESCE(su.realname,''),' ',COALESCE(su.firstname,''))),''), su.name),
                'tipo',       s.solutiontype_name,
                'status_cod', s.status,
                'texto_html', s.content))
      FROM glpi_itilsolutions s LEFT JOIN glpi_users su ON su.id=s.users_id
      WHERE s.itemtype='Ticket' AND s.items_id=t.id)
)
FROM glpi_tickets t
LEFT JOIN glpi_itilcategories cat ON cat.id=t.itilcategories_id
LEFT JOIN glpi_locations      loc ON loc.id=t.locations_id
LEFT JOIN glpi_entities       ent ON ent.id=t.entities_id
LEFT JOIN glpi_requesttypes   req ON req.id=t.requesttypes_id
WHERE t.is_deleted=0
  AND t.status IN (__STATUS_LIST__)
  AND t.date >= DATE_SUB(NOW(), INTERVAL __MAX_AGE_MONTHS__ MONTH)
ORDER BY t.id;
