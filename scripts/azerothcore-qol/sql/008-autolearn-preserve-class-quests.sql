-- Apply after mod-autolearn's supplied mod_autolearn.sql.
-- Preserve flavourful class quest rewards: the module must teach only normal
-- trainer spells on level-up, not class mounts/forms that normally come from
-- quests or Shaman starter totems.

DELETE FROM mod_autolearn_extra_spells
WHERE spell_id IN (
    5784, 13819, 34769, 23161, 23214, 34767, -- Warlock/Paladin mounts
    40120                                     -- Druid Swift Flight Form
);
