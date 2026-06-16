import { test } from 'node:test';
import assert from 'node:assert';
import { parseCostModel, estimateUsd } from '../lib/preflight.mjs';

test('no cost_model → dormant (null estimate), the V1 default', () => {
  assert.equal(parseCostModel({}), null);
  assert.equal(estimateUsd(50000, null), null);
});

test('cost_model turns context tokens into a {lo, hi} dollar range', () => {
  const m = parseCostModel({ cost_model: { input_per_mtok: 3, output_per_mtok: 15, expected_output_tokens: 1000, hi_multiplier: 2 } });
  const est = estimateUsd(1_000_000, m);
  // 1M input @ $3/M = $3.00 + 1k output @ $15/M = $0.015  → lo 3.015, hi ×2 = 6.03
  assert.equal(est.lo, 3.015);
  assert.equal(est.hi, 6.03);
});

test('defaults fill in expected_output_tokens and hi_multiplier', () => {
  const m = parseCostModel({ cost_model: { input_per_mtok: 3, output_per_mtok: 15 } });
  assert.equal(m.expected_output_tokens, 1500);
  assert.equal(m.hi_multiplier, 2.5);
  const est = estimateUsd(0, m);   // no context → just expected output
  assert.ok(est.lo > 0 && est.hi === Math.round(est.lo * 2.5 * 1e4) / 1e4);
});
