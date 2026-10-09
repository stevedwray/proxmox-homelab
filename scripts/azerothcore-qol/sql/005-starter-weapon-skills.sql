-- Homelab QoL: grant each new character all normal WotLK weapon skills for
-- their class. This deliberately excludes armor/shield proficiencies, dual
-- wield, combat spells, talents, and every invalid class/weapon combination.
START TRANSACTION;

INSERT INTO playercreateinfo_skills (raceMask, classMask, skill, `rank`, `comment`)
VALUES
    -- Warrior
    (0, 1, 43, 0, 'Homelab QoL: Warrior one-handed swords'),
    (0, 1, 44, 0, 'Homelab QoL: Warrior axes'),
    (0, 1, 45, 0, 'Homelab QoL: Warrior bows'),
    (0, 1, 46, 0, 'Homelab QoL: Warrior guns'),
    (0, 1, 54, 0, 'Homelab QoL: Warrior maces'),
    (0, 1, 55, 0, 'Homelab QoL: Warrior two-handed swords'),
    (0, 1, 136, 0, 'Homelab QoL: Warrior staves'),
    (0, 1, 160, 0, 'Homelab QoL: Warrior two-handed maces'),
    (0, 1, 172, 0, 'Homelab QoL: Warrior two-handed axes'),
    (0, 1, 173, 0, 'Homelab QoL: Warrior daggers'),
    (0, 1, 176, 0, 'Homelab QoL: Warrior thrown weapons'),
    (0, 1, 226, 0, 'Homelab QoL: Warrior crossbows'),
    (0, 1, 229, 0, 'Homelab QoL: Warrior polearms'),
    (0, 1, 473, 0, 'Homelab QoL: Warrior fist weapons'),
    -- Paladin
    (0, 2, 43, 0, 'Homelab QoL: Paladin one-handed swords'),
    (0, 2, 44, 0, 'Homelab QoL: Paladin axes'),
    (0, 2, 54, 0, 'Homelab QoL: Paladin maces'),
    (0, 2, 55, 0, 'Homelab QoL: Paladin two-handed swords'),
    (0, 2, 160, 0, 'Homelab QoL: Paladin two-handed maces'),
    (0, 2, 172, 0, 'Homelab QoL: Paladin two-handed axes'),
    (0, 2, 229, 0, 'Homelab QoL: Paladin polearms'),
    -- Hunter
    (0, 4, 43, 0, 'Homelab QoL: Hunter one-handed swords'),
    (0, 4, 44, 0, 'Homelab QoL: Hunter axes'),
    (0, 4, 45, 0, 'Homelab QoL: Hunter bows'),
    (0, 4, 46, 0, 'Homelab QoL: Hunter guns'),
    (0, 4, 55, 0, 'Homelab QoL: Hunter two-handed swords'),
    (0, 4, 136, 0, 'Homelab QoL: Hunter staves'),
    (0, 4, 172, 0, 'Homelab QoL: Hunter two-handed axes'),
    (0, 4, 173, 0, 'Homelab QoL: Hunter daggers'),
    (0, 4, 176, 0, 'Homelab QoL: Hunter thrown weapons'),
    (0, 4, 226, 0, 'Homelab QoL: Hunter crossbows'),
    (0, 4, 229, 0, 'Homelab QoL: Hunter polearms'),
    (0, 4, 473, 0, 'Homelab QoL: Hunter fist weapons'),
    -- Rogue
    (0, 8, 43, 0, 'Homelab QoL: Rogue one-handed swords'),
    (0, 8, 45, 0, 'Homelab QoL: Rogue bows'),
    (0, 8, 46, 0, 'Homelab QoL: Rogue guns'),
    (0, 8, 54, 0, 'Homelab QoL: Rogue maces'),
    (0, 8, 173, 0, 'Homelab QoL: Rogue daggers'),
    (0, 8, 176, 0, 'Homelab QoL: Rogue thrown weapons'),
    (0, 8, 226, 0, 'Homelab QoL: Rogue crossbows'),
    (0, 8, 473, 0, 'Homelab QoL: Rogue fist weapons'),
    -- Priest
    (0, 16, 54, 0, 'Homelab QoL: Priest maces'),
    (0, 16, 136, 0, 'Homelab QoL: Priest staves'),
    (0, 16, 173, 0, 'Homelab QoL: Priest daggers'),
    (0, 16, 228, 0, 'Homelab QoL: Priest wands'),
    -- Death Knight
    (0, 32, 43, 0, 'Homelab QoL: Death Knight one-handed swords'),
    (0, 32, 44, 0, 'Homelab QoL: Death Knight axes'),
    (0, 32, 54, 0, 'Homelab QoL: Death Knight maces'),
    (0, 32, 55, 0, 'Homelab QoL: Death Knight two-handed swords'),
    (0, 32, 160, 0, 'Homelab QoL: Death Knight two-handed maces'),
    (0, 32, 172, 0, 'Homelab QoL: Death Knight two-handed axes'),
    (0, 32, 229, 0, 'Homelab QoL: Death Knight polearms'),
    -- Shaman
    (0, 64, 44, 0, 'Homelab QoL: Shaman axes'),
    (0, 64, 54, 0, 'Homelab QoL: Shaman maces'),
    (0, 64, 136, 0, 'Homelab QoL: Shaman staves'),
    (0, 64, 173, 0, 'Homelab QoL: Shaman daggers'),
    (0, 64, 473, 0, 'Homelab QoL: Shaman fist weapons'),
    -- Mage and Warlock
    (0, 128, 43, 0, 'Homelab QoL: Mage one-handed swords'),
    (0, 128, 136, 0, 'Homelab QoL: Mage staves'),
    (0, 128, 173, 0, 'Homelab QoL: Mage daggers'),
    (0, 128, 228, 0, 'Homelab QoL: Mage wands'),
    (0, 256, 43, 0, 'Homelab QoL: Warlock one-handed swords'),
    (0, 256, 136, 0, 'Homelab QoL: Warlock staves'),
    (0, 256, 173, 0, 'Homelab QoL: Warlock daggers'),
    (0, 256, 228, 0, 'Homelab QoL: Warlock wands'),
    -- Druid
    (0, 1024, 54, 0, 'Homelab QoL: Druid maces'),
    (0, 1024, 136, 0, 'Homelab QoL: Druid staves'),
    (0, 1024, 160, 0, 'Homelab QoL: Druid two-handed maces'),
    (0, 1024, 173, 0, 'Homelab QoL: Druid daggers'),
    (0, 1024, 229, 0, 'Homelab QoL: Druid polearms'),
    (0, 1024, 473, 0, 'Homelab QoL: Druid fist weapons')
ON DUPLICATE KEY UPDATE
    `rank` = VALUES(`rank`),
    `comment` = VALUES(`comment`);

COMMIT;
