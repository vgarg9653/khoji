#!/usr/bin/env bash
# Deploy Khoji.AI to Cloud Run.
#
# Idempotent: safe to re-run. Checks for the things people actually get wrong
# (missing secrets, missing dataset, missing IAM) and says so instead of
# deploying something that will fail at runtime.
set -euo pipefail

PROVIDER="${WHATSAPP_PROVIDER:-}"          # meta | twilio
PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-asia-south1}"
# A Cloud Run service cannot be renamed in place, so `khoji` was deployed
# alongside the original `edudisha` rather than replacing it. The old service is
# deliberately still running: links shared before the rename keep working, and
# both scale to zero so the second one costs nothing. Retire `edudisha` only
# once the Meta webhook points here and no shared link needs it:
#   gcloud run services delete edudisha --region asia-south1
SERVICE="${SERVICE:-khoji}"
META_PHONE_NUMBER_ID="${META_PHONE_NUMBER_ID:-}"   # filled from .env below if unset
from_env() {   # read a key from .env, stripping inline comments
  sed -n "s/^$1=//p" .env 2>/dev/null | head -1 | tr -d '\r' \
    | sed 's/[[:space:]]*#.*$//' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}
# Exported value wins, then .env, then a default. Silently defaulting the
# provider once shipped a Gemini key as an OpenRouter key — the service looked
# healthy and would have failed on the first student message.
LLM_PROVIDER="${LLM_PROVIDER:-$(from_env LLM_PROVIDER)}"
LLM_PROVIDER="${LLM_PROVIDER:-openrouter}"
# LLM_MODEL pins EVERY role to one model and is deliberately not defaulted any
# more: one model doing every job meant one 429 took Hindi, voice notes and
# free-form questions down together, silently, for the rest of the day. Set it
# only to force a single model (OpenRouter, or debugging).
LLM_MODEL="${LLM_MODEL:-$(from_env LLM_MODEL)}"
if [[ -z "$LLM_MODEL" && "$LLM_PROVIDER" != "gemini" ]]; then
  LLM_MODEL="google/gemini-2.5-flash"        # OpenRouter has no role routing
fi
# Per-role models. A different family for the fallback, because a free-tier
# quota is per model — so falling back is capacity, not a downgrade.
MODEL_ROUTER="${MODEL_ROUTER:-$(from_env MODEL_ROUTER)}"
MODEL_GENERATION="${MODEL_GENERATION:-$(from_env MODEL_GENERATION)}"
MODEL_AUDIO="${MODEL_AUDIO:-$(from_env MODEL_AUDIO)}"
MODEL_FALLBACK="${MODEL_FALLBACK:-$(from_env MODEL_FALLBACK)}"

die() { echo "error: $*" >&2; exit 1; }

[[ -n "$PROJECT_ID" ]] || die "set PROJECT_ID (export PROJECT_ID=your-project)"

# Either provider is fine — the bot serves both webhooks from the same service,
# so you can start on Twilio's sandbox and move to Meta later without redeploying
# anything but an environment variable.
if [[ -z "$PROVIDER" ]]; then
  # Read it from .env if the caller did not export it.
  PROVIDER=$(from_env WHATSAPP_PROVIDER)
fi
if [[ -z "$PROVIDER" ]]; then
  # No provider configured yet — deploy the web demo only. This is a valid
  # state: the bot is fully usable at /demo while a WhatsApp number is pending.
  PROVIDER=none
fi
# Same fallback as every other setting: exported value wins, then .env. Without
# this, a value sitting correctly in .env still failed the deploy.
if [[ -z "$META_PHONE_NUMBER_ID" ]]; then
  META_PHONE_NUMBER_ID=$(from_env META_PHONE_NUMBER_ID)
fi
if [[ "$PROVIDER" == "meta" && -z "$META_PHONE_NUMBER_ID" ]]; then
  die "WHATSAPP_PROVIDER=meta but META_PHONE_NUMBER_ID is set nowhere (shell or .env)"
fi
echo "==> WhatsApp provider: $PROVIDER"
command -v gcloud >/dev/null || die "gcloud not installed"

# The image bakes in the dataset, so a stale or missing file ships silently.
DATASET="deliverables/dataset/bot_matching.json"
[[ -f "$DATASET" ]] || die "$DATASET missing — run: python pipeline.py export && python src/make_deliverables.py"

AGE_DAYS=$(( ( $(date +%s) - $(stat -f %m "$DATASET" 2>/dev/null || stat -c %Y "$DATASET") ) / 86400 ))
if (( AGE_DAYS > 7 )); then
  echo "warning: dataset is ${AGE_DAYS} days old. Deadlines go stale fast."
  echo "         re-run: python pipeline.py verify && python pipeline.py export"
  read -rp "Deploy anyway? [y/N] " ok
  [[ "$ok" == "y" || "$ok" == "Y" ]] || exit 1
fi

gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> checking secrets"
case "$PROVIDER" in
  meta)   REQUIRED_SECRETS=(meta-access-token meta-verify-token) ;;
  twilio) REQUIRED_SECRETS=(twilio-auth-token) ;;
  none)   REQUIRED_SECRETS=() ;;
esac
REQUIRED_SECRETS+=(llm-api-key phone-hash-salt)
for s in "${REQUIRED_SECRETS[@]}"; do
  if gcloud secrets describe "$s" >/dev/null 2>&1; then
    echo "    ok   $s"
  else
    echo "    MISSING $s — create it with:"
    echo "      printf '%s' 'VALUE' | gcloud secrets create $s --data-file=-"
    die "missing secret: $s"
  fi
