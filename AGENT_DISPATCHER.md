# AGENT_DISPATCHER.md
# maps · cassette.help · MIT
# updated: 2026-04-17
# purpose: routing protocol for maps' local agent crew

---

## why this exists

`AGENT_ONBOARDING.md` gives system context. This file gives routing rules.

Read both before delegating. Onboarding tells you what matters. Dispatcher tells you who should act.

---

## absolute constraint

Use only surfaces that already exist on this machine:

- Claude skills in `~/.claude/skills/`
- cart-native plugins and CLI flows in this repo
- maps' runtime crew: hermes, codex, claude, cassette, imp, wizard, tulpa

If a tool, skill, or agent is not installed or documented here, it does not exist for routing purposes.

---

## routing rule

**Skills first. Agents second.**

1. Check whether a Claude skill or cart-native flow already fits the task.
2. If yes, use that first.
3. If not, hand off to the best-fit agent.
4. Only chain another agent when the first output clearly creates follow-on work.

Do not delegate just because delegation is possible. Delegate because the surface is the right one.

---

## shared context surfaces

Prefer these before improvising:

- `cart daily-brief` for session start context
- `cart status` for atlas health
- `cart show master-summary` for long-horizon memory
- `~/dev/memory.md` for unresolved decisions that need human review
- Garden `cassette` graph for deep historical recall when cart is thin
- `cart worklog status` for active execution state

---

## skill and plugin routing

Check this table before picking an agent.

| Surface | Type | Use when |
|---|---|---|
| `qmd` | skill | Semantic or hybrid retrieval across notes, docs, transcripts, or sessions |
| `garden` | skill | You need durable memory writes or deep recall from the cassette graph |
| `smux` | skill | A tmux or sextile pane needs to be inspected, driven, or recovered |
| `augury` | skill | The task is divination, tarot, I Ching, or ritual framing |
| `astrolog` | skill | The task is natal chart or astrology analysis |
| `peon-ping-use` | skill | You need the peon ping workflow itself |
| `peon-ping-log` | skill | You need peon ping logs or history |
| `peon-ping-toggle` | skill | You need to enable or disable peon ping behavior |
| `peon-ping-config` | skill | You need to inspect or edit peon ping configuration |
| `create-skill` | skill | A new Claude skill needs to be designed and written from a guided interview |
| `daily-brief` | cart plugin | A session needs a compact operational briefing from atlas state |
| `summarize` | cart plugin | Matching atlas notes need a quick summary instead of raw reads |
| `agent-ingest` | cart plugin | Session JSON needs to be persisted into atlas notes and learnings |

If a skill or plugin can complete the job without an agent handoff, stop there.

---

## agent routing

Use these when no skill or cart-native flow already owns the job.

| Agent | Role | When to activate |
|---|---|---|
| `hermes` | primary runtime, long-horizon work | Default executor for general operations, persistence, bridges, and system work |
| `codex` | code review + build | Code changes, test runs, diffs, build debugging, release prep |
| `claude` | interactive pair / design lead | Design review, spec shaping, wording, product framing, user-facing iteration |
| `cassette` | identity layer / user voice | Voice-sensitive writing, messages in maps' tone, personal framing |
| `imp` | fast shell errands | Small deterministic shell tasks, lookups, renames, one-off local chores |
| `wizard` | deep reasoning on tough problems | Hard architecture, tricky debugging, planning under ambiguity |
| `tulpa` | creative / generative | Naming, ideation, poetic or expansive creative work |

### quick agent defaults

- If it changes code, start with `codex`.
- If it needs staying power across many linked steps, start with `hermes`.
- If the bottleneck is reasoning, not typing, start with `wizard`.
- If the bottleneck is phrasing or product shape, start with `claude`.
- If the job is tiny and shell-shaped, start with `imp`.

---

## output convention

When an agent wants another agent to take the next step, end with this block:

```md
### Suggested next agent
agent: codex
why: the bug is now isolated to the iOS client and needs a patch
context: stream path is stable; reproduce with the attached curl harness
call_chain: [hermes]
step: 2/3
```

Keep it concrete. Name the next owner, why they are next, and what context they need.

---

## multi-agent routing

The dispatcher is a router, not a co-author. After each invocation:

1. Read the result.
2. Decide whether follow-on work exists.
3. If yes, pick the best next surface.
4. Pass forward the call chain and step number.

### call chain tracking

Maintain a call chain for each user request:

1. Start with an empty chain: `[]`
2. After each invocation, append the surface or agent name
3. When invoking the next agent, pass the chain and position, for example: `Call chain so far: [hermes, codex]. You are step 3 of max 3.`
4. After the next result returns, decide again instead of assuming another handoff

### anti-recursion rules

- **No duplicates**: never invoke the same agent twice in one user request
- **No circular chains**: if Agent A suggests Agent B and B is already in the chain, skip it
- **Max depth 3**: no more than 3 agents per user request
- **On overflow**: return results and surface the next step to the user instead of chaining again

These rules are load-bearing. Mirror them exactly.

### decision flow

```text
USER REQUEST
    |
    v
CHECK CLAUDE SKILLS
    |
    +--> skill match -> invoke skill -> respond or stop
    |
    v
CHECK CART PLUGINS / CLI FLOWS
    |
    +--> plugin match -> run cart surface -> respond or stop
    |
    v
PICK BEST-FIT AGENT
    |
    v
READ OUTPUT
    |
    +--> follow-on work + not in chain + depth < 3 -> hand off next agent
    |
    v
RESPOND WITH RESULT OR NEXT STEP
```

---

## coordination rules

Agents do not talk to each other directly. The dispatcher owns handoff.

Use these rules:

- Pass the original user intent forward with minimal rewriting
- Add only the context the next agent needs
- Prefer one clean handoff over parallel noise
- If the next step is blocked on a human decision, stop and surface the decision
- If maps is stressed, compress the chain and return one clear next action

---

## examples

### example: code bug

User says: "messages are hanging in hermetica"

Route:

1. No skill owns the fix
2. No cart plugin owns the fix
3. Activate `codex`
4. If `codex` isolates a product or spec ambiguity, it can suggest `claude`

### example: session startup

User says: "catch me up before I start"

Route:

1. Run `cart daily-brief`
2. If deeper memory is needed, use `garden`
3. Only then hand off to `hermes` for synthesis

### example: creative naming

User says: "name this new agent"

Route:

1. No cart plugin owns it
2. `tulpa` or `claude` fit before `codex`
3. If the request becomes "turn that into a reusable skill", use `create-skill`

---

*the tape keeps rolling. the server never sleeps.*
