-- Place the Draenei-start heirloom vendor at the verified Ammen Vale ground
-- height, alongside the normal starter NPC rather than below the terrain.
START TRANSACTION;

UPDATE creature
SET zoneId = 0,
    areaId = 0,
    position_x = -3960.000,
    position_y = -13927.000,
    position_z = 101.2380,
    orientation = 4.18890
WHERE id = 601100
  AND map = 530
  AND Comment = 'Homelab QoL heirloom vendor: draenei start';

COMMIT;
