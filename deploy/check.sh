#!/usr/bin/env bash
# Where am I? Run this any time during setup.
#
# Checks each prerequisite in the order the walkthrough needs them and stops at
# the first thing that is not done, so you always have exactly one next action.

set -uo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; BOLD='\033[1m'; NC='\033[0m'

ok()    { printf "  ${GREEN}✅${NC} %s\n" "$1"; }
bad()   { printf "  ${RED}❌${NC} %s\n" "$1"; }
warn()  { printf "  ${YELLOW}⚠️${NC}  %s\n" "$1"; }
step()  { printf "\n${BOLD}%s${NC}\n" "$1"; }

NEXT=""
note_next() { [[ -z "$NEXT" ]] && NEXT="$1"; return 0; }

cd "$(dirname "$0")/.." || exit 1

printf "${BOLD}Khoji.AI — setup progress${NC}\n"

# ---------------------------------------------------------------- step 1
step "STEP 1 — tools on your laptop"
if command -v gcloud >/dev/null 2>&1; then
  ok "gcloud installed ($(gcloud --version 2>/dev/null | head -1))"
else
  bad "gcloud not installed"
  note_next "Install gcloud:  brew install --cask google-cloud-sdk"
fi
command -v python3 >/dev/null 2>&1 && ok "python3 installed" || bad "python3 missing"

# ---------------------------------------------------------------- step 2
step "STEP 2 — the dataset the bot serves"
DATASET="deliverables/dataset/bot_matching.json"
if [[ -f "$DATASET" ]]; then
  COUNT=$(python3 -c "import json;print(len(json.load(open('$DATASET'))))" 2>/dev/null || echo "?")
  AGE=$(( ( $(date +%s) - $(stat -f %m "$DATASET" 2>/dev/null || stat -c %Y "$DATASET" 2>/dev/null) ) / 86400 ))
  ok "$DATASET ($COUNT scholarships, ${AGE} days old)"
  (( AGE > 7 )) && warn "more than a week old — re-run: python pipeline.py verify && python pipeline.py export"
else
  bad "dataset missing"
  note_next "Build it:  python pipeline.py export && python src/make_deliverables.py"
fi

# ---------------------------------------------------------------- step 3
step "STEP 3 — Google Cloud login and project"
if command -v gcloud >/dev/null 2>&1; then
  ACCOUNT=$(gcloud config get-value account 2>/dev/null)
  if [[ -n "$ACCOUNT" && "$ACCOUNT" != "(unset)" ]]; then
    ok "logged in as $ACCOUNT"
  else
    bad "not logged in"
    note_next "Log in:  gcloud auth login"
  fi

  PROJECT=$(gcloud config get-value project 2>/dev/null)
  if [[ -n "$PROJECT" && "$PROJECT" != "(unset)" ]]; then
    ok "project set to $PROJECT"
  else
    bad "no project selected"
    note_next "Create/select a project — see docs/SETUP.md step 4"
  fi

  if [[ -n "${PROJECT:-}" && "$PROJECT" != "(unset)" ]]; then
    # ------------------------------------------------------------ step 4
    step "STEP 4 — APIs enabled"
    ENABLED=$(gcloud services list --enabled --format='value(config.name)' 2>/dev/null)
    for api in run.googleapis.com firestore.googleapis.com \
               secretmanager.googleapis.com cloudbuild.googleapis.com; do
      if grep -q "^${api}$" <<<"$ENABLED"; then ok "$api"; else
        bad "$api not enabled"
        note_next "Enable APIs — see docs/SETUP.md step 5"
      fi
    done

    # ------------------------------------------------------------ step 5
    step "STEP 5 — Firestore database"
    if gcloud firestore databases list --format='value(name)' 2>/dev/null | grep -q .; then
      ok "Firestore database exists"
    else
      bad "no Firestore database"
      note_next "Create it:  gcloud firestore databases create --location=asia-south1"
    fi

    # ------------------------------------------------------------ step 6
    step "STEP 6 — secrets in Secret Manager"
    # Which secrets matter depends on the WhatsApp provider chosen in .env.
    WA=$(sed -n 's/^WHATSAPP_PROVIDER=//p' .env 2>/dev/null | sed 's/[[:space:]]*#.*//' | tr -d ' \r')
    NEEDED="llm-api-key"
    case "$WA" in
      meta)   NEEDED="$NEEDED meta-access-token meta-verify-token" ;;
      twilio) NEEDED="$NEEDED twilio-auth-token" ;;
      *)      warn "WHATSAPP_PROVIDER not set in .env — only the LLM key is checked" ;;
    esac
    for s in $NEEDED; do
      if gcloud secrets describe "$s" >/dev/null 2>&1; then ok "$s stored"; else
        bad "$s missing"
        note_next "Push your .env into Secret Manager:  ./deploy/push_secrets.sh"
      fi
    done

    # ------------------------------------------------------------ step 7
    step "STEP 7 — deployed service"
    REGION="${REGION:-asia-south1}"
    URL=$(gcloud run services describe khoji --region "$REGION" \
          --format='value(status.url)' 2>/dev/null)
    if [[ -n "$URL" ]]; then
      ok "deployed at $URL"
      HEALTH=$(curl -fsS --max-time 25 "$URL/health" 2>/dev/null)
      if [[ -n "$HEALTH" ]]; then
        ok "health check responding"
        grep -q '"gemini": *true' <<<"$HEALTH" && ok "Gemini connected" \
          || warn "Gemini NOT connected — bot works, but English-only"
        grep -q 'FirestoreSessionStore' <<<"$HEALTH" && ok "Firestore connected" \
          || warn "using in-memory sessions — students lose their place on restart"
        echo "     webhook URL for Meta:  ${URL}/webhook/meta"
      else
        bad "service deployed but not responding"
        note_next "Check logs:  gcloud run services logs read khoji --region $REGION --limit 50"
      fi
    else
      bad "not deployed yet"
      note_next "Deploy:  export PROJECT_ID=$PROJECT META_PHONE_NUMBER_ID=xxx && ./deploy/deploy.sh"
    fi
  fi
fi

echo
if [[ -n "$NEXT" ]]; then
  printf "${BOLD}👉 YOUR NEXT STEP:${NC}\n   %s\n\n" "$NEXT"
else
  printf "${GREEN}${BOLD}🎉 Everything is set up.${NC}\n"
  printf "   Last thing: point Meta's webhook at the URL above and send a test message.\n\n"
fi
