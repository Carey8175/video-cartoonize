/**
 * Tests for data.js mock state generation.
 * Focuses on invariants that the real backend must also satisfy.
 */
import { describe, it, expect } from 'vitest';
import { INITIAL_STATE, STYLES, MODELS } from '../data.js';

const { clips } = INITIAL_STATE;

// ── Clip status → cartoon presence ────────────────────────────────────────
// P1 fix: cartoon must be null for split/keyframes clips (Codex review)
describe('clip.subshots[].cartoon correctness', () => {
  const STAGES_WITHOUT_CARTOON = ['split', 'keyframes'];
  const STAGES_WITH_CARTOON    = ['cartoon_ready', 'polling', 'done'];

  it('cartoon is null for split and keyframes clips', () => {
    const violations = clips
      .filter(c => STAGES_WITHOUT_CARTOON.includes(c.status))
      .flatMap(c =>
        c.subshots
          .filter(s => s.cartoon !== null)
          .map(s => ({ clip_id: c.clip_id, status: c.status, sub_idx: s.idx }))
      );
    expect(violations).toEqual([]);
  });

  it('cartoon is non-null for cartoon_ready / polling / done clips', () => {
    const violations = clips
      .filter(c => STAGES_WITH_CARTOON.includes(c.status))
      .flatMap(c =>
        c.subshots
          .filter(s => s.cartoon === null)
          .map(s => ({ clip_id: c.clip_id, status: c.status, sub_idx: s.idx }))
      );
    expect(violations).toEqual([]);
  });
});

// ── Clip counts match expected distribution ────────────────────────────────
describe('mock data distribution', () => {
  it('has exactly 21 clips', () => {
    expect(clips).toHaveLength(21);
  });

  it('has 5 done clips', () => {
    expect(clips.filter(c => c.status === 'done')).toHaveLength(5);
  });

  it('has 5 polling clips', () => {
    expect(clips.filter(c => c.status === 'polling')).toHaveLength(5);
  });

  it('all clip_ids are unique', () => {
    const ids = clips.map(c => c.clip_id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// ── Subshot structure ──────────────────────────────────────────────────────
describe('subshot structure', () => {
  it('every subshot has t_start < t_end', () => {
    const bad = clips.flatMap(c =>
      c.subshots
        .filter(s => s.t_start >= s.t_end)
        .map(s => ({ clip_id: c.clip_id, idx: s.idx, t_start: s.t_start, t_end: s.t_end }))
    );
    expect(bad).toEqual([]);
  });

  it('vlm_pass is null for clips not yet cartoonized', () => {
    const bad = clips
      .filter(c => ['split', 'keyframes'].includes(c.status))
      .flatMap(c =>
        c.subshots
          .filter(s => s.vlm_pass !== null)
          .map(s => ({ clip_id: c.clip_id, sub: s.idx, vlm_pass: s.vlm_pass }))
      );
    expect(bad).toEqual([]);
  });

  it('n_subshots matches actual subshots array length', () => {
    const bad = clips.filter(c => c.n_subshots !== c.subshots.length);
    expect(bad).toEqual([]);
  });
});

// ── Config ────────────────────────────────────────────────────────────────
describe('INITIAL_STATE config', () => {
  it('style_id is a known style', () => {
    const ids = STYLES.map(s => s.id);
    expect(ids).toContain(INITIAL_STATE.config.style_id);
  });

  it('scene_threshold is positive', () => {
    expect(INITIAL_STATE.config.scene_threshold).toBeGreaterThan(0);
  });
});

// ── STYLES & MODELS ───────────────────────────────────────────────────────
describe('STYLES', () => {
  it('has 7 style options', () => {
    expect(STYLES).toHaveLength(7);
  });

  it('every style has id, name, blurb', () => {
    for (const s of STYLES) {
      expect(s).toHaveProperty('id');
      expect(s).toHaveProperty('name');
      expect(s).toHaveProperty('blurb');
    }
  });

  it('includes custom style', () => {
    expect(STYLES.find(s => s.id === 'custom')).toBeDefined();
  });
});

describe('MODELS', () => {
  it('has 3 model options', () => {
    expect(MODELS).toHaveLength(3);
  });

  it('Pro model has token-based pricing', () => {
    const pro = MODELS.find(m => m.tier === 'Pro');
    expect(pro).toBeDefined();
    expect(pro.price_out).toMatch(/^\$/);
  });

  it('custom model has null pricing', () => {
    const custom = MODELS.find(m => m.id === 'custom');
    expect(custom.price_in).toBeNull();
    expect(custom.price_out).toBeNull();
  });
});
