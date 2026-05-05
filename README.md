# HawkNetic Sports Tools

This repository is being rebuilt around the current HawkNetic architecture from the active project work.

## Current repository purpose
This repo is intended to hold only the updated HawkNetic materials that match the current project direction:
- HawkNetic architecture rules
- system build guidance
- provider-isolation rules for BALLDONTLIE
- project inventory and handoff documentation

## Core design rule
BALLDONTLIE must live in its own provider area.
HawkNetic must read from canonical HawkNetic structures, not directly from provider payloads.

## Recommended data flow
1. BALLDONTLIE API responses enter raw provider tables.
2. Raw provider data is stored in BALLDONTLIE-specific structures.
3. A normalization layer maps provider data into HawkNetic canonical tables.
4. HawkNetic features, model inputs, and recommendation logic read only from canonical tables.

## Docs in this repo
- `docs/system_architecture_and_build_guide.md`
- `docs/architecture_decisions_and_rules.md`
- `docs/project_file_inventory.md`
- `docs/provider_integration_balldontlie.md`

## Security rule
Do not commit live API keys or secrets into this repository.
Use local environment variables only.
