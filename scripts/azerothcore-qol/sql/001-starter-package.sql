-- AzerothCore private-realm starter package.
-- race=0/class=0 expands to every valid playable race/class. Player creation
-- attempts to equip bags before it considers backpack storage.
START TRANSACTION;

INSERT INTO `playercreateinfo_item` (`race`, `class`, `itemid`, `amount`, `Note`)
VALUES (0, 0, 41597, 4, 'Homelab QoL: four equipped 32-slot Abyssal Bags')
ON DUPLICATE KEY UPDATE
    `amount` = VALUES(`amount`),
    `Note` = VALUES(`Note`);

COMMIT;
