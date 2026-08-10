#!/usr/bin/env bash
# Guided secrets setup for Khoji.AI.
#
# Walks through every key the bot needs, one at a time: what it is, where to get
# it, and whether you can skip it for now. Values are written to .env, which is
# git-ignored. Nothing is ever printed back in full — only masked.
#
#   ./deploy/setup_secrets.sh            walk through everything missing
#   ./deploy/setup_secrets.sh --check    just show what is set and what isn't
#   ./deploy/setup_secrets.sh --reset K  re-enter one key

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

ENV_FILE=".env"
TEMPLATE=".env.example"

B=$'\033[1m'; G=$'\033[0;32m'; Y=$'\033[0;33m'; R=$'\033[0;31m'; D=$'\033[2m'; N=$'\033[0m'

mask() {                                    # never echo a secret in full
  local v="$1"
  [[ -z "$v" ]] && { echo "${D}(not set)${N}"; return; }
  local n=${#v}
  (( n <= 8 )) && { echo "${G}set${N} ${D}(${n} chars)${N}"; return; }
  echo "${G}${v:0:4}…${v: -4}${N} ${D}(${n} chars)${N}"
}

get_val() {                                 # read a key out of .env
  # Strips inline comments and surrounding whitespace. Without this,
  # "LLM_PROVIDER=openrouter   # openrouter | gemini" reads as the whole
  # 48-character line, and every downstream comparison silently fails.
  [[ -f "$ENV_FILE" ]] || { echo ""; return; }
  sed -n "s/^$1=//p" "$ENV_FILE" | head -1 | tr -d '\r' \
    | sed 's/[[:space:]]*#.*$//' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

set_val() {                                 # write/replace a key in .env
  local k="$1" v="$2"
  if grep -q "^${k}=" "$ENV_FILE" 2>/dev/null; then
    # portable in-place edit (BSD sed on macOS needs the empty -i arg)
    local tmp; tmp=$(mktemp)
    awk -v k="$k" -v v="$v" -F= '
      $1==k { print k "=" v; next } { print }' "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$k" "$v" >> "$ENV_FILE"
  fi
  chmod 600 "$ENV_FILE"
}

ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$TEMPLATE" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "${G}Created $ENV_FILE${N} from $TEMPLATE (permissions 600 — only you can read it)"
  fi
}

# key | required? | where to get it | what it is
prompt_for() {
  local key="$1" need="$2" url="$3" what="$4" how="${5:-}"
  local cur; cur=$(get_val "$key")

  echo
  echo "${B}${key}${N}  $( [[ $need == yes ]] && echo "${R}required${N}" || echo "${D}optional${N}" )"
  echo "  $what"
  [[ -n "$url" ]] && echo "  ${D}Get it: ${url}${N}"
  [[ -n "$how" ]] && echo "  ${D}${how}${N}"
  echo "  Currently: $(mask "$cur")"

  if [[ -n "$cur" ]]; then
    read -rp "  Keep it? [Y/n] " k
    [[ "$k" =~ ^[Nn] ]] || return 0
  fi

  read -rp "  Paste value (blank to skip): " val
  if [[ -n "$val" ]]; then
    set_val "$key" "$val"
    echo "  ${G}saved${N} $(mask "$val")"
  else
    echo "  ${Y}skipped${N}"
  fi
}

generate_for() {                            # secrets you invent, not fetch
  local key="$1" what="$2" cmd="$3"
  local cur; cur=$(get_val "$key")
  echo
  echo "${B}${key}${N}  ${R}required${N}"
  echo "  $what"
  echo "  Currently: $(mask "$cur")"
  if [[ -n "$cur" ]]; then
    read -rp "  Keep it? [Y/n] " k
    [[ "$k" =~ ^[Nn] ]] || return 0
  fi
  read -rp "  Generate one automatically? [Y/n] " g
  if [[ "$g" =~ ^[Nn] ]]; then
    read -rp "  Paste your own: " val
  else
    val=$(eval "$cmd")
    echo "  ${D}generated with: $cmd${N}"
  fi
  [[ -n "$val" ]] && { set_val "$key" "$val"; echo "  ${G}saved${N} $(mask "$val")"; }
}

# ── --check ────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--check" ]]; then
  ensure_env
  echo "${B}Khoji.AI — secrets status${N}  ${D}($ENV_FILE)${N}"
  echo
  missing_required=0
  for row in \
    "LLM_PROVIDER|no|which model provider" \
    "OPENROUTER_API_KEY|maybe|OpenRouter key (if LLM_PROVIDER=openrouter)" \
    "GEMINI_API_KEY|maybe|Gemini key (if LLM_PROVIDER=gemini)" \
    "WHATSAPP_PROVIDER|no|twilio or meta" \
    "TWILIO_AUTH_TOKEN|maybe|Twilio auth token (if provider=twilio)" \
    "META_PHONE_NUMBER_ID|maybe|WhatsApp sender id (if provider=meta)" \
    "META_ACCESS_TOKEN|maybe|WhatsApp access token (if provider=meta)" \
    "META_VERIFY_TOKEN|maybe|webhook verify token (if provider=meta)" \
    "PHONE_HASH_SALT|yes|salt for hashing phone numbers"
  do
    IFS='|' read -r k need desc <<<"$row"
    v=$(get_val "$k")
    if [[ -z "$v" && "$need" == yes ]]; then
      printf "  ${R}✗${N} %-24s %s\n" "$k" "$desc"; missing_required=1
    elif [[ -z "$v" ]]; then
      printf "  ${Y}·${N} %-24s %s\n" "$k" "$desc"
    else
      printf "  ${G}✓${N} %-24s %s\n" "$k" "$(mask "$v")"
    fi
  done
  echo
  # An LLM key is only required if a provider that needs one was chosen.
  wa=$(get_val WHATSAPP_PROVIDER)
  case "$wa" in
    twilio) [[ -z "$(get_val TWILIO_AUTH_TOKEN)" ]] && \
      echo "  ${R}WHATSAPP_PROVIDER=twilio but TWILIO_AUTH_TOKEN is empty${N}" ;;
    meta) for k in META_PHONE_NUMBER_ID META_ACCESS_TOKEN META_VERIFY_TOKEN; do
            [[ -z "$(get_val $k)" ]] && echo "  ${R}WHATSAPP_PROVIDER=meta but $k is empty${N}"
          done ;;
    *) echo "  ${Y}WHATSAPP_PROVIDER not set — run setup to choose Twilio or Meta${N}" ;;
  esac
  prov=$(get_val LLM_PROVIDER)
  case "$prov" in
    openrouter) [[ -z "$(get_val OPENROUTER_API_KEY)" ]] && \
      echo "  ${Y}LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is empty — bot will run English-only${N}" ;;
    gemini) [[ -z "$(get_val GEMINI_API_KEY)" ]] && \
      echo "  ${Y}LLM_PROVIDER=gemini but GEMINI_API_KEY is empty — bot will run English-only${N}" ;;
  esac
  (( missing_required )) && echo "  ${D}Run ./deploy/setup_secrets.sh to fill these in.${N}"
  exit 0
