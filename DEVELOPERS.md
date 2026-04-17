# DEVELOPERS.md
# maps · cassette.help · MIT

## this is infrastructure. what are you going to build?

cartographer + mapsOS started as one person's attempt to make their tools
actually know them - their projects, their history, their state.

The result is a local-first knowledge graph with a qualitative life OS
sitting underneath it. Everything agent-aware. Everything configurable.
Everything yours.

Now it's yours to build on.

---

## the plugin API (30 seconds)

Any executable that reads JSON on stdin and writes JSON on stdout is a plugin.

```json
{
  "command": "my-plugin",
  "args": {"option": "value"},
  "notes": [{"id": "project-alpha", "content": "..."}]
}
```

```json
{
  "output": "result text",
  "writes": [{"path": "agents/my-agent/output.md", "content": "..."}],
  "errors": []
}
```

Drop it in `.cartographer/plugins/`. Run with `cart plugin run my-plugin`.
Python, shell, Rust, Lua - anything that speaks JSON.

---

## things you could build

**For neurodivergent communities:**
A mapsOS profile tuned for ADHD hyperfocus cycles, autism sensory load,
bipolar energy tracking, BPD emotional intensity. Different state vocabulary.
Different arc definitions. Different capacity thresholds. Same substrate.

**For teams:**
A shared atlas where multiple engineers' agents all write session logs to the
same knowledge graph. Entity notes for shared concepts. Cross-agent backlinks.
A `cart query` that answers "what did any agent learn about this component?"

**For researchers:**
Every paper you read becomes a note. Every quote is a block reference.
`cart query 'tag:paper links:transformer-architecture'` returns your reading list.
Your agent's session logs link to the papers that informed them.

**For therapists / coaches:**
Session notes accumulate into entity profiles. Patterns surface automatically.
`cart mapsos patterns --field state` across clients (with consent). No cloud.
No vendor. Files on your machine.

**For ops teams:**
Incident reports are notes. Runbooks are notes. Every incident links to the
entities and projects it touched. Backlinks show you which runbook sections
were consulted during which incidents. Post-mortems write themselves.

**For anyone building with LLMs:**
Your agents forget everything when the context window closes. cartographer is
what they leave behind. Session import means every conversation accumulates
into a queryable graph. `cart daily-brief` seeds the next session from the last.
Your AI tools get smarter because they actually remember.

---

## extension points

| surface | how |
|---------|-----|
| Plugins | executable in `.cartographer/plugins/` |
| Templates | Jinja2 in `.cartographer/jinja/` |
| Hooks | shell scripts in `.cartographer/hooks/` |
| mapsOS tracks | `tracks:` in `~/.maps_os_config.yaml` |
| mapsOS state vocab | `state.tags:` in config |
| mapsOS arcs | custom patterns in config (coming) |
| Agent adapters | `cart session-import` reads any agent that writes the ECC session format |

---

## the ethos

This was built for one brain, configured for that brain's specific needs.
The whole point is that you configure it for yours.

In a month, the first community config drops and someone else's brain
works better because of it. In a year, someone's building something
we haven't imagined on top of this substrate.

That's the goal. Come build.

-> [github.com/nosleepcassette/cartographer](https://github.com/nosleepcassette/cartographer)
-> [github.com/nosleepcassette/mapsOS](https://github.com/nosleepcassette/mapsOS)
