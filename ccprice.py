#!/usr/bin/env python3
"""Scan Claude Code session history and calculate equivalent Anthropic API costs."""

import json
import os
import re
import sys
import glob
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Anthropic pricing (USD per 1M tokens)
ANTHROPIC_PRICING = {
    "opus": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "sonnet": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "haiku": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_write": 1.0,
    },
}

# Model ID → pricing tier
MODEL_PATTERNS = {
    "opus": ["opus"],
    "sonnet": ["sonnet"],
    "haiku": ["haiku"],
}


def classify_model(model_id: str) -> str | None:
    """Classify model ID as opus/sonnet/haiku. Returns None for non-Anthropic models."""
    mid = model_id.lower()
    non_anthropic = ["google/", "gemini", "openai/", "gpt", "minimax/", "<synthetic>"]
    if any(prefix in mid for prefix in non_anthropic):
        return None
    for tier, keywords in MODEL_PATTERNS.items():
        if any(kw in mid for kw in keywords):
            return tier
    return None


def parse_period(period: str) -> tuple[datetime, datetime | None] | None:
    """Parse a time period string and return (since, until) datetimes (UTC).

    Returns a tuple of (since, until). until is None for open-ended ranges.
    Returns None if the period string is invalid.

    Supported formats:
      today, yesterday, week, month, year,
      Nd (N days), Nw (N weeks), Nm (N months),
      YYYY-MM-DD (specific date)
    """
    now = datetime.now(timezone.utc)
    p = period.lower().strip()

    if p == "today":
        return (now.replace(hour=0, minute=0, second=0, microsecond=0), None)
    if p == "yesterday":
        return ((now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0), None)
    if p == "week":
        return (now - timedelta(weeks=1), None)
    if p == "month":
        return (now - timedelta(days=30), None)
    if p == "year":
        return (now - timedelta(days=365), None)

    # Nd, Nw, Nm patterns
    m = re.match(r"^(\d+)([dwm])$", p)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == "d":
            return (now - timedelta(days=n), None)
        if unit == "w":
            return (now - timedelta(weeks=n), None)
        if unit == "m":
            return (now - timedelta(days=n * 30), None)

    # YYYY-MM-DD
    m = re.match(r"^\d{4}-\d{2}-\d{2}$", p)
    if m:
        return (datetime.fromisoformat(p).replace(tzinfo=timezone.utc), None)

    return None


