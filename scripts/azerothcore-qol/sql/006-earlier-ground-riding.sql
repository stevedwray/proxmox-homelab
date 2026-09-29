-- Homelab QoL: reduce only the ground-riding trainer level gates.
-- WotLK spell IDs: Apprentice Riding (33388, 60%) and Journeyman Riding
-- (33391, 100%). Expert Riding (34090, flying) intentionally remains level 60.
-- trainer_spell is the authoritative world-table source used by every trainer.
-- This migration is idempotent and does not grant riding or mounts to existing
-- characters; it merely makes the normal training available earlier.

UPDATE trainer_spell
SET ReqLevel = 10
WHERE SpellId = 33388;

UPDATE trainer_spell
SET ReqLevel = 20
WHERE SpellId = 33391;
