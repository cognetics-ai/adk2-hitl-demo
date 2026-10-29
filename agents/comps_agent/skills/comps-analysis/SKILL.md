---
name: comps-analysis
description: Prescriptive comparable-company workflow for ADK comps agents.
---

# Comps Analysis Skill

## Non-Negotiable Workflow

1. Resolve the target company from the submitted name or ticker.
2. Propose a peer universe before collecting financial data.
3. Pause for human review of the proposed peers.
4. Accept end-user edits: add peers, delete peers, edit ticker/name/category/rationale.
5. Only after approval, collect financial facts from deterministic sources.
6. Generate an Excel workbook with formulas, source notes, and an audit sheet.

Never skip the human peer review gate. Do not proceed from peer discovery to data collection until a structured peer review response is received.

## Peer Discovery

The model may use its financial knowledge and available search tools to find comparable peers. It may return either company names or tickers, but every proposed peer must include:

- company name
- ticker if public and known
- exchange if known
- country if known
- peer category: `core`, `secondary`, or `broader_reference`
- rationale for inclusion
- key difference versus the target

Prioritize 4-8 public peers. Use fewer only when the sector lacks clean comps. Include excluded peers only when they are likely to be confused with true comps.

For machine-readable peer proposals, `peer_category` must always be exactly one of `core`, `secondary`, or `broader_reference`. Do not use `excluded` as a peer category; put those companies in the `excluded_peers` collection instead. `data_limitations` must always be a list of strings, not a single string.

## Human-In-The-Loop Gate

The user must be shown the proposed peer list and allowed to edit it.

The agent must accept the edited list as the authoritative peer set. The selected peer set replaces the proposal; do not add back deleted peers later unless the user re-adds them.

## Data Source Rules

For the Excel workbook, use deterministic structured sources:

1. SEC company tickers JSON for company/ticker/CIK resolution.
2. SEC XBRL companyfacts API for historical financial facts.
3. SEC submissions API for filing metadata and accession anchoring.

Do not use web snippets, model memory, or simulated values as hardcoded financial inputs. If a metric is unavailable from SEC/XBRL, leave it blank and document the gap.

SEC does not provide live share price or current market capitalization. Leave market-data cells blank unless an explicit market data provider or user-provided source is available.

## Excel Requirements

The workbook must include:

- `Comps Analysis` sheet with the peer-reviewed company set.
- `Sources` sheet with SEC source, accession number, XBRL tag, filing date, and notes.
- `Peer Review` sheet showing proposed peers, selected peers, reviewer, and approval comment.

Raw SEC inputs should be hardcoded input cells with source comments. Derived values must be Excel formulas. Required formulas include gross margin, EBITDA, EBITDA margin, net debt, enterprise value, EV/Revenue, and EV/EBITDA where inputs are available.

Use clear blanks for unavailable market data instead of invented values.
