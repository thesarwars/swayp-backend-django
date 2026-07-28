#!/usr/bin/env bash
#
# CI gate for BRD §3.4 / E1-S6: raw bank numbers must never be stored.
#
# Fails if:
#   1. any Django model declares a routing_number / account_number field, or
#   2. EncryptedTextField is used to declare a field for anything other than a
#      provider secret (the Plaid access_token) — it must never wrap a bank
#      number.
#
# Serializer input fields (e.g. the write-only routing-number on the ABA
# validation endpoint) are fine: they are validated in memory, never persisted.
# Imports, comments, tests and migrations are ignored.
set -euo pipefail

cd "$(dirname "$0")/.."

fail=0

# 1. No routing/account number model fields.
raw_fields=$(grep -RnE \
  '^[[:space:]]*(routing_number|account_number)[[:space:]]*=[[:space:]]*models\.' \
  apps/ --include='*.py' 2>/dev/null \
  | grep -vE '/migrations/|/tests/' || true)

if [ -n "$raw_fields" ]; then
  echo "ERROR: a model declares a raw routing_number/account_number field (BRD §3.4):"
  echo "$raw_fields"
  fail=1
fi

# 2. EncryptedTextField only for the provider secret (access_token).
bad_enc=$(grep -RnE '=[[:space:]]*EncryptedTextField\(' \
  apps/ --include='*.py' 2>/dev/null \
  | grep -vE '/migrations/|/tests/' \
  | grep -vE 'access_token' || true)

if [ -n "$bad_enc" ]; then
  echo "ERROR: EncryptedTextField declares a field outside provider secrets (only access_token is allowed):"
  echo "$bad_enc"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "OK: no raw bank-number storage detected."
fi

exit "$fail"
