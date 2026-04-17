# cartographer

Local-first knowledge filesystem and agent memory layer.

## Install

```zsh
cd ~/dev/cartographer
pipx install -e .
```

## Phase 1 commands

```zsh
cart init [path]
cart status
cart backup
cart new [type] [title]
cart open [id]
cart edit [id]
cart query 'tag:project status:active'
cart backlinks hopeagent
cart todo list
cart todo add "finish conversational loop" -p P0
cart todo done t123abc
cart worklog status
```

The atlas defaults to `~/atlas`, or `CARTOGRAPHER_ROOT` can be set to override it.
