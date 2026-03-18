-- Production cleanup: Ghost materials in Railway DB
-- Executed: 2026-03-18
-- Database: Railway PostgreSQL (tramway.proxy.rlwy.net:45306/railway)
--
-- BEFORE cleanup:
--   Total materials: 123
--   Ghost (duplicado bloqueado + 0 blocks): 46
--   Ghost (success + 0 blocks + 0 files): 12
--   Total to delete: 58
--
-- AFTER cleanup:
--   Remaining materials: 65
--   With content_blocks: 65
--   With material_files: 11

-- Step 1: Dry-run verification (SELECT before DELETE)
-- SELECT m.id, m.name, m.processing_status, m.processing_error
-- FROM materials m
-- WHERE (
--   (m.processing_error LIKE '%duplicado bloqueado%'
--    AND NOT EXISTS (SELECT 1 FROM content_blocks cb WHERE cb.material_id = m.id))
--   OR
--   (m.processing_status = 'success'
--    AND NOT EXISTS (SELECT 1 FROM content_blocks cb WHERE cb.material_id = m.id)
--    AND NOT EXISTS (SELECT 1 FROM material_files mf WHERE mf.material_id = m.id))
-- );

-- Step 2: Cleanup (executed in transaction)
BEGIN;

CREATE TEMP TABLE ghost_ids AS
  SELECT m.id FROM materials m
  WHERE m.processing_error LIKE '%duplicado bloqueado%'
    AND NOT EXISTS (SELECT 1 FROM content_blocks cb WHERE cb.material_id = m.id)
  UNION
  SELECT m.id FROM materials m
  WHERE m.processing_status = 'success'
    AND NOT EXISTS (SELECT 1 FROM content_blocks cb WHERE cb.material_id = m.id)
    AND NOT EXISTS (SELECT 1 FROM material_files mf WHERE mf.material_id = m.id);

DELETE FROM document_page_results WHERE job_id IN (
  SELECT dpj.id FROM document_processing_jobs dpj WHERE dpj.material_id IN (SELECT id FROM ghost_ids)
);
DELETE FROM upload_queue_items WHERE material_id IN (SELECT id FROM ghost_ids);
DELETE FROM document_processing_jobs WHERE material_id IN (SELECT id FROM ghost_ids);
DELETE FROM ingestion_logs WHERE material_id IN (SELECT id FROM ghost_ids);
DELETE FROM material_files WHERE material_id IN (SELECT id FROM ghost_ids);
DELETE FROM content_blocks WHERE material_id IN (SELECT id FROM ghost_ids);
DELETE FROM materials WHERE id IN (SELECT id FROM ghost_ids);

DROP TABLE ghost_ids;

COMMIT;

-- Results:
-- DELETE 24 (document_page_results)
-- DELETE 59 (upload_queue_items)
-- DELETE 12 (document_processing_jobs)
-- DELETE 12 (ingestion_logs)
-- DELETE 0  (material_files)
-- DELETE 0  (content_blocks)
-- DELETE 58 (materials)