done

echo "==> granting runtime permissions BEFORE deploy"
# Doing this after the deploy meant the first instance booted without Firestore
# access and quietly used in-memory sessions instead.
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
RUNTIME_SA="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for role in roles/datastore.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="$RUNTIME_SA" --role="$role" --condition=None >/dev/null 2>&1 \
    && echo "    ok   $role"
done

echo "==> deploying $SERVICE to $REGION"
ENV_VARS="USE_FIRESTORE=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},LLM_PROVIDER=${LLM_PROVIDER}"
[[ -n "$LLM_MODEL" ]]        && ENV_VARS="${ENV_VARS},LLM_MODEL=${LLM_MODEL}"
[[ -n "$MODEL_ROUTER" ]]     && ENV_VARS="${ENV_VARS},MODEL_ROUTER=${MODEL_ROUTER}"
[[ -n "$MODEL_GENERATION" ]] && ENV_VARS="${ENV_VARS},MODEL_GENERATION=${MODEL_GENERATION}"
[[ -n "$MODEL_AUDIO" ]]      && ENV_VARS="${ENV_VARS},MODEL_AUDIO=${MODEL_AUDIO}"
[[ -n "$MODEL_FALLBACK" ]]   && ENV_VARS="${ENV_VARS},MODEL_FALLBACK=${MODEL_FALLBACK}"
SECRETS="PHONE_HASH_SALT=phone-hash-salt:latest"
case "$PROVIDER" in
  meta)   ENV_VARS="${ENV_VARS},META_PHONE_NUMBER_ID=${META_PHONE_NUMBER_ID}"
          SECRETS="${SECRETS},META_ACCESS_TOKEN=meta-access-token:latest,META_VERIFY_TOKEN=meta-verify-token:latest" ;;
  twilio) SECRETS="${SECRETS},TWILIO_AUTH_TOKEN=twilio-auth-token:latest" ;;
esac
# The LLM key is read under both provider names so one secret works either way.
if [[ "${LLM_PROVIDER}" == "gemini" ]]; then
  SECRETS="${SECRETS},GEMINI_API_KEY=llm-api-key:latest"
else
  SECRETS="${SECRETS},OPENROUTER_API_KEY=llm-api-key:latest"
fi

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5 \
  --timeout 60 \
  --set-env-vars "$ENV_VARS" \
  --set-secrets "$SECRETS"


URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo
echo "==> deployed: $URL"
echo "==> health:"
HEALTH=$(curl -fsS --max-time 30 "$URL/health" 2>/dev/null)
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "    health check failed"

# A deploy that exits 0 can still be running the wrong model or storing sessions
# in memory. Check what is actually live.
if [[ -n "$HEALTH" ]]; then
  echo
  python3 - "$HEALTH" "$LLM_PROVIDER" "$LLM_MODEL" <<'PYEOF'
import json, sys
h = json.loads(sys.argv[1]); want_p, want_m = sys.argv[2], sys.argv[3]
expect = {"gemini": "GeminiLLM", "openrouter": "OpenRouterLLM"}.get(want_p, "NullLLM")
bad = False
if h.get("llm") != expect:
    print(f"  MISMATCH: expected {expect}, service reports {h.get('llm')}"); bad = True
if want_m and h.get("llm_model") != want_m:
    print(f"  MISMATCH: expected model {want_m}, service reports {h.get('llm_model')}"); bad = True
chains = h.get("models") or {}
if chains:
    for role, chain in chains.items():
        print(f"  models[{role}]: {' -> '.join(chain)}")
    if any(len(c) < 2 for c in chains.values()):
        print("  WARNING: a role has no fallback model - one 429 disables it"); bad = True
if not h.get("llm_ready"):
    print("  WARNING: no model key reached the service - bot will be English-only"); bad = True
if h.get("store") != "FirestoreSessionStore":
    print(f"  WARNING: sessions in {h.get('store')} - students lose their place on restart"); bad = True
print("  configuration matches what you asked for" if not bad else
      "  ^ fix the above and re-run ./deploy/deploy.sh")
PYEOF
fi

if [[ "$PROVIDER" == "none" ]]; then
cat <<EOF

No WhatsApp provider configured yet — that is fine. The bot is live and usable:

  Web demo : ${URL}/demo      <- open this on your phone
  Health   : ${URL}/health

When Meta approves your business, set WHATSAPP_PROVIDER=meta in .env, add the
credentials, run ./deploy/push_secrets.sh and re-run this script. The web demo
keeps working alongside WhatsApp.
EOF
elif [[ "$PROVIDER" == "meta" ]]; then
cat <<EOF

Next: point Meta at this service.
  Callback URL : ${URL}/webhook/meta
  Verify token : the value you stored in the meta-verify-token secret
  Subscribe to : messages

Then message your WhatsApp test number.

Confirm /health shows "llm_ready": true and "store": "FirestoreSessionStore".
Anything else means the service is running degraded.
EOF
else
cat <<EOF

Next: point Twilio's WhatsApp Sandbox at this service.
  Console  : Messaging -> Try it out -> Send a WhatsApp message -> Sandbox settings
  "When a message comes in" : ${URL}/webhook/twilio   (HTTP POST)

Then send the join code to +1 415 523 8886 from your phone and say hi.

Confirm /health shows "llm_ready": true and "store": "FirestoreSessionStore".
Anything else means the service is running degraded.
EOF
fi
