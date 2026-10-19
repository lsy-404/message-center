# Scan result status contract

## Goal
Replace the ambiguous boolean scan result with complete, partial, and failed states so QQ can commit validated partial progress without presenting a partial scan as online.

## Scope
Public Python runtime, its host tests, and adapter contract documentation. No Worker/UI/deployment/device changes.

## Work plan
- [x] Inspect current result validation, commit path, health, recovery, fixtures, and documentation.
- [x] Replace the boolean scan field with strict complete/partial/failed validation and persist partial source state correctly.
- [x] Add complete/partial/failed contract tests, including all-pages-failed cursor scheduling and degraded health.
- [x] Run the focused runtime suites, review the diff, and commit the isolated branch.
