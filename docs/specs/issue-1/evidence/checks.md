# Verification output — issue-1

Captured 2026-10-09 from the branch `issue-1-init-dev-env`. `$PLUGIN` is the installed
the-loop plugin root, version 19.28.0.

## the-loop folder

```text
$ ls -A .the-loop
collaborators.yaml
harness-config.yaml
manifest.yaml
```

## Claude settings

```text
$ curl -sL https://raw.githubusercontent.com/MadaraUchiha-314/the-loop/main/.claude/settings.json | diff - .claude/settings.json && echo identical
identical
$ jq -e '.enabledPlugins["the-loop@the-loop"] and .extraKnownMarketplaces["the-loop"].source.repo=="MadaraUchiha-314/the-loop"' .claude/settings.json
true
```

## Schema validation

```text
$ uv run --quiet --with pyyaml --with jsonschema python validate.py
.the-loop/harness-config.yaml: valid against harness-config.schema.json
.the-loop/collaborators.yaml: valid against collaborators.schema.json
.the-loop/manifest.yaml: parses as YAML
```

`validate.py` loads each YAML file and runs `jsonschema.validate` against the schema
of the same name under `$PLUGIN/.the-loop/`.

## Manifest

```text
$ diff $PLUGIN/.the-loop/manifest.yaml .the-loop/manifest.yaml && echo identical
identical
```

## Docs trees

```text
$ ls -d docs/*/
docs/architecture/
docs/capabilities/
docs/decisions/
docs/learnings/
docs/specs/
```
