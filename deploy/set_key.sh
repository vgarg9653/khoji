#!/usr/bin/env bash
# Set one secret in .env without it ever appearing in your shell history or in
# a chat transcript.
#
#   ./deploy/set_key.sh GEMINI_API_KEY
#
# It prompts, and the input is hidden as you type (like a password field).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

KEY="${1:-}"
[[ -n "$KEY" ]] || { echo "usage: ./deploy/set_key.sh VARIABLE_NAME"; exit 1; }
[[ -f .env ]] || { echo "error: .env not found"; exit 1; }

# -s hides the typed characters, so the value never renders on screen and never
# reaches ~/.zsh_history the way an inline command argument would.
printf 'Paste value for %s (input hidden), then press Enter:\n> ' "$KEY"
read -rs VALUE
echo

[[ -n "$VALUE" ]] || { echo "nothing entered; unchanged"; exit 1; }

tmp=$(mktemp)
awk -v k="$KEY" -v v="$VALUE" '
  BEGIN { done=0 }
  $0 ~ "^" k "=" { print k "=" v; done=1; next }
  { print }
  END { if (!done) print k "=" v }
' .env > "$tmp"
mv "$tmp" .env
chmod 600 .env

n=${#VALUE}
if (( n > 8 )); then echo "saved ${KEY}=${VALUE:0:4}…${VALUE: -4} (${n} chars)"
else echo "saved ${KEY} (${n} chars)"; fi
