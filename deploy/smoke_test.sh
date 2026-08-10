#!/usr/bin/env bash
# End-to-end check against the DEPLOYED bot.
#
# Unit tests pass against in-process objects. This exercises the real thing over
# HTTP — including the seams unit tests cannot see: sessions crossing the
# Firestore boundary, secrets arriving from Secret Manager, and the model
# actually answering. Every bug reported from the live bot so far lived in one
# of those seams.
#
#   ./deploy/smoke_test.sh                    # uses the deployed service
#   ./deploy/smoke_test.sh http://localhost:8080
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

G=$'\033[0;32m'; R=$'\033[0;31m'; Y=$'\033[0;33m'; B=$'\033[1m'; D=$'\033[2m'; N=$'\033[0m'

URL="${1:-}"
if [[ -z "$URL" ]]; then
  URL=$(gcloud run services describe khoji --region "${REGION:-asia-south1}" \
        --format='value(status.url)' 2>/dev/null)
fi
[[ -n "$URL" ]] || { echo "${R}could not determine service URL${N}"; exit 1; }

PHONE="smoke-$(date +%s)"          # a fresh session every run
PASS=0; FAIL=0
ok()   { printf "  ${G}✓${N} %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  ${R}✗${N} %s\n" "$1"; FAIL=$((FAIL+1)); }

say() {  # say <text> -> prints the bot's last reply
  curl -s --max-time 45 -X POST "$URL/webhook/test" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"phone":sys.argv[1],"text":sys.argv[2]}))' "$PHONE" "$1")" \
  | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print((d.get("replies") or [""])[-1])
except Exception: print("")'
}

sayall() {  # say <text> -> prints EVERY reply, joined. Some turns answer in two
            # messages (an acknowledgement, then the next question).
  curl -s --max-time 45 -X POST "$URL/webhook/test" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"phone":sys.argv[1],"text":sys.argv[2]}))' "$PHONE" "$1")" \
  | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print("\n".join(d.get("replies") or []))
except Exception: print("")'
}

echo "${B}Khoji.AI smoke test${N}  ${D}$URL${N}"
echo "${D}session: $PHONE${N}"
echo

# ---------------------------------------------------------------- health
echo "${B}health${N}"
H=$(curl -fsS --max-time 30 "$URL/health" 2>/dev/null)
if [[ -z "$H" ]]; then bad "service is not answering"; echo; exit 1; fi
python3 - "$H" <<'PY'
import json,sys
h=json.loads(sys.argv[1])
for k in ("llm","llm_model","store","records"): print(f"    {k}: {h.get(k)}")
PY
grep -q '"llm_ready": *true' <<<"$H" && ok "model key reached the service" || bad "no model key"
grep -q 'FirestoreSessionStore' <<<"$H" && ok "sessions in Firestore" || bad "sessions in memory - they will be lost"
grep -q '"records": *2[0-9][0-9]' <<<"$H" && ok "catalogue loaded" || bad "catalogue looks wrong"

# ------------------------------------------------------------ conversation
echo
echo "${B}conversation (Rajasthan, Class 12, OBC)${N}"
R0=$(say "hi");            grep -qi "call you" <<<"$R0"     && ok "greets and asks the name" || bad "unexpected: ${R0:0:60}"
R1=$(sayall "Farheen"); grep -qi "which state" <<<"$R1"  && ok "accepts the name, asks for state" || bad "unexpected: ${R1:0:60}"
grep -q "Farheen" <<<"$R1" && ok "greets them by name" || bad "name was not used back"
R2=$(say "Rajasthan");     grep -qi "studying" <<<"$R2"    && ok "accepts state, asks level" || bad "unexpected: ${R2:0:60}"
R3=$(say "1");             grep -qi "class" <<<"$R3"       && ok "school -> asks class" || bad "unexpected: ${R3:0:60}"
R4=$(say "12");            grep -qi "category" <<<"$R4"    && ok "accepts class, asks category" || bad "unexpected: ${R4:0:60}"
R5=$(say "3");             grep -qi "income" <<<"$R5"      && ok "accepts category, asks income" || bad "unexpected: ${R5:0:60}"
RA=$(say "2.5 lakh");      grep -qi "after this" <<<"$RA"  && ok "asks the aspiration question" || bad "unexpected: ${RA:0:60}"
R6=$(say "1")
grep -qiE "found|couldn.t find" <<<"$R6" && ok "returns a result list" || bad "unexpected: ${R6:0:60}"
grep -qi "best match first" <<<"$R6" && ok "explains its ordering" || bad "ordering not explained"
grep -qE "🔭|for later" <<<"$R6" && ok "shows a plan-ahead result" \
  || bad "no plan-ahead bucket for a Class 12 student"

