#!/bin/zsh
# Discord announcement for cartographer public debut
# Usage: ./announce.zsh [webhook_url]

WEBHOOK="${1:-$DISCORD_CARTOGRAPHER_WEBHOOK}"

if [[ -z "$WEBHOOK" ]]; then
    echo "No webhook. Set DISCORD_CARTOGRAPHER_WEBHOOK or pass as argument."
    exit 1
fi

curl -X POST "$WEBHOOK" \
  -H "Content-Type: application/json" \
  -d '{
    "content": null,
    "embeds": [
      {
        "title": "🗺️ cartographer",
        "description": "**a local-first knowledge filesystem and agent memory layer**\n\nPlain Markdown files. Git-native history. Queryable notes. Block-addressable text.\nAgents and humans write to the same substrate. Nothing is trapped in an app.",
        "url": "https://github.com/nosleepcassette/cartographer",
        "color": 32768,
        "fields": [
          {
            "name": "why this hits different",
            "value": "- **Files are the API.** Delete the tool, keep your brain.\n- **Agents are first-class.** Hermes, Claude, Codex write to the same atlas.\n- **Block-addressable.** `[[note#block]]` transclusion built in.\n- **Imports are idempotent.** Run `cart import` 100x, get 0 duplicates.\n- **Daily brief.** `cart daily-brief` generates session context from your own notes."
          },
          {
            "name": "what it does",
            "value": "```cart init && cart daily-brief```\nThat'\''s it. You now have:\n• Session import (Claude, Hermes, ChatGPT exports)\n• Full-text query\n• Task tracking\n• Graph export\n• mapsOS integration"
          },
          {
            "name": "the loop",
            "value": "```\nsession → export → cart ingest → atlas update → daily brief → next session\n```\nYour agents start every session already knowing what you forgot."
          },
          {
            "name": "install",
            "value": "```zsh\npipx install git+https://github.com/nosleepcassette/cartographer.git\n```"
          }
        ],
        "footer": {
          "text": "the tape keeps rolling. the server never sleeps."
        }
      }
    ]
  }'

echo ""
echo "Posted to Discord."
