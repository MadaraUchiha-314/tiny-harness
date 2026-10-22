# Capability: entities-and-registry

> Every pluggable construct is an entity behind one abstract interface per kind, addressed
> by a registry reference and resolved from one registry.

## What it is

The principle the rest of the harness is built on. A prompt, a skill, a tool, a model, a
hook, a channel, a renderer, a surface, a store and an agent are all entities; the core
loop, plugins and hooks reach them only through the registry, so any of them can be
replaced, versioned or served remotely without touching the loop. Lives in
`tiny_harness/harness/entities/`.

## Current behaviour

- The system SHALL define one abstract interface per entity kind: `prompt`, `skill`,
  `tool`, `llm`, `system_one`, `hook`, `channel`, `renderer`, `surface`, `store`,
  `agent` and `command`. The agent interface is `send_message` (an async stream of the A2A SDK's own
  `Message`, `Task` and update events) and `cancel_task`, with an agent card.
- The system SHALL address every entity instance by an `EntityRef` of `(kind, id,
  version)`, where `version` is `None` for kinds that are not versioned. A version
  specifier is resolved as sherma resolves it: a PEP 440 specifier selects among the
  concrete registered versions, `*` means the latest concrete one, and an entry registered
  under `*` is the fallback when no concrete version matches.
- WHEN an entity is resolved THEN the registry SHALL return exactly one instance or raise
  the typed not-found error; it SHALL NOT fall back to a default.
- The registry SHALL hold local entries (an instance or a factory) and remote entries (a
  URL and the application protocol it speaks: A2A for agents, MCP for tools and prompts,
  HTTPS for models and remote hooks); a remote entry with no protocol SHALL be refused.
- WHEN two registrations carry the same `(id, version)` THEN the second SHALL be refused
  unless the caller asks for an override.
- A `Command` entity SHALL wrap a `CommandSpec` (name matching `[a-z][a-z0-9-]*`,
  description, argument hint) under `EntityRef(kind="command", id=<name>)`, unversioned.
  The `CommandRegistry` (`harness/commands/registry.py`) takes registrations from code
  (`register(spec, handler)` or `register_executor(spec, executor)`, each with
  `override=`), from plugins and from the built-ins; an invalid or duplicate name raises
  `CommandError` when the harness is built. It is frozen before the worker starts and
  published into the entity registry, and its specs are what the card's commands
  extension lists.
- The registry SHALL be one object with a typed `get`, exposed to hooks and plugins, so a
  plugin can register, override or remove an entry. Divergences from sherma's
  `Registry[T]`: one registry instead of a subclass per kind, a remote entry carries its
  protocol, no `tenant_id`.
- `EntityKind` SHALL include `speech_to_text`, `text_to_speech`, `image_generator` and
  `media_store` (issue-38).

## Design

[design.md § Entities and registry](../specs/issue-3/design.md#entities-and-registry-r1--harnessentities),
[design.md § sherma: reused and replaced](../specs/issue-3/design.md#sherma-reused-and-replaced).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Entity base, kinds, references, remote locations and the registry (Layer 1); the `surface` kind added with the renderers (Layer 7) | [spec](../specs/issue-3/), [PR #7](https://github.com/MadaraUchiha-314/tiny-harness/pull/7), [PR #13](https://github.com/MadaraUchiha-314/tiny-harness/pull/13) |
| issue-25 | The `command` kind and the `Command` entity, filled by `CommandRegistry` and published before the worker starts | [spec](../specs/issue-25/), [PR #26](https://github.com/MadaraUchiha-314/tiny-harness/pull/26), [decision-007](../decisions/decision-007.md) |
| issue-38 | The `speech_to_text`, `text_to_speech`, `image_generator` and `media_store` kinds | [spec](../specs/issue-38/), [PR #39](https://github.com/MadaraUchiha-314/tiny-harness/pull/39) |
