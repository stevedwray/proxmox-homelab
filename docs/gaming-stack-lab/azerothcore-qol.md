# AzerothCore quality-of-life profile

This is the deliberate gameplay profile for the private LAN-only WotLK realm.
It keeps questing, class chains, normal combat, and dungeon progression intact,
while removing routine administration from a party made up of one human player
and their Altbots.

## Agreed rules

| Area | Decision |
|---|---|
| Human players | Maximum two; LAN only. |
| Bots | Persistent player-created Altbots for the long-term party. No random roaming bots. |
| Experience | `1.25x` for all XP categories. |
| Questing | Normal quest and class-quest progression; do not grant quest completions or bypass attunements. |
| Training and upkeep | Altbots use Playerbot `maintenance`: spells/skills, repairs, consumables, enchants, and bags. This intentionally removes trainer and vendor errands. |
| Gear | Keep normal drops and upgrades. Do not enable automatic BiS/epic gearing. Playerbot `autogear match` remains an occasional catch-up tool, not the normal progression path. |
| Gold | Not a constraint. Characters receive enough starting money for ordinary travel and incidental costs; bot upkeep is supplied through `maintenance`. |
| Heirlooms | Free at character creation/start-of-play, using a dedicated vendor rather than requiring emblems, PvP, or an auction economy. |
| Bags | Every Altbot receives four maximum-size general bags at first provisioning; no bag-management loop. |
| Appearance | Transmog is enabled with normal weapon, armor, class, and proficiency restrictions and a nominal or zero price. |
| Looting | Area loot is enabled for grouped play at a conservative 20-yard radius. |

## What exists already

- The Playerbot fork is live and has no random-bot autologin or roaming.
- The server permits four deliberately added party bots and four prepared
  AddClass accounts. AddClass remains a testing/convenience feature; new
  long-term companions should be ordinary characters used as Altbots.
- Playerbot's `maintenance` and Altbot `autogear` facilities are already
  available in the fork. The operator should use `maintenance` in party chat
  after creating an Altbot and at level milestones. Do not use `autogear bis`.
- **Completed 2026-09-29:** the live Panel configuration sets
  `RATE_XP_KILL`, `RATE_XP_QUEST`, and `RATE_XP_EXPLORE` to `1.25`; money,
  reputation, and honor remain `1`.
- **Completed 2026-09-29:** the pinned Playerbot checkout now includes
  `mod-transmog` `0d85cbc53d63ce2df8527169ce6ae47f5f6f6ba8` and
  `mod-aoe-loot` `57279b660a278e9b3a1afa425e7c7a5edc72b7bb`. Automatic
  source updates are disabled. The rebuilt authserver/worldserver listen
  normally on TCP 3724/8085; Transmog's character tables exist.
- **Completed 2026-09-29:** new characters receive 10,000g and four equipped
  22-slot Glacial Bags. Existing character Aldred was topped up to 10,000g.

## Delivery plan

### Phase 1 — safe live configuration — completed 2026-09-29

Change only the existing Pterodactyl server's XP-rate variables from `1` to
`1.25`, preserving every non-XP rate at `1`. Restart the server and verify a
login, XP gain, and the existing game-slot interlock. This does not rebuild the
core or touch characters, quests, the world database, or the other game
servers.

The Panel accepted the startup update while preserving all 52 server variables.
After the restart, `worldserver`, `authserver`, and MySQL were running; the
world and authentication sockets were listening on TCP 8085 and 3724.

### Phase 2 — controlled module build — completed 2026-09-29

The existing egg already persists the Playerbot source checkout and supports
module installation through `ACORE_MODULES`; a separate image registry and
image change are unnecessary. The live baseline is Playerbot core
`7f12e89ee5f467a50e62eba1d525eac7dc953d03` (branch `Playerbot`) and
Playerbot module `7bae1b5c58c76a0aa20381155edc08096d1485b2` (branch
`master`).

Before adding modules, set `AUTO_UPDATE=0`. This freezes the known-working
core and prevents a routine restart from silently pulling a newer core or
module revision. Add and build these modules through the existing egg:

- `azerothcore/mod-transmog`;
- `azerothcore/mod-aoe-loot`.

