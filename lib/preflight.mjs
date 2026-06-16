// Preflight cost prediction (Node port of the V2 model — advisory by default).
// A paid agent with a `cost_model` in its config turns a chore's est_context_tokens
// into a {lo, hi} dollar range. Dormant in V1 (no source populates est_context_tokens
// and no agent ships a cost_model), so estimate() returns null and nothing changes.
// The per-task-cap GATE is opt-in (`preflight.mode: gate`) and stays off until an
// operator's own replay clears the report's ≥70% bracket bar.

export function parseCostModel(options = {}) {
  const cm = options.cost_model;
  if (!cm) return null;
  return {
    input_per_mtok: Number(cm.input_per_mtok),
    output_per_mtok: Number(cm.output_per_mtok),
    expected_output_tokens: Number(cm.expected_output_tokens ?? 1500),
    hi_multiplier: Number(cm.hi_multiplier ?? 2.5),   // upper band absorbs agentic loops / retries
  };
}

// -> { lo, hi } in USD, or null when there is no cost model (dormant).
export function estimateUsd(estContextTokens, model) {
  if (!model) return null;
  const ctx = estContextTokens || 0;
  const lo = (ctx / 1_000_000) * model.input_per_mtok
    + (model.expected_output_tokens / 1_000_000) * model.output_per_mtok;
  const round = (n) => Math.round(n * 1e4) / 1e4;
  return { lo: round(lo), hi: round(lo * model.hi_multiplier) };
}
