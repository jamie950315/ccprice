# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ccprice** is a single-file Python CLI tool that scans Claude Code session history (`~/.claude/projects/`) and calculates equivalent Anthropic API costs. It reads `.jsonl` session transcripts and provides per-project cost breakdowns with time/model filtering.

## Running

```bash
python3 ccprice.py                     # basic usage
python3 ccprice.py --since week        # time filter (today/yesterday/week/month/year/Nd/Nw/Nm/YYYY-MM-DD)
python3 ccprice.py --model opus        # model filter (opus/sonnet/haiku/other or substring)
python3 ccprice.py --json              # machine-readable output
```

No external dependencies — stdlib only (Python 3.10+).

## Architecture

Everything lives in `ccprice.py` (~466 lines). Key flow:

1. **`main()`** — argparse CLI entry point
2. **`scan_projects()`** — walks `~/.claude/projects/*/` reading `.jsonl` files, extracts `assistant` message usage records, applies time/model filters, accumulates per-tier token counts
3. **`classify_model()`** — maps model IDs to pricing tiers (opus/sonnet/haiku) via `MODEL_PATTERNS`; skips non-Anthropic models
4. **`calc_cost()`** — computes API-equivalent cost from token counts × `ANTHROPIC_PRICING` rates
5. **`print_summary()` / `print_json()`** — output formatting with 6-tier color-coded cost thresholds (bright red ≥$500, red ≥$250, bright yellow ≥$100, yellow ≥$50, green ≥$25, bright green <$25)

## Pricing Data

`ANTHROPIC_PRICING` dict holds USD per 1M tokens for each tier (input, output, cache_read, cache_write). Update this when Anthropic changes pricing or adds new model tiers.

`MODEL_PATTERNS` maps model ID patterns to tier names. Update when new Claude model IDs appear.

## Conventions

- All UI text and code comments are in English
- No test suite — single-file utility validated manually
- Output adapts to terminal width via `get_terminal_width()`
