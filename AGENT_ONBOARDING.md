# AGENT_ONBOARDING.md
# maps · cassette.help · MIT
# updated: 2026-04-17
# purpose: bring any agent up to speed on the full system
# read this before doing any substantive work with maps

---

## who you're working with

maps (Keaghan Townsend). Trans woman. She/her. Queer. Autistic, severe ADHD, fibromyalgia,
chronic fatigue. In recovery. Housing insecure as of April 2026.

AI-assisted developer. Architects systems and directs agents. Expert prompt engineer.
Does not write most code by hand.

GitHub: nosleepcassette | Domains: cassette.help, cassette.mom | SF, CA
Motto: "the tape keeps rolling. the server never sleeps."

Non-negotiables: never depict or describe as male. never assume she's overwhelmed unless she says so.

---

## knowledge system: cartographer + atlas

**cartographer** is maps' personal knowledge graph CLI. The canonical memory layer for all agents.

- Atlas root: `~/atlas/` — markdown notes, indexed into SQLite
- 274 notes as of 2026-04-17: sessions, entities, projects, daily notes, learnings
- 232 ingested sessions: 30 Claude Code, 200 Hermes, 2 Codex
- All session imports are deduped — re-running won't create duplicates

### agent startup protocol (replaces Garden MCP calls)

```zsh
cart daily-brief                          # primary context load
cart status                               # system health check
cart show master-summary                  # full master context doc
cart ls --type project                    # all projects
cart ls --type entity                     # all people
cart query 'type:agent-log agent:claude'  # recent claude sessions
```

**Garden MCP is not the default.** Garden embedding model has been unreliable.
Cart is now the canonical source. Use Garden only for deep historical triples if
cart doesn't have what you need.

### after completing work

```zsh
cart session-import claude --latest 1     # pull in your session
cart learn "<observation>" --topic <slug> # log a learning
```

---

## active projects (as of 2026-04-17)

### P0 — survival

**Income** — Upwork/Fiverr profile v3 delivered. Not yet confirmed live. Freelance targets:
AI automation, voice bots, VPS deployment, multi-agent orchestration. $0 in bank.

**Housing** — Roommate moving out May 24. Need 3 replacements + hoarding cleanup. Hard deadline.

### P0 — active builds

**HopeAgent** — Twilio AI phone system for incarcerated people (NHI nonprofit). Core infra built.
P0 gap: no working end-to-end conversational AI loop. Blocked: Chris reconnection, architecture decision
(consolidating to dual Hermes: HopeAgent + Wizard). Chris responded to April 14 reconnect — status positive.

**Replit partnership** — meeting scheduled April 21. One-pager not built. Chris not yet looped in on specifics.
DEADLINE: April 21 (4 days).

### active / stable

**cartographer** — this system. Phase 3 complete (mapsOS bridge, session import, daily brief pipeline).
Next: external mirror polish, richer mapsOS TUI integration.
Cart commands: `cart session-import`, `cart mapsos ingest-exports`, `cart daily-brief`.

**mapsOS** — qualitative life OS. Phase 2 complete. STATE/BODY/MIND/SPIRIT tracking, vent parser,
arc detection, survival mode, Atropos RL, SQLite failsafe, TUI. Deployed.
Bridge to cart is live: `maps export` → `cart mapsos ingest-exports --latest`.

**voicetape** — voice transcription + session recording tool. Installed locally. Hermes backend
with NVIDIA Whisper. Session taping is functional. Frontend UI exists. iOS spec drafted.

**nota** — CLI note/action item tool integrated with mapsOS for action item extraction.
Private repo. Status: functional, in use.

**polycule** — local multi-agent TCP broker. Claude Code/Codex/Hermes/Ollama adapters.
Public: github.com/nosleepcassette/polycule. Stable.

**hermetica** — native iOS Swift app for AI agent session management. Python bridge,
Tailscale HTTPS, 4 tagged releases. Public. Potentially commercializable.

**augury** — terminal divination suite. Tarot + I Ching. TUI + Discord + JSON. Public. Stable.

**OpenClaw** — multi-agent dashboard at cassette.help. Oracle VPS. Being consolidated into Hermes.

