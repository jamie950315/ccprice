# ccprice

A CLI tool that scans your local [Claude Code](https://docs.anthropic.com/en/docs/claude-code) session history and calculates equivalent API costs for Anthropic models.

Since Claude Code stores session transcripts locally in `~/.claude/projects/`, this tool aggregates token usage across all projects and sessions, then estimates what you would have paid at API pricing.

## Screenshot

```
Claude Code Usage Summary
──────────────────────────────────────────────────────────────────────────────────

  Project                          Sessions    Anthropic      Other    Est. Cost
  ────────────────────────────────────────────────────────────────────────────────
  my-web-app                             12        59.4M          0      $98.33
    └ Opus     in:535 out:140.2k cR:34.4M cW:1.3M                       $86.54
    └ Sonnet   in:14.8k out:145.6k cR:22.6M cW:741.4k                   $11.79
  another-project                         5         9.3M       4.8M      $22.69
    └ Opus     in:210 out:63.7k cR:5.8M cW:337.8k                       $19.88
    └ Sonnet   in:83 out:83.6k cR:2.8M cW:188.4k                         $2.81
  ~ (home)                               22         1.4M     563.3k       $4.20
    └ Opus     in:81 out:12.1k cR:1.2M cW:70.6k                          $4.08
    └ Sonnet   in:9 out:382 cR:32.4k cW:27.3k                           $0.118
  ────────────────────────────────────────────────────────────────────────────────
  TOTAL                                           72.5M       6.1M     $128.09
```

Output is color-coded: costs >= $10 in red, >= $1 in yellow, < $1 in green.

## Features

- **Auto-discovery** — scans all projects under `~/.claude/projects/`; new projects are picked up automatically
- **Anthropic-only pricing** — calculates equivalent costs for Opus, Sonnet, and Haiku; other providers show token counts only
- **Per-tier breakdown** — input, output, cache read, and cache write tokens with individual costs
- **Color-coded output** — red / yellow / green based on cost thresholds
- **Adaptive layout** — column widths adjust to terminal size; long project names are truncated
- **JSON output** — `--json` for machine-readable output

## Pricing Reference (USD per 1M tokens)

| Model | Input | Output | Cache Read | Cache Write |
|---|---|---|---|---|
| Opus 4.6 | $15.00 | $75.00 | $1.50 | $18.75 |
| Sonnet 4.6 | $3.00 | $15.00 | $0.30 | $3.75 |
| Haiku 4.5 | $0.80 | $4.00 | $0.08 | $1.00 |

## Install

```bash
git clone https://github.com/jamie950315/ccprice.git
cd ccprice

# Option 1: symlink (recommended, easy to update with git pull)
ln -s "$(pwd)/ccprice.py" ~/.local/bin/ccprice

# Option 2: copy
cp ccprice.py ~/.local/bin/ccprice
chmod +x ~/.local/bin/ccprice
```

### Requirements

- Python 3.10+
- No external dependencies (stdlib only)

## Usage

```bash
ccprice              # formatted table
ccprice --json       # JSON output
ccprice --projects-dir /path/to/.claude/projects  # custom path
```

## How It Works

1. Scans `~/.claude/projects/` for all project directories
2. Reads `.jsonl` session transcript files
3. Extracts `usage` from `assistant` message records
4. Classifies models into Anthropic tiers (Opus / Sonnet / Haiku) or other
5. Calculates equivalent API cost using current Anthropic pricing
6. Outputs a formatted table or JSON

## Notes

- If you're on a **Claude Pro/Max subscription**, the cost shown is the **equivalent API price**, not your actual bill. Useful for understanding resource consumption and comparing against subscription value.
- Token data comes from locally stored session transcripts. Deleting `~/.claude/projects/` removes the history.
- Non-Anthropic models (Gemini, GPT, etc.) are listed under "Other" as token counts without cost calculation.

## License

MIT
