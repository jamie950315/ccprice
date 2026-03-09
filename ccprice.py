#!/usr/bin/env python3
"""Claude Code 專案用量統計與 Anthropic 模型等效費用計算"""

import json
import os
import sys
import glob
import argparse
from collections import defaultdict

# Anthropic 模型定價 (USD per 1M tokens)
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

# 模型 ID → 定價類別
MODEL_PATTERNS = {
    "opus": ["opus"],
    "sonnet": ["sonnet"],
    "haiku": ["haiku"],
}


def classify_model(model_id: str) -> str | None:
    """將模型 ID 分類為 opus/sonnet/haiku，非 Anthropic 模型回傳 None"""
    mid = model_id.lower()
    # 排除非 Anthropic 模型
    non_anthropic = ["google/", "gemini", "openai/", "gpt", "minimax/", "<synthetic>"]
    if any(prefix in mid for prefix in non_anthropic):
        return None
    for tier, keywords in MODEL_PATTERNS.items():
        if any(kw in mid for kw in keywords):
            return tier
    return None


def calc_cost(tier: str, input_t: int, output_t: int, cache_read: int, cache_write: int) -> float:
    """計算等效 API 費用"""
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
    """將目錄名稱轉為可讀的專案名稱"""
    name = dirname
    # 移除 home 路徑前綴
    home_prefixes = ["-Users-jamie-", "-Users-jamie"]
    for prefix in home_prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    if not name:
        name = "~ (home)"
    # 將 ---- 還原為 /../../
    name = name.replace("----", "/../../")
    name = name.replace("---", "/../")
    name = name.replace("--", "/../")
    return name


def scan_projects(projects_dir: str) -> list[dict]:
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

                        if model:
                            model_set.add(model)

                        tier = classify_model(model) if model else None
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

        # 計算 Anthropic 總 token 與費用
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
    """截斷字串並加省略號，確保不超過指定寬度"""
    if len(s) <= width:
        return s
    return s[: width - 2] + ".."


def get_terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100


def print_summary(results: list[dict]):
    """輸出摘要表格"""
    c_cyan = "\033[36m"
    c_green = "\033[32m"
    c_yellow = "\033[33m"
    c_red = "\033[31m"
    c_dim = "\033[2m"
    c_bold = "\033[1m"
    c_reset = "\033[0m"

    # 固定欄位寬度
    col_sess = 10
    col_anth = 12
    col_other = 10
    col_cost = 12
    right_cols = col_sess + col_anth + col_other + col_cost + 4  # +4 for spacing

    # 動態計算專案名稱欄寬：取終端寬度扣掉右側欄位，但限制在 20~50 之間
    term_w = get_terminal_width()
    name_w = max(20, min(50, term_w - right_cols - 4))  # -4 for left padding

    total_w = name_w + right_cols + 4

    print(f"\n{c_bold}Claude Code 專案用量統計{c_reset}")
    print(f"{c_dim}{'─' * total_w}{c_reset}\n")

    header = (
        f"  {'專案':<{name_w}}"
        f" {'Sessions':>{col_sess}}"
        f" {'Anthropic':>{col_anth}}"
        f" {'其他':>{col_other}}"
        f" {'等效費用':>{col_cost}}"
    )
    print(f"{c_bold}{header}{c_reset}")
    print(f"  {'─' * (total_w - 2)}")

    grand_anthropic = 0
    grand_other = 0
    grand_cost = 0.0

    for r in results:
        cost = r["anthropic_cost"]
        if cost >= 10:
            cost_color = c_red
        elif cost >= 1:
            cost_color = c_yellow
        else:
            cost_color = c_green

        proj_name = truncate(r["project"], name_w)
        other_total = r["other_input"] + r["other_output"]
        print(
            f"  {c_cyan}{proj_name:<{name_w}}{c_reset}"
            f" {r['sessions']:>{col_sess}}"
            f" {fmt_tokens(r['anthropic_tokens']):>{col_anth}}"
            f" {fmt_tokens(other_total):>{col_other}}"
            f" {cost_color}{fmt_cost(r['anthropic_cost']):>{col_cost}}{c_reset}"
        )

        # 顯示各 tier 明細
        for td in r["tier_details"]:
            tier_label = td["tier"].capitalize()
            # 明細行：左邊對齊到專案名稱欄內，右邊費用對齊到等效費用欄
            detail = (
                f"in:{fmt_tokens(td['input'])} "
                f"out:{fmt_tokens(td['output'])} "
                f"cR:{fmt_tokens(td['cache_read'])} "
                f"cW:{fmt_tokens(td['cache_write'])}"
            )
            left_part = f"  └ {tier_label:<8} {detail}"
            # 計算需要填充的寬度讓費用靠右對齊
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

    cost_color = c_red if grand_cost >= 10 else c_yellow if grand_cost >= 1 else c_green
    print(
        f"  {c_bold}{'TOTAL':<{name_w}}{c_reset}"
        f" {'':>{col_sess}}"
        f" {c_bold}{fmt_tokens(grand_anthropic):>{col_anth}}{c_reset}"
        f" {fmt_tokens(grand_other):>{col_other}}"
        f" {cost_color}{c_bold}{fmt_cost(grand_cost):>{col_cost}}{c_reset}"
    )
    print()


def print_json(results: list[dict]):
    """輸出 JSON 格式"""
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
    parser = argparse.ArgumentParser(description="Claude Code 專案用量統計")
    parser.add_argument("--json", action="store_true", help="輸出 JSON 格式")
    parser.add_argument(
        "--projects-dir",
        default=os.path.expanduser("~/.claude/projects"),
        help="專案目錄路徑 (預設: ~/.claude/projects)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.projects_dir):
        print(f"找不到專案目錄: {args.projects_dir}", file=sys.stderr)
        sys.exit(1)

    results = scan_projects(args.projects_dir)

    if not results:
        print("沒有找到任何有用量記錄的專案。")
        return

    if args.json:
        print_json(results)
    else:
        print_summary(results)


if __name__ == "__main__":
    main()