fi

# ── walkthrough ────────────────────────────────────────────────────────
ensure_env

cat <<EOF
${B}Khoji.AI — secrets setup${N}

I'll take you through each key: what it does, where to get it, and whether you
can skip it for now. Everything is written to ${B}.env${N}, which git ignores.

${D}Nothing you paste is shown back in full or printed to any log.${N}
${D}Press Enter to skip any key and come back later.${N}
EOF

echo
echo "${B}── 1 of 4 · Language model ─────────────────────────────────${N}"
echo "${D}Lets the bot understand Hindi, Hinglish and voice notes."
echo "Skip it and the bot still works — English, numbered menus only.${N}"
echo
echo "  a) OpenRouter — one key, any model, swap by editing LLM_MODEL"
echo "  b) Gemini direct — cheaper if you have Google credits"
read -rp "  Which? [a/b/skip] " which
case "$which" in
  a|A) set_val LLM_PROVIDER openrouter
       prompt_for OPENROUTER_API_KEY yes "https://openrouter.ai/keys" \
         "Powers language understanding, translation and voice." \
         "Sign in → Create Key. Pay-as-you-go, no minimum."
       ;;
  b|B) set_val LLM_PROVIDER gemini
       prompt_for GEMINI_API_KEY yes "https://aistudio.google.com/apikey" \
         "Powers language understanding, translation and voice." \
         "Create API key. Generous free tier."
       ;;
  *)   set_val LLM_PROVIDER none
       echo "  ${Y}Skipped — bot will run in English with numbered menus.${N}" ;;