# --------------------------------------------- the three reported bugs
echo
echo "${B}regressions reported from the live bot${N}"
R7=$(say "1")
if grep -q "between 1 and 0" <<<"$R7"; then
  bad "BUG: still offering 'a number between 1 and 0'"
elif grep -qiE "why this matches|apply on|official" <<<"$R7"; then
  ok "picking '1' opens the detail (shortlist survived storage)"
else
  bad "picking '1' gave: ${R7:0:70}"
fi

R8=$(say "2")
grep -qiE "why this matches|apply on|official" <<<"$R8" \
  && ok "picking another number still works" || bad "picking '2' gave: ${R8:0:70}"

RM=$(say "more")
grep -qiE "about this scholarship" <<<"$RM" && ok "'more' explains the scheme in plain language" \
  || bad "'more' gave: ${RM:0:70}"
RD=$(say "documents")
grep -qiE "where to get it|documents you" <<<"$RD" && ok "'documents' says where each paper comes from" \
  || bad "'documents' gave: ${RD:0:70}"

# order must not change between messages
A=$(say "restart" >/dev/null; say "Farheen" >/dev/null; say "Rajasthan" >/dev/null; \
    say "1" >/dev/null; say "12" >/dev/null; say "3" >/dev/null; \
    say "2.5 lakh" >/dev/null; say "1")
FIRST_A=$(grep -o '\*1\.\*.*' <<<"$R6" | head -1)
FIRST_B=$(grep -o '\*1\.\*.*' <<<"$A" | head -1)
[[ "$FIRST_A" == "$FIRST_B" ]] && ok "same profile gives the same top result" \
  || bad "ordering changed between identical searches"

# ------------------------------------------------------------- language
echo
echo "${B}language (needs the model)${N}"
PHONE="smoke-hi-$(date +%s)"
say "hi" >/dev/null
RH=$(say "मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, OBC, आय ढाई लाख")
if grep -qE "[ऀ-ॿ]" <<<"$RH"; then ok "replies in Hindi to a Hindi message"
elif grep -qiE "found|couldn.t find|category|income" <<<"$RH"; then
  bad "understood it but replied in English (translation may be off)"
else bad "Hindi message gave: ${RH:0:70}"; fi

PHONE="smoke-hg-$(date +%s)"
say "hi" >/dev/null
RG=$(say "mai Rajasthan me rehta hun, class 12, OBC, ghar ki aay 2 lakh")
if grep -qiE "maine yeh samjha|sahi hai" <<<"$RG"; then
  ok "reads Roman-script Hindi and replies in it"
elif grep -qE "[ऀ-ॿ]" <<<"$RG"; then
  bad "answered Hinglish in Devanagari - not the script they typed in"
else bad "Hinglish message gave: ${RG:0:70}"; fi

# -------------------------------------------------------------- summary
echo
if (( FAIL == 0 )); then
  echo "${G}${B}all $PASS checks passed${N} — safe to demo"
else
  echo "${R}${B}$FAIL failed${N}, $PASS passed"
fi
echo
echo "${D}Try it yourself: ${URL}/demo${N}"
exit $(( FAIL > 0 ))
