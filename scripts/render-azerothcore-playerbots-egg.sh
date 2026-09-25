#!/usr/bin/env bash
# Render the reviewed, interlocked AzerothCore Playerbots egg for manual Panel
# import. The artifact is deliberately ignored: its pinned upstream source and
# transformation live here in version control.
set -euo pipefail

readonly upstream_commit="78ba322bcf79fce44b1ecc994483add8d0350054"
readonly upstream_url="https://raw.githubusercontent.com/Nazgile94/pelican-acore/${upstream_commit}/egg-azerothcore-aio.json"
readonly egg_uuid="e18b4c81-c51c-4a98-a984-8f218d0a37d6"

repo_root=$(git rev-parse --show-toplevel)
output_path=${1:-"${repo_root}/docs/gaming-stack-lab/artifacts/azerothcore-playerbots-interlocked-egg.json"}
temp_path=$(mktemp)
trap 'rm -f "$temp_path"' EXIT

mkdir -p "$(dirname "$output_path")"
curl -fsSL "$upstream_url" -o "$temp_path"

jq \
  --arg uuid "$egg_uuid" \
  --arg startup "command -v flock >/dev/null 2>&1 || { echo 'GAME SLOT INTERLOCK ERROR: flock is unavailable in this image.'; exit 69; }; exec 9</game-slot/active.lock; if ! flock -n -E 75 9; then echo 'GAME SLOT BUSY: another game server is already running on this node.'; exit 75; fi; exec bash ./start.sh" \
  '
  .name = "AzerothCore WotLK Playerbots (game-slot interlocked)"
  | .uuid = $uuid
  | .description = "Private two-human WotLK realm with party-only Playerbots. Requires the read-only /game-slot mount."
  | .startup = $startup
  | .variables |= map(
      if .env_variable == "USE_PLAYERBOTS" then .default_value = "1" | .user_editable = false
      elif .env_variable == "MAP_UPDATE_THREADS" then .default_value = "4" | .user_editable = false
      elif .env_variable == "PLAYER_LIMIT" then .default_value = "2" | .user_editable = false
      elif (.env_variable | startswith("RATE_")) then .default_value = "1" | .user_editable = false
      else .
      end
    )
  | .variables += [
      {
        name: "Disable Playerbots random autologin",
        description: "Keeps random roaming bots offline; party bots are added deliberately.",
        env_variable: "AC_AI_PLAYERBOT_RANDOM_BOT_AUTOLOGIN",
        default_value: "0", user_viewable: true, user_editable: false,
        rules: "required|boolean", sort: 1000, field_type: "text"
      },
      {
        name: "Minimum random bots",
        description: "Private realm policy: no roaming random bots.",
        env_variable: "AC_AI_PLAYERBOT_MIN_RANDOM_BOTS",
        default_value: "0", user_viewable: true, user_editable: false,
        rules: "required|integer|min:0", sort: 1001, field_type: "text"
      },
      {
        name: "Maximum random bots",
        description: "Private realm policy: no roaming random bots.",
        env_variable: "AC_AI_PLAYERBOT_MAX_RANDOM_BOTS",
        default_value: "0", user_viewable: true, user_editable: false,
        rules: "required|integer|min:0", sort: 1002, field_type: "text"
      },
      {
        name: "Maximum deliberate party bots",
        description: "Maximum bots a player can control simultaneously.",
        env_variable: "AC_AI_PLAYERBOT_MAX_ADDED_BOTS",
        default_value: "4", user_viewable: true, user_editable: false,
        rules: "required|integer|min:0|max:40", sort: 1003, field_type: "text"
      },
      {
        name: "AddClass account pool size",
        description: "One account pool is sufficient for this private realm and its deliberate party bots.",
        env_variable: "AC_AI_PLAYERBOT_ADD_CLASS_ACCOUNT_POOL_SIZE",
        default_value: "1", user_viewable: true, user_editable: false,
        rules: "required|integer|min:0|max:1000", sort: 1004, field_type: "text"
      }
    ]
  ' "$temp_path" > "$output_path"

jq -e \
  --arg uuid "$egg_uuid" \
  '
  .meta.version == "PTDL_v2"
  and .uuid == $uuid
  and (.startup | contains("/game-slot/active.lock"))
  and (.startup | contains("flock -n -E 75"))
  and ([.variables[] | select(.env_variable == "USE_PLAYERBOTS").default_value] == ["1"])
  and ([.variables[] | select(.env_variable == "AC_AI_PLAYERBOT_RANDOM_BOT_AUTOLOGIN").default_value] == ["0"])
  and ([.variables[] | select(.env_variable == "AC_AI_PLAYERBOT_MAX_ADDED_BOTS").default_value] == ["4"])
  ' "$output_path" >/dev/null

printf 'Rendered %s\n' "$output_path"