esac

echo
echo "${B}── 2 of 4 · WhatsApp ───────────────────────────────────────${N}"
echo "  a) Twilio Sandbox — works today, no Meta business verification"
echo "  b) Meta Cloud API — free for user-started chats, needs an approved business"
read -rp "  Which? [a/b/skip] " wa

if [[ "$wa" =~ ^[aA] ]]; then
  set_val WHATSAPP_PROVIDER twilio
  echo "${D}From console.twilio.com → Account Info (SID and token are on the dashboard).${N}"
  prompt_for TWILIO_ACCOUNT_SID no "https://console.twilio.com" \
    "Your Twilio Account SID (starts with AC)." \
    "On the console home page under Account Info."
  prompt_for TWILIO_AUTH_TOKEN yes "https://console.twilio.com" \
    "Your Twilio Auth Token — also proves inbound webhooks really came from Twilio." \
    "Click 'show' next to Auth Token on the console home page."
  echo
  echo "  ${D}Sandbox number is shared: +1 415 523 8886${N}"
  echo "  ${D}Join it from your phone with the code Twilio shows you.${N}"
elif [[ "$wa" =~ ^[bB] ]]; then
  set_val WHATSAPP_PROVIDER meta
  echo "${D}From developers.facebook.com → your app → WhatsApp → API Setup."
  echo "Full walkthrough: docs/SETUP.md steps 2-5.${N}"

  prompt_for META_PHONE_NUMBER_ID yes \
  "https://developers.facebook.com/apps" \
  "The 'Phone number ID' on the API Setup page." \
  "A long number — NOT your phone number itself."

  prompt_for META_ACCESS_TOKEN yes \
    "https://developers.facebook.com/apps" \
    "Lets the bot send replies." \
    "The temporary token expires in 24h. docs/SETUP.md step 14 makes a permanent one."

  generate_for META_VERIFY_TOKEN \
    "A password YOU invent, shared with Meta so each side can recognise the other. Paste the same value into Meta's webhook config." \
    "openssl rand -hex 16"
else
  echo "  ${Y}Skipped — set this up before you can message anyone.${N}"
fi

echo
echo "${B}── 3 of 4 · Privacy ────────────────────────────────────────${N}"
generate_for PHONE_HASH_SALT \
  "Used to hash students' phone numbers before storing them, so the database never holds a readable number. Changing it later makes existing sessions unreadable." \
  "openssl rand -hex 32"

echo
echo "${B}── 4 of 4 · Google Cloud ───────────────────────────────────${N}"
echo "${D}Only needed when deploying. Skip if you're running locally.${N}"
prompt_for GOOGLE_CLOUD_PROJECT no "" \
  "Your GCP project id (docs/SETUP.md step 7)." \
  "Leave blank until you deploy."

echo
echo "${G}${B}Done.${N} Secrets are in ${B}.env${N} (permissions 600, git-ignored)."
echo
echo "Next:"
echo "  ./deploy/setup_secrets.sh --check     see what's still missing"
echo "  ./.venv/bin/python bot/simulate.py    try the bot locally"
echo
echo "${D}When you deploy, these move to Google Secret Manager — .env stays local.${N}"
