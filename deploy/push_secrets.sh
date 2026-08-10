#!/usr/bin/env bash
# Copy the secrets in .env into Google Secret Manager.
#
# .env is for local development. Cloud Run reads from Secret Manager instead,
# so nothing sensitive is baked into the container image or passed as a plain
# environment variable in the deploy command (where it would show up in
# `gcloud run services describe` and in your shell history).
#
# Re-runnable: adds a new *version* of an existing secret rather than failing.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

G=$'\033[0;32m'; R=$'\033[0;31m'; Y=$'\033[0;33m'; B=$'\033[1m'; D=$'\033[2m'; N=$'\033[0m'
die() { echo "${R}error:${N} $*" >&2; exit 1; }

[[ -f .env ]] || die ".env not found — run ./deploy/setup_secrets.sh first"
command -v gcloud >/dev/null || die "gcloud not installed"

PROJECT=$(gcloud config get-value project 2>/dev/null)
[[ -n "$PROJECT" && "$PROJECT" != "(unset)" ]] || die "no project set (gcloud config set project ...)"

get() {  # read a key from .env, stripping inline comments
  sed -n "s/^$1=//p" .env | head -1 | tr -d '\r' \
    | sed 's/[[:space:]]*#.*$//' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

mask() { local v="$1"; local n=${#v}; (( n<=8 )) && echo "(${n} chars)" || echo "${v:0:4}…${v: -4}"; }

put() {  # put SECRET_NAME "value"
  local name="$1" value="$2"
  [[ -z "$value" ]] && { echo "  ${Y}·${N} $name — empty in .env, skipped"; return; }
  if gcloud secrets describe "$name" --project="$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- \
      --project="$PROJECT" >/dev/null 2>&1 \
      && echo "  ${G}✓${N} $name updated  $(mask "$value")" \
      || echo "  ${R}✗${N} $name failed to update"
  else
    printf '%s' "$value" | gcloud secrets create "$name" --data-file=- \
      --replication-policy=automatic --project="$PROJECT" >/dev/null 2>&1 \
      && echo "  ${G}✓${N} $name created  $(mask "$value")" \
      || echo "  ${R}✗${N} $name failed to create"
  fi
}

echo "${B}Pushing secrets to Secret Manager${N}  ${D}(project: $PROJECT)${N}"
echo

LLM_PROVIDER=$(get LLM_PROVIDER)
WA=$(get WHATSAPP_PROVIDER)

# One secret name for the model key, whichever provider it belongs to. The
# deploy maps it to GEMINI_API_KEY or OPENROUTER_API_KEY as appropriate.
case "$LLM_PROVIDER" in
  gemini)     put llm-api-key "$(get GEMINI_API_KEY)" ;;
  openrouter) put llm-api-key "$(get OPENROUTER_API_KEY)" ;;
  *)          echo "  ${Y}·${N} LLM_PROVIDER is '${LLM_PROVIDER:-unset}' — no model key pushed" ;;
esac

case "$WA" in
  meta)   put meta-access-token "$(get META_ACCESS_TOKEN)"
          put meta-verify-token "$(get META_VERIFY_TOKEN)" ;;
  twilio) put twilio-auth-token "$(get TWILIO_AUTH_TOKEN)" ;;
  *)      echo "  ${Y}·${N} WHATSAPP_PROVIDER is '${WA:-unset}' — no WhatsApp secret pushed" ;;
esac

put phone-hash-salt "$(get PHONE_HASH_SALT)"

echo
echo "${D}.env stays on your laptop and is git-ignored. Cloud Run reads these."
echo "Rotate a key by editing .env and re-running this script.${N}"
echo
echo "Next:  ./deploy/deploy.sh"
