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
- The existing live rates are still `1x` until the explicitly approved Panel
  configuration change below is made.

## Delivery plan

### Phase 1 — safe live configuration

Change only the existing Pterodactyl server's XP-rate variables from `1` to
`1.25`, preserving every non-XP rate at `1`. Restart the server and verify a
login, XP gain, and the existing game-slot interlock. This does not rebuild the
core or touch characters, quests, the world database, or the other game
servers.

### Phase 2 — reproducible QoL image

Create a dedicated, pinned image fork from the exact Playerbot source revision
currently running in the realm. Add and build these pinned modules together:

- `azerothcore/mod-transmog`;
- `azerothcore/mod-aoe-loot`.

The image must include versioned configuration overlays and database migration
files, rather than manually editing a running game-server container. Configure
AoE loot for group use, a 20-yard range, no login spam, and fast decay of
looted corpses. Configure Transmog to accept heirlooms but retain ordinary
equipability restrictions. Run its migration on a disposable copy of the live
database before any production cutover.

### Phase 3 — starter provisioning

Ship a small, versioned world/character database customization with the QoL
image. It must provide:

- a free heirloom vendor in each playable starting area, containing only
  WotLK-appropriate heirlooms;
- four maximum-size bags for each provisioned Altbot;
- a generous starter-gold grant for each human or Altbot character;
- idempotent migrations, so a restart or image update cannot duplicate gold,
  bags, or vendor stock.

The vendor is intentionally not a source of normal combat upgrades, materials,
profession rewards, or reputation rewards. Class quests, quest rewards, and
dungeon drops remain meaningful.

### Phase 4 — controlled cutover

Build and scan the image, take a database backup, stop server 4, change only
its image and required configuration, then start it under the existing shared
game-slot lock. Verify module migrations, an existing character, a new Altbot,
free heirloom issue, bags, Transmog NPC interaction, AoE looting, and LAN
login. Retain the previous image and database backup as rollback points.

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
