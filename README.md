# Ruoyu Film Daily

This repository contains the controlled-production workflow for the Ruoyu film article group.

## Current state

- Phase 1 contract and internal templates exist.
- Phase 2 offline validators and synthetic negative tests exist.
- The next permitted operation is one manually initiated, real-source controlled batch that stops at `R8 review-ready`.
- No cron, source registry, publisher integration, message delivery, HTML renderer, image pipeline, or publication path is implemented or authorized.

## First-run boundary

Use [controlled-first-run-brief.md](templates/controlled-first-run-brief.md) as the task contract. The run must stop after independent review handoff. A green local validator confirms only deterministic batch gates; it does not establish factual truth, article quality, `publish-ready`, or publication authorization.

## Offline verification

```bash
python3 -m pytest -q
```

The tests use synthetic records only. They verify state transitions, slot and angle separation, claim-coverage requirements, withheld HTML, and the no-publication boundary.
