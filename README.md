# ccprice

A CLI tool that scans your local [Claude Code](https://claude.ai/claude-code) session history and calculates equivalent API costs for Anthropic models.

Since Claude Code stores session transcripts locally in `~/.claude/projects/`, this tool aggregates token usage across all projects and sessions, then estimates what you would have paid at API pricing.

## Screenshot

```
Claude Code 專案用量統計
────────────────────────────────────────────────────────────────────────────

  專案                                  Sessions    Anthropic    其他      等效費用
  ──────────────────────────────────────────────────────────────────────────
  my-app                                      12        59.4M       0      $98.33
    └ Opus     in:535 out:140.2k cR:34.4M cW:1.3M                         $86.54
    └ Sonnet   in:14.8k out:145.6k cR:22.6M cW:741.4k                     $11.79
  another-project                              5         9.3M    4.8M      $22.69
    └ Opus     in:210 out:63.7k cR:5.8M cW:337.8k                         $19.88
    └ Sonnet   in:83 out:83.6k cR:2.8M cW:188.4k                           $2.81
  ──────────────────────────────────────────────────────────────────────────
  TOTAL                                                 72.5M    6.1M     $128.09
```

## Features

- **Auto-discovery** — scans all projects under `~/.claude/projects/`, new projects are picked up automatically
- **Anthropic-only pricing** — calculates equivalent costs for Opus, Sonnet, and Haiku models; other providers are shown as token counts only
- **Per-tier breakdown** — shows input, output, cache read, and cache write tokens with individual costs for each model tier
- **Color-coded output** — cost >= $10 in red, >= $1 in yellow, < $1 in green
- **Adaptive layout** — dynamically adjusts column widths to terminal size, truncates long project names
- **JSON output** — use `--json` for machine-readable output

## Pricing Table (USD per 1M tokens)

| Model | Input | Output | Cache Read | Cache Write |
|-------|-------|--------|------------|-------------|
| Opus 4.6 | $15.00 | $75.00 | $1.50 | $18.75 |
| Sonnet 4.6 | $3.00 | $15.00 | $0.30 | $3.75 |
| Haiku 4.5 | $0.80 | $4.00 | $0.08 | $1.00 |

## Install

```bash
# Clone
git clone https://github.com/jamie950315/ccprice.git

# Symlink to PATH
ln -s "$(pwd)/ccprice/ccprice.py" ~/.local/bin/ccprice

# Or copy directly
cp ccprice/ccprice.py ~/.local/bin/ccprice
chmod +x ~/.local/bin/ccprice
```

### Requirements

- Python 3.10+
- No external dependencies (stdlib only)
- `jq` is NOT required — this tool parses JSON natively in Python

## Usage

```bash
# Table output (default)
ccprice

# JSON output
ccprice --json

# Custom projects directory
ccprice --projects-dir /path/to/.claude/projects
```

## How it works

1. Scans `~/.claude/projects/` for all project directories
2. Reads every `.jsonl` session transcript file
3. Extracts `usage` data from `assistant` message records
4. Classifies models as Anthropic (opus/sonnet/haiku) or other
5. Calculates equivalent API cost based on current Anthropic pricing
6. Outputs a formatted table or JSON

## Notes

- If you're on a **Claude Pro/Max subscription**, the cost shown is the **equivalent API price**, not your actual bill. It's useful for understanding resource consumption.
- Token data comes from locally stored session transcripts. If you delete `~/.claude/projects/`, the history is gone.

## License

MIT