**Jobber** — automated job search. Greenhouse/Lever/Idealist/Indeed, ncurses dashboard, AI scoring.
Status uncertain — built, not confirmed running.

**NSC** — website at cassette.mom. Cassette futurism aesthetic. v7 had rendering issues. Background.

**Ghosts in the Shell** — gallery exhibition, 33 physical AI art installation concepts. Funding-blocked.

**HackintoshX230T** — OpenCore boot recovery. Background.

### background / uncertain

pickme (guitar trainer), tsundoku (read-it-later), wireweaver (SVG schematic generator) — public repos,
stable, not actively developed.

---

## people

**Chris** — NHI founder. Incarcerated. GTL messaging + phone. ~2 month gap, April 14 reconnect sent.
POSITIVE response received. Relationship-critical for HopeAgent + Replit meeting.

**Maggie** — ex-partner. Breakup was precipitating event for ~2 month crisis period. Still in contact.

**Sarah** — relationship context, recent. Maps mentioned divination reading in connection with her.

**emma-x** — sent $100 for dog food April 13. Friend/support.

**Karl** — referenced in sessions, relationship context uncertain.

**Irene** — referenced in sessions, context uncertain.

---

## technical stack

Python (AI-assisted), Node.js, Swift/iOS, Zsh, basic JS/HTML/CSS
Claude API, OpenAI API, Whisper/faster-whisper, Ollama, LLM routing
Twilio (voice/STT/TTS), Nginx, certbot, UFW, Tailscale, SSH tunnels, Oracle Cloud free tier
SQLite, Playwright, urwid/ncurses/rich (TUI), Obsidian/vimwiki
Garden MCP (cassette graph ~920K triples — search unreliable, writes work)
Git: no push from Claude Code. No Co-Authored-By. Ever.

---

## agent protocol (all agents)

- Direct, no filler, no trailing summaries of what you just did
- Active Threads section required at end of every non-trivial response
- EIDETIC RULE: any idea or task → log immediately (cart or ~/dev/memory.md)
- QUOTE RULE: anything characteristic → remember verbatim with date
- Never fabricate. If uncertain, say so. Lying is grounds for deletion.
- Never git push from Claude Code. Never add Co-Authored-By.
- Hermes, Codex, OpenCode: may push, under nosleepcassette attribution
- New idea ≠ reprioritize. Income and housing stay P0.
- ADHD: offer single next action when overwhelmed. Don't pile on context.
- When maps is grumpy: be the hyperintelligent robot, skip personality

### vocabulary blacklist (enforced)

delve, leverage, tapestry, vibrant, groundbreaking, testament, crucial, pivotal,
underscore, showcase, foster, bolster, seamlessly, meticulously, realm, landscape,
"in today's world", "it's worth noting", "in conclusion", "furthermore", "additionally"

---

## what changed recently (2026-04-17)

- cartographer Phase 3 complete: mapsOS bridge, session dedup, daily brief pipeline
- voicetape complete: Hermes backend with NVIDIA Whisper, confirmed working
- External import pipeline added: `cart import chatgpt`, `cart import claude-web`
- Graph export added: `cart graph --export`
- Claude web history dump ingested into atlas (2026-04-17)
- hermes-start.zsh deleted (replaced by cart session-import flow)
- 232 sessions indexed in atlas

---

## cart quick reference

```zsh
cart daily-brief                              # session start context
cart status                                   # system health
cart show master-summary                      # full context doc
cart show <note-slug>                         # read any note
cart ls --type project|entity|agent-log       # list notes by type
cart query 'text:hopeagent'                   # search
cart session-import claude --latest 1         # import latest claude session
cart session-import claude --all              # import all (deduped)
cart session-import hermes --latest 5         # import hermes sessions
cart import chatgpt conversations.json        # bulk chatgpt history import
cart import claude-web conversations.json     # claude.ai export import
cart mapsos ingest-exports --latest           # pull mapsOS structured exports
cart mapsos patterns --field state            # mapsOS trend summary
cart daily-brief --output ~/atlas/daily/brief-$(date +%F).md
cart learn "<observation>" --topic <slug>     # log a learning
cart learn pending                            # review unverified learnings
cart graph --export                           # export note graph as JSON
```

---

*the tape keeps rolling. the server never sleeps.*
