-- Homelab QoL: free WotLK heirloom vendors in each distinct starting area.
--
-- Entry 601100 is deliberately a separate template cloned from the Ethereal
-- Transmog appearance (190011). It is a normal vendor, not the Transmog
-- script NPC, so either can be changed without affecting the other.
START TRANSACTION;

DELETE FROM npc_vendor WHERE entry = 601100;
DELETE FROM creature WHERE id = 601100;
DELETE FROM creature_template_model WHERE CreatureID = 601100;
DELETE FROM creature_template WHERE entry = 601100;

CREATE TEMPORARY TABLE homelab_heirloom_vendor_template LIKE creature_template;
INSERT INTO homelab_heirloom_vendor_template
SELECT * FROM creature_template WHERE entry = 190011;
UPDATE homelab_heirloom_vendor_template
SET entry = 601100,
    name = 'Ethereal Heirloom Quartermaster',
    subname = 'Free Heirlooms',
    gossip_menu_id = 0,
    npcflag = 128,
    ScriptName = '';
INSERT INTO creature_template SELECT * FROM homelab_heirloom_vendor_template;
DROP TEMPORARY TABLE homelab_heirloom_vendor_template;

INSERT INTO creature_template_model (CreatureID, Idx, CreatureDisplayID, DisplayScale, Probability, VerifiedBuild)
SELECT 601100, Idx, CreatureDisplayID, DisplayScale, Probability, VerifiedBuild
FROM creature_template_model
WHERE CreatureID = 190011;

-- Explicitly curated WotLK heirloom gear only. Excludes the Quality=7 test
-- shoulder, level-80 inscriptions, Wintergrasp commendation, and flight tome.
SET @slot := 0;
INSERT INTO npc_vendor (entry, slot, item, maxcount, incrtime, ExtendedCost, VerifiedBuild)
SELECT 601100, (@slot := @slot + 1), entry, 0, 0, 0, 0
FROM item_template
WHERE entry IN (
    38691,
    42943, 42944, 42945, 42946, 42947, 42948, 42949, 42950, 42951, 42952,
    42984, 42985, 42991, 42992,
    44091, 44092, 44093, 44094, 44095, 44096, 44097, 44098, 44099, 44100,
    44101, 44102, 44103, 44105, 44107,
    48677, 48683, 48685, 48687, 48689, 48691, 48716, 48718, 50255
)
ORDER BY entry;

-- Nine distinct initial areas: human; orc/troll; dwarf/gnome; night elf;
-- undead; tauren; blood elf; draenei; and the shared death-knight start.
-- The small coordinate offsets avoid spawning directly on the player.
INSERT INTO creature
    (id, map, zoneId, areaId, spawnMask, phaseMask, equipment_id,
     position_x, position_y, position_z, orientation, spawntimesecs,
     wander_distance, MovementType, npcflag, unit_flags, dynamicflags,
     ScriptName, CreateObject, Comment)
VALUES
    (601100,   0,   12, 0, 1, 1, 0, -8946.45,   -128.993,    83.5312, 0.00000, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: human start'),
    (601100,   1,   14, 0, 1, 1, 0,  -615.018, -4248.170,    38.7180, 0.00000, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: orc/troll start'),
    (601100,   0,    1, 0, 1, 1, 0, -6236.820,   334.533,   382.7580, 6.17716, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: dwarf/gnome start'),
    (601100,   1,  141, 0, 1, 1, 0, 10314.800,   835.963,  1326.4100, 5.69632, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: night elf start'),
    (601100,   0,   85, 0, 1, 1, 0,  1680.210,  1681.810,   121.6700, 2.70526, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: undead start'),
    (601100,   1,  215, 0, 1, 1, 0, -2914.080,  -254.480,    52.9968, 0.00000, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: tauren start'),
    (601100, 530, 3431, 0, 1, 1, 0, 10353.100, -6353.790,    33.4026, 5.31605, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: blood elf start'),
    (601100, 530,    0, 0, 1, 1, 0, -3960.000,-13927.000,   101.2380, 4.18890, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: draenei start'),
    (601100, 609, 4298, 0, 1, 1, 0,  2361.940, -5658.270,   426.0280, 3.65997, 120, 0, 0, 128, 0, 0, '', 0, 'Homelab QoL heirloom vendor: death knight start');

COMMIT;
