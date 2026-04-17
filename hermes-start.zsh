#!/usr/bin/env zsh
# hermes-start.zsh
# maps · cassette.help · MIT
# generated: 2026-04-16
# purpose: bootstrap Hermes aggregation agent for atlas/cartographer
# usage: zsh ~/dev/cartographer/hermes-start.zsh [--full | --update | --status]

set -euo pipefail

HERMES_BIN="$HOME/.hermes/bin/hermes"
BOOTSTRAP_PROMPT="$HOME/dev/cartographer/HERMES_BOOTSTRAP.md"
ATLAS_DIR="$HOME/atlas"
MASTER_SUMMARY="$ATLAS_DIR/agents/MASTER_SUMMARY.md"
HERMES_SUMMARY="$ATLAS_DIR/agents/hermes/SUMMARY.md"
SESSION_DIR="$ATLAS_DIR/agents/hermes/sessions"

# ── color helpers ──────────────────────────────────────────────────────────────
c_cyan='\033[36m'
c_green='\033[32m'
c_yellow='\033[33m'
c_red='\033[31m'
c_reset='\033[0m'

step()  { print -P "%F{cyan}▶ $1%f" }
ok()    { print -P "%F{green}  ✓ $1%f" }
warn()  { print -P "%F{yellow}  ⚠ $1%f" }
err()   { print -P "%F{red}  ✗ $1%f" }

# ── parse args ─────────────────────────────────────────────────────────────────
MODE="${1:---full}"   # --full | --update | --status | --ingest

# ── preflight ─────────────────────────────────────────────────────────────────
step "hermes-start — preflight"

if [[ ! -x "$HERMES_BIN" ]]; then
  err "hermes binary not found at $HERMES_BIN"
  err "run: ls ~/.hermes/bin/ to debug"
  exit 1
fi
ok "hermes binary found"

if [[ ! -f "$BOOTSTRAP_PROMPT" ]]; then
  err "bootstrap prompt not found: $BOOTSTRAP_PROMPT"
  exit 1
fi
ok "bootstrap prompt found"

# atlas dir — warn if not init'd but don't block
if [[ ! -d "$ATLAS_DIR" ]]; then
  warn "~/atlas/ not initialized — run: cart init"
  warn "hermes will generate summary from CLAUDE.md + soul files only"
else
  ok "atlas root found: $ATLAS_DIR"
fi

# ── status mode ───────────────────────────────────────────────────────────────
if [[ "$MODE" == "--status" ]]; then
  step "hermes status"
  echo ""
  echo "  hermes binary:    $HERMES_BIN"
  echo "  bootstrap prompt: $BOOTSTRAP_PROMPT"
  echo "  atlas root:       $ATLAS_DIR"
  echo ""
  if [[ -f "$MASTER_SUMMARY" ]]; then
    LAST_UPDATED=$(grep 'updated:' "$MASTER_SUMMARY" 2>/dev/null | head -1 | awk '{print $2}')
    VERSION=$(grep 'version:' "$MASTER_SUMMARY" 2>/dev/null | head -1 | awk '{print $2}')
    echo "  master summary:   v$VERSION — last updated $LAST_UPDATED"
  else
    warn "  master summary:   not yet generated"
  fi
  if [[ -d "$SESSION_DIR" ]]; then
    SESSION_COUNT=$(ls "$SESSION_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
    echo "  session logs:     $SESSION_COUNT files in $SESSION_DIR"
  fi
  echo ""
  exit 0
fi

# ── ingest mode — add a session file to atlas ─────────────────────────────────
if [[ "$MODE" == "--ingest" ]]; then
  SESSION_FILE="${2:-}"
  if [[ -z "$SESSION_FILE" || ! -f "$SESSION_FILE" ]]; then
    err "usage: hermes-start.zsh --ingest /path/to/session.json"
    exit 1
  fi
  step "ingesting session: $SESSION_FILE"
  mkdir -p "$SESSION_DIR"
  STAMP=$(date +%Y-%m-%d_%H%M%S)
  DEST="$SESSION_DIR/${STAMP}.md"
  # simple ingest: copy JSON as fenced block in a markdown note
  cat > "$DEST" << INGEST
---
type: agent-log
agent: hermes
date: $(date +%Y-%m-%d)
source: $SESSION_FILE
---

# Hermes Session — $STAMP

\`\`\`json
$(cat "$SESSION_FILE")
\`\`\`
INGEST
  ok "session ingested: $DEST"
  exit 0
fi

# ── full / update mode — run the bootstrap prompt ─────────────────────────────
step "preparing hermes context"

# build preamble telling hermes exactly what to do
PREAMBLE=$(cat << 'PREAMBLE'
You are running in aggregation mode.

Your task: read HERMES_BOOTSTRAP.md and execute it fully.
Generate or update ~/atlas/agents/MASTER_SUMMARY.md.

Read all context sources listed in the prompt before writing.
If a file doesn't exist, note it and continue with available data.
Do not truncate output. Write the complete file.
After writing, append your agent notes to ## agent notes in the summary.
After writing, append any prompt improvements to ## prompt improvement notes in HERMES_BOOTSTRAP.md.

PREAMBLE
)

echo "$PREAMBLE" > /tmp/hermes_preamble.md
cat "$BOOTSTRAP_PROMPT" >> /tmp/hermes_preamble.md

step "launching hermes — aggregation run ($(date +%Y-%m-%d %H:%M))"
echo ""

# ensure atlas session dir exists
mkdir -p "$SESSION_DIR"
mkdir -p "$(dirname "$MASTER_SUMMARY")"

# run hermes with the bootstrap prompt via -q (non-interactive single query)
PROMPT_TEXT=$(cat /tmp/hermes_preamble.md)
"$HERMES_BIN" chat -q "$PROMPT_TEXT"

# cleanup
rm -f /tmp/hermes_preamble.md

echo ""
step "aggregation complete"

if [[ -f "$MASTER_SUMMARY" ]]; then
  ok "master summary written: $MASTER_SUMMARY"
  LINES=$(wc -l < "$MASTER_SUMMARY")
  ok "summary length: $LINES lines"
else
  warn "master summary not found — hermes may have printed to stdout instead"
  warn "redirect output or run interactively to capture"
fi

echo ""
echo "  next steps:"
echo "    cart init                        ← if atlas not yet initialized"
echo "    zsh hermes-start.zsh --status    ← check summary status"
echo "    zsh hermes-start.zsh --update    ← run again after more sessions"
echo ""
