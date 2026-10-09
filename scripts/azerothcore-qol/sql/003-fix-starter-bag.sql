-- Correct the original starter package: 41597 is a Warlock-only Soul Bag.
-- 41600 (Glacial Bag) is the largest ordinary WotLK bag usable by all classes.
START TRANSACTION;

DELETE FROM playercreateinfo_item
WHERE race = 0 AND class = 0 AND itemid = 41597;

INSERT INTO playercreateinfo_item (race, class, itemid, amount, Note)
VALUES (0, 0, 41600, 4, 'Homelab QoL: four equipped 22-slot Glacial Bags')
ON DUPLICATE KEY UPDATE amount = VALUES(amount), Note = VALUES(Note);

COMMIT;