def parse_at(period: str) -> tuple[datetime, datetime | None] | None:
    """Parse a calendar-based window and return (since, until) datetimes (UTC).

    Unlike parse_period which counts backwards from now, parse_at uses
    real calendar boundaries:
      today/day:   today 00:00 ~ now
      yesterday:   yesterday 00:00 ~ today 00:00
      week:        Sunday 00:00 of this week ~ now
      month:       1st of this month 00:00 ~ now
    """
    now = datetime.now(timezone.utc)
    p = period.lower().strip()

    if p in ("today", "day"):
        return (now.replace(hour=0, minute=0, second=0, microsecond=0), None)
    if p == "yesterday":
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return (start, end)
    if p == "week":
        # Start from Sunday (weekday: Mon=0, Sun=6)
        days_since_sunday = (now.weekday() + 1) % 7
        sunday = (now - timedelta(days=days_since_sunday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return (sunday, None)
    if p == "month":
        return (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), None)

    return None


def parse_timestamp(ts: str) -> datetime | None:
    """Parse an ISO 8601 timestamp from session records."""
    if not ts:
        return None
    try:
        ts = ts.rstrip("Z") + "+00:00" if ts.endswith("Z") else ts
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def calc_cost(tier: str, input_t: int, output_t: int, cache_read: int, cache_write: int) -> float:
    """Calculate equivalent API cost."""
    p = ANTHROPIC_PRICING[tier]
    return (
        input_t * p["input"]
        + output_t * p["output"]
        + cache_read * p["cache_read"]
        + cache_write * p["cache_write"]
    ) / 1_000_000


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_cost(c: float) -> str:
    if c >= 1.0:
        return f"${c:.2f}"
    elif c >= 0.01:
        return f"${c:.3f}"
    elif c > 0:
        return f"${c:.4f}"
    return "$0.00"


def prettify_project_name(dirname: str) -> str:
    """Convert directory name to a readable project name."""
    name = dirname
    # Strip home path prefix (matches common patterns like -Users-xxx- or -home-xxx-)
    m = re.match(r"^-(?:Users|home)-[^-]+-?", name)
    if m:
        name = name[m.end():]
    if not name:
        name = "~ (home)"
    # Restore path separators
    name = name.replace("----", "/../../")
    name = name.replace("---", "/../")
    name = name.replace("--", "/../")
    return name


def scan_projects(
    projects_dir: str,
    since: datetime | None = None,
    until: datetime | None = None,
    model_filter: str | None = None,
) -> list[dict]:
    results = []

    for project_dir in sorted(glob.glob(os.path.join(projects_dir, "*"))):
        if not os.path.isdir(project_dir):
            continue

        project_name = prettify_project_name(os.path.basename(project_dir))
        jsonl_files = glob.glob(os.path.join(project_dir, "*.jsonl"))

        # Per-tier token accumulators
        tier_usage = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
        other_input = 0
        other_output = 0
        model_set = set()
        session_count = len(jsonl_files)

        for jf in jsonl_files:
            try:
                with open(jf, "r", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue

                        if rec.get("type") != "assistant":
                            continue

                        # Time filter
                        if since or until:
                            ts = parse_timestamp(rec.get("timestamp") or rec.get("ts", ""))
                            if ts:
                                if since and ts < since:
                                    continue
                                if until and ts >= until:
                                    continue

                        msg = rec.get("message", {})
                        model = msg.get("model", "")
                        usage = msg.get("usage", {})
                        if not usage:
                            continue

                        inp = usage.get("input_tokens", 0) or 0
                        out = usage.get("output_tokens", 0) or 0
                        cr = usage.get("cache_read_input_tokens", 0) or 0
                        cw = usage.get("cache_creation_input_tokens", 0) or 0

                        if inp == 0 and out == 0:
                            continue

                        tier = classify_model(model) if model else None

                        # Model filter
                        if model_filter:
                            mf = model_filter.lower()
                            if mf in ("opus", "sonnet", "haiku"):
                                if tier != mf:
                                    continue
                            elif mf == "other":
                                if tier is not None:
                                    continue
                            else:
                                if model and mf not in model.lower():
                                    continue

                        if model:
                            model_set.add(model)

                        if tier:
                            tier_usage[tier]["input"] += inp
                            tier_usage[tier]["output"] += out
                            tier_usage[tier]["cache_read"] += cr
                            tier_usage[tier]["cache_write"] += cw
                        else:
                            other_input += inp
                            other_output += out
            except Exception:
                pass

        # Calculate Anthropic totals and costs
        total_anthropic_tokens = 0
        total_cost = 0.0
        tier_details = []
        for tier in ["opus", "sonnet", "haiku"]:
            if tier not in tier_usage:
                continue
            u = tier_usage[tier]
            tokens = u["input"] + u["output"] + u["cache_read"] + u["cache_write"]
            cost = calc_cost(tier, u["input"], u["output"], u["cache_read"], u["cache_write"])
            total_anthropic_tokens += tokens
            total_cost += cost
            tier_details.append({
                "tier": tier,
                "input": u["input"],
                "output": u["output"],
                "cache_read": u["cache_read"],
                "cache_write": u["cache_write"],
                "tokens": tokens,
                "cost": cost,
            })

        total_all = total_anthropic_tokens + other_input + other_output

        if total_all == 0:
            continue

        results.append({
            "project": project_name,
            "sessions": session_count,
            "tier_details": tier_details,
            "anthropic_tokens": total_anthropic_tokens,
            "anthropic_cost": total_cost,
            "other_input": other_input,
            "other_output": other_output,
            "total_tokens": total_all,
            "models": sorted(model_set),
        })

    results.sort(key=lambda x: x["anthropic_cost"], reverse=True)
    return results


def truncate(s: str, width: int) -> str:
    """Truncate string to fit within given width."""
    if len(s) <= width:
        return s
    return s[: width - 2] + ".."


def get_terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100


def print_summary(results: list[dict], filter_label: str = ""):
    """Print formatted summary table."""
    c_cyan = "\033[36m"
    c_bright_green = "\033[92m"
    c_green = "\033[32m"
    c_yellow = "\033[33m"
    c_bright_yellow = "\033[93m"
    c_red = "\033[31m"
    c_bright_red = "\033[91m"
    c_dim = "\033[2m"
    c_bold = "\033[1m"
    c_reset = "\033[0m"

    def cost_color(cost):
        if cost >= 500:
            return c_bright_red
        if cost >= 250:
            return c_red
        if cost >= 100:
            return c_bright_yellow
        if cost >= 50:
            return c_yellow
        if cost >= 25:
            return c_green
        return c_bright_green

    # Fixed column widths
    col_sess = 10
    col_anth = 12
    col_other = 10
    col_cost = 12
    right_cols = col_sess + col_anth + col_other + col_cost + 4  # +4 for spacing

    # Dynamic project name column width based on terminal size (clamped 20~50)
    term_w = get_terminal_width()
    name_w = max(20, min(50, term_w - right_cols - 4))  # -4 for left padding

    total_w = name_w + right_cols + 4

    print(f"\n{c_bold}Claude Code Usage Summary{c_reset}")
    if filter_label:
        print(f"  {c_dim}{filter_label}{c_reset}")
    print(f"{c_dim}{'─' * total_w}{c_reset}\n")

    header = (
        f"  {'Project':<{name_w}}"
        f" {'Sessions':>{col_sess}}"
        f" {'Anthropic':>{col_anth}}"
        f" {'Other':>{col_other}}"
        f" {'Est. Cost':>{col_cost}}"
    )
    print(f"{c_bold}{header}{c_reset}")
    print(f"  {'─' * (total_w - 2)}")

    grand_anthropic = 0
    grand_other = 0
    grand_cost = 0.0

    for r in results:
        cost = r["anthropic_cost"]
        proj_name = truncate(r["project"], name_w)
        other_total = r["other_input"] + r["other_output"]
        print(
            f"  {c_cyan}{proj_name:<{name_w}}{c_reset}"
            f" {r['sessions']:>{col_sess}}"
            f" {fmt_tokens(r['anthropic_tokens']):>{col_anth}}"
            f" {fmt_tokens(other_total):>{col_other}}"
            f" {cost_color(cost)}{fmt_cost(r['anthropic_cost']):>{col_cost}}{c_reset}"
        )

        # Tier breakdown
        for td in r["tier_details"]:
            tier_label = td["tier"].capitalize()
            detail = (
                f"in:{fmt_tokens(td['input'])} "
                f"out:{fmt_tokens(td['output'])} "
                f"cR:{fmt_tokens(td['cache_read'])} "
                f"cW:{fmt_tokens(td['cache_write'])}"
            )
            left_part = f"  └ {tier_label:<8} {detail}"
            # Pad to right-align cost
            pad = total_w - len(left_part) - 2  # -2 for leading spaces
            if pad < 1:
                pad = 1
            print(
                f"  {c_dim}{left_part}{fmt_cost(td['cost']):>{pad}}{c_reset}"
            )

        grand_anthropic += r["anthropic_tokens"]
        grand_other += other_total
        grand_cost += cost

    print(f"  {'─' * (total_w - 2)}")

    total_color = cost_color(grand_cost)
    print(
        f"  {c_bold}{'TOTAL':<{name_w}}{c_reset}"
        f" {'':>{col_sess}}"
        f" {c_bold}{fmt_tokens(grand_anthropic):>{col_anth}}{c_reset}"
        f" {fmt_tokens(grand_other):>{col_other}}"
        f" {total_color}{c_bold}{fmt_cost(grand_cost):>{col_cost}}{c_reset}"
    )
    print()


def print_json(results: list[dict]):
    """Print JSON output."""
    output = {
        "projects": results,
        "grand_total": {
            "anthropic_tokens": sum(r["anthropic_tokens"] for r in results),
            "anthropic_cost_usd": round(sum(r["anthropic_cost"] for r in results), 4),
            "other_tokens": sum(r["other_input"] + r["other_output"] for r in results),
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code session usage & cost calculator",
        epilog=(
            "period examples (--since/--until): today, yesterday, week, month, year, 3d, 2w, 6m, 2026-03-01\n"
            "calendar windows (--at):          today/day, yesterday, week (from Sunday), month (from 1st)\n"
            "model examples:                   opus, sonnet, haiku, other, gemini"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--since", "-s",
        metavar="PERIOD",
        default="week",
        help="Filter by time period (default: week) (today, yesterday, week, month, year, Nd, Nw, Nm, YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until", "-u",
        metavar="PERIOD",
        help="End of time window (today, yesterday, week, month, year, Nd, Nw, Nm, YYYY-MM-DD)",
    )
    parser.add_argument(
        "--at", "-a",
        metavar="WINDOW",
        help="Calendar window (today/day, yesterday, week, month). Overrides --since/--until.",
    )
    parser.add_argument(
        "--model", "-m",
        metavar="MODEL",
        help="Filter by model (opus, sonnet, haiku, other, or substring match)",
    )
    parser.add_argument(
        "--projects-dir",
        default=os.path.expanduser("~/.claude/projects"),
        help="Projects directory (default: ~/.claude/projects)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.projects_dir):
        print(f"Projects directory not found: {args.projects_dir}", file=sys.stderr)
        sys.exit(1)

    since = None
    until = None

    if getattr(args, "at", None):
        parsed = parse_at(args.at)
        if parsed is None:
            print(f"Invalid calendar window: {args.at}", file=sys.stderr)
            print("Examples: today, day, yesterday, week, month", file=sys.stderr)
            sys.exit(1)
        since, until = parsed
    else:
        if args.since:
            parsed = parse_period(args.since)
            if parsed is None:
                print(f"Invalid period: {args.since}", file=sys.stderr)
                print("Examples: today, yesterday, week, month, year, 3d, 2w, 6m, 2026-03-01", file=sys.stderr)
                sys.exit(1)
            since, until = parsed

        if args.until:
            parsed = parse_period(args.until)
            if parsed is None:
                print(f"Invalid until period: {args.until}", file=sys.stderr)
                sys.exit(1)
            # Use the start of the parsed period as the upper bound
            until = parsed[0]

    results = scan_projects(args.projects_dir, since=since, until=until, model_filter=args.model)

    if not results:
        print("No projects with usage data found.")
        return

    # Build filter label
    filters = []
    if since or until:
        time_parts = []
        if since:
            time_parts.append(since.strftime('%Y-%m-%d %H:%M'))
        else:
            time_parts.append("...")
        time_parts.append("~")
        if until:
            time_parts.append(until.strftime('%Y-%m-%d %H:%M'))
        else:
            time_parts.append("now")
        filters.append(f"({' '.join(time_parts)} UTC)")
    if args.model:
        filters.append(f"model: {args.model}")
    filter_label = "  ".join(filters)

    if args.json:
        print_json(results)
    else:
        print_summary(results, filter_label)


if __name__ == "__main__":
    main()
