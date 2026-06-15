"""Morning report (U14) — the honest artifact.

Always prints each paid lane's utilization every night, so honesty is structural,
not gated on a threshold (R20/R27). Recommends downgrading a paid lane when, over
the last ``window_nights``, its spend is below ``spend_pct_threshold`` of its
budget AND its lane-attributable passes are below ``min_passes`` — pass-per-dollar
is first-class, so a high-spend/low-pass lane also triggers (R18/AE6).
"""

from __future__ import annotations

from datetime import datetime, timedelta


def _paid_lanes(config) -> dict:
    """name → nightly_budget for lanes that cost money (unit usd)."""
    out = {}
    for b in config.backends:
        budget = b.options.get("nightly_budget")
        if budget:
            out[b.name] = float(budget)
    return out


def _window_start(night_start: str, nights: int) -> str:
    try:
        d = datetime.fromisoformat(night_start)
    except ValueError:
        return night_start
    return (d - timedelta(days=nights)).isoformat()


def downgrade_candidates(config, ledger, night_start: str) -> list:
    """Return [(lane, evidence)] for lanes that should be downgraded."""
    dg = config.report.downgrade
    win_start = _window_start(night_start, dg.window_nights)
    hist = ledger.lane_summary(win_start)
    out = []
    for lane, budget in _paid_lanes(config).items():
        s = hist.get(lane, {"consumed": 0.0, "passes": 0, "attempts": 0})
        if s["attempts"] == 0:
            continue  # never nag an unused/young lane — no evidence to act on
        budget_window = budget * dg.window_nights
        util = (s["consumed"] / budget_window) if budget_window > 0 else 0.0
        low_pass = s["passes"] < dg.min_passes
        underused = util < dg.spend_pct_threshold
        # recommend on too-few-passes when the lane is EITHER under-used (low spend)
        # OR paying-for-failure (spent money for too few passes) — pass-per-dollar first-class.
        if low_pass and (underused or s["consumed"] > 0):
            out.append((lane, {
                "window_nights": dg.window_nights,
                "spend": s["consumed"], "budget_window": budget_window,
                "utilization_pct": round(util * 100, 1), "passes": s["passes"],
            }))
    return out


def generate(config, ledger, summary, inventory: dict, night_start: str) -> str:
    paid = _paid_lanes(config)
    tonight = ledger.lane_summary(night_start)
    rows = ledger.runs_since(night_start)
    lines = [f"# Nightsweeper morning report — {night_start[:10]}", ""]

    if summary.tasks_total == 0:
        lines += ["**No backlog, no run.** No tasks were returned by any configured source.",
                  "Nightsweeper never invents work."]
        text = "\n".join(lines) + "\n"
        _write(config, text)
        return text

    lines += [
        "## Summary",
        f"- Tasks seen: **{summary.tasks_total}**",
        f"- Dispatched: **{summary.dispatched}** · Passed: **{summary.passed}** · "
        f"Parked: **{summary.parked}**",
        f"- Backlog remaining (unprocessed this night): **{summary.backlog_remaining}**",
        f"- Stop reason: `{summary.stop_reason}`",
        "",
        "## Per-lane consumption (tonight)",
        "| Lane | Attempts | Passes | $ consumed | Utilization |",
        "|---|---:|---:|---:|---|",
    ]
    for b in sorted(config.backends, key=lambda x: x.cost_rank):
        s = tonight.get(b.name, {"consumed": 0.0, "passes": 0, "attempts": 0})
        if b.name in paid:
            budget = paid[b.name]
            util = f"{round(100*s['consumed']/budget,1)}% of ${budget:.2f} budget"
            ppd = (s["passes"] / s["consumed"]) if s["consumed"] > 0 else 0.0
            util += f" · {ppd:.2f} passes/$"
            spend = f"${s['consumed']:.2f}"
        else:
            util, spend = "free ($0)", "$0.00"
        lines.append(f"| {b.name} | {s['attempts']} | {s['passes']} | {spend} | {util} |")

    lines += ["", "## Backlog"]
    parked_rows = [r for r in rows
                   if r["park_reason"] or r["validation_result"] in ("parked", "skipped")]
    lines.append(f"- Parked for human review: **{summary.parked}**")
    lines.append(f"- Bare (un-enrolled) TODO/FIXME markers (not dispatched): "
                 f"**{inventory.get('bare_todo_count', 0)}**")
    if parked_rows:
        lines.append("")
        lines.append("Parked tasks:")
        for r in parked_rows:
            reason = r["park_reason"] or r["validation_result"]
            lines.append(f"  - `{r['task_id']}` ({r['backend']}) — {reason}")

    cands = downgrade_candidates(config, ledger, night_start)
    lines += ["", "## Plan utilization & recommendations"]
    if not paid:
        lines.append("- No paid lanes configured.")
    for lane, budget in paid.items():
        s = tonight.get(lane, {"consumed": 0.0})
        lines.append(f"- `{lane}`: spent ${s['consumed']:.2f} of ${budget:.2f} tonight "
                     f"(utilization always reported, recommendation or not).")
    for lane, ev in cands:
        lines.append(
            f"- **Recommend downgrading `{lane}`.** Over the last {ev['window_nights']} nights it "
            f"used ${ev['spend']:.2f} of ${ev['budget_window']:.2f} ({ev['utilization_pct']}%) "
            f"and cleared {ev['passes']} task(s). Honesty over engagement — you are paying for "
            f"capacity you are not using."
        )

    # Dormant V2 line: only rendered once predicted_lo/hi are populated.
    if any(r["predicted_lo"] is not None for r in rows):
        lines += ["", "## Preflight accuracy (V2)",
                  "- (predicted-vs-actual bracketing line renders here when preflight is active.)"]

    text = "\n".join(lines) + "\n"
    _write(config, text)
    return text


def _write(config, text: str) -> None:
    try:
        with open(config.report.path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