Record the resulting module commits immediately after the initial build. Keep
the configuration overlays and database SQL versioned in this repository,
rather than relying on undocumented edits. Configure AoE loot for group use,
a 20-yard range, no login spam, and fast decay of looted corpses. Configure
Transmog to accept heirlooms but retain ordinary equipability restrictions.
Back up the live database and server volume before the build; a failed module
build rolls back by restoring the prior checkout/database backup and removing
the module list.

The deployed configuration makes Transmog free, retains its ordinary item
restrictions, disables portable Transmog, and enables grouped AoE loot at 20
yards with no login message or overflow mail. `Rate.Corpse.Decay.Looted` is
`0.01`. An operator gameplay check remains: use a Transmog NPC and loot a
nearby group of corpses.

### Phase 3a — starter money and bags — completed 2026-09-29

The egg's native `START_PLAYER_MONEY` setting is `100000000` copper (10,000g).
The idempotent world migration
`scripts/azerothcore-qol/sql/001-starter-package.sql` adds four `41600`
Glacial Bags for every valid race/class creation template. AzerothCore equips
new bags in available bag slots during character creation, rather than placing
them loose in the initial inventory. Existing characters are intentionally not
given bags retrospectively; existing Aldred was topped up to the same 10,000g
floor.

The originally deployed `41597` Abyssal Bag was discovered to be a
Warlock-only Soul Bag. **Corrected 2026-09-29:** migration
`003-fix-starter-bag.sql` replaced the global creation row with the largest
ordinary all-class alternative, the 22-slot Glacial Bag (`41600`). It does not
alter existing character inventories. After the restart, only the `41600 × 4`
row remained and both realm services were listening normally.

The server was restarted to reload the world create-item cache. `worldserver`
and `authserver` were verified listening on TCP 8085 and 3724 after the
change. A short-lived newly created character remains the operator gameplay
check for the four equipped bags.

### Phase 3b — free heirloom vendor — completed 2026-09-29

Ship a small, versioned world/character database customization. It must
provide:

- a free heirloom vendor in each playable starting area, containing only
  WotLK-appropriate heirlooms;
- an idempotent migration, so a restart or image update cannot duplicate
  vendor stock.

The vendor is intentionally not a source of normal combat upgrades, materials,
profession rewards, or reputation rewards. Class quests, quest rewards, and
dungeon drops remain meaningful.

The proposed migration uses a separate Ethereal vendor template (`601100`),
cloned only for its visual model from the Transmog Ethereal (`190011`). It has
no Transmog script, so it cannot replace or break the existing Transmog NPC.
It stocks 39 curated level-appropriate WotLK heirloom equipment items for zero
cost, respecting the normal item faction/class restrictions. Nine spawns cover
the distinct initial areas (including the shared death-knight area); shared
race starts share one vendor.

The migration was imported into the live world database and server 4 was
restarted. The vendor has 39 stock records and nine spawn records; both
`authserver` and `worldserver` resumed listening on TCP 3724 and 8085.

**Corrected 2026-09-29:** the Ammen Vale vendor was initially placed below the
nearby verified terrain height. Migration
`004-fix-draenei-heirloom-vendor-placement.sql` moves only that spawn beside
the normal Draenei starter NPC at its confirmed ground height.

### Phase 4 — controlled cutover

Take a database and server-volume backup, stop server 4, change only its
approved startup variables and required configuration, then start it under the
existing shared game-slot lock. Verify module migrations, an existing
character, a new Altbot, free heirloom issue, bags, Transmog NPC interaction,
AoE looting, and LAN login. Retain the previous source checkout/module list
and database backup as rollback points.

## Explicit non-goals

- no random/world-roaming bots;
- no automatic quest completion, leveling, or dungeon clears;
- no unrestricted race/class combinations;
- no automatic BiS or raid-tier equipment;
- no changes to ARK, Minecraft, allocations, firewall, or the game-slot
  interlock.

## Operator commands after delivery

For a new permanent companion, create the normal character, invite it, then:

```text
.playerbots bot add CharacterName
/p maintenance
```

Use `/p autogear match` only as an explicit catch-up action. The MultiBot
client addon remains recommended for issuing those commands without chat
macros.
