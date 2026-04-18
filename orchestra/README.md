# orchestra
# maps · cassette.help · MIT

Short shell wrappers for common cart operations.

Why:

- short names are easier for agents to remember
- stable script paths are easier to allowlist than ad hoc shell pipelines
- each wrapper keeps output deterministic and one-screen when possible

## scripts

| Script | What it does | Wraps |
|---|---|---|
| `cart-today` | plain-text daily brief | `python3 -m cartographer.cli daily-brief --format plain` |
| `cart-state-today` | today's mapsOS STATE rows | cartographer pattern helpers |
| `cart-inbox` | pending learning inbox | `python3 -m cartographer.cli learn pending` |
| `cart-worklog` | current worklog session + in-progress count | `python3 -m cartographer.cli worklog status` |
| `cart-health` | atlas root, cart importability, Garden presence, qmd presence | cartographer config + qmd helper |
| `cart-recent` | last N learning writes across agents | cartographer agent-memory helpers |

## allowlist note

This repo does **not** edit `~/.claude/settings.json`.

If you want these wrappers permission-free in Claude Code, add them yourself under the bash allowlist. Suggested entries:

```json
{
  "permissions": {
    "allow": [
      "Bash(/Users/maps/dev/cartographer/orchestra/cart-today:*)",
      "Bash(/Users/maps/dev/cartographer/orchestra/cart-state-today:*)",
      "Bash(/Users/maps/dev/cartographer/orchestra/cart-inbox:*)",
      "Bash(/Users/maps/dev/cartographer/orchestra/cart-worklog:*)",
      "Bash(/Users/maps/dev/cartographer/orchestra/cart-health:*)",
      "Bash(/Users/maps/dev/cartographer/orchestra/cart-recent:*)"
    ]
  }
}
```

## how to add one

1. Keep it in `orchestra/`
2. Start with `#!/usr/bin/env zsh`
3. Keep the body under 15 lines
4. Derive repo root from the script path
5. Set `PYTHONPATH` to the repo root
6. Wrap one cart command or one tiny Python helper
7. Keep output stable enough for agents to parse
8. Make it executable
