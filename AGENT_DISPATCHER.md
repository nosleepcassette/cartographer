# Agent Dispatcher

This document defines the lightweight handoff protocol for multi-agent work around the atlas.

### Suggested next agent

Pick the smallest useful next agent that can move the work forward without duplicating context gathering.

**No duplicates**
Never dispatch two agents to do the same unresolved task.

**No circular chains**
Do not hand work from agent A to agent B if B would immediately hand it back to A.

**Max depth 3**
Keep dispatch depth shallow so the coordination surface stays understandable.

**On overflow**
If there are too many possible handoffs, collapse back to a single summary, refresh context with `cart daily-brief`, and pick one next owner.

### Handoff hints

- Use `cart daily-brief` before starting a fresh worker when the local context is stale.
- Prefer durable context over chat-only context when delegating.
- When the task is about skill authoring, route to `create-skill` rather than inventing a parallel workflow.
