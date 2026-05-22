/**
 * Tests for shared utility functions in components.jsx.
 */
import { describe, it, expect } from 'vitest';
import { fmt, statusTag } from '../components.jsx';

describe('fmt.dur', () => {
  it('formats zero as 0:00', () => {
    expect(fmt.dur(0)).toBe('0:00');
  });

  it('formats 90s as 1:30', () => {
    expect(fmt.dur(90)).toBe('1:30');
  });

  it('formats 142.6s correctly', () => {
    expect(fmt.dur(142.6)).toBe('2:22');
  });

  it('returns — for null', () => {
    expect(fmt.dur(null)).toBe('—');
  });

  it('pads seconds below 10', () => {
    expect(fmt.dur(65)).toBe('1:05');
  });
});

describe('fmt.shortTask', () => {
  it('truncates long task IDs', () => {
    const id = 'cgt-20260514203653-56rsx';
    const result = fmt.shortTask(id);
    expect(result).toContain('…');
    expect(result.length).toBeLessThan(id.length);
  });

  it('returns — for empty string', () => {
    expect(fmt.shortTask('')).toBe('—');
  });

  it('returns — for null/undefined', () => {
    expect(fmt.shortTask(null)).toBe('—');
  });
});

describe('fmt.bytes', () => {
  it('formats MB with one decimal', () => {
    expect(fmt.bytes(38.4)).toBe('38.4 MB');
  });

  it('rounds to one decimal place', () => {
    expect(fmt.bytes(38)).toBe('38.0 MB');
  });
});

describe('statusTag', () => {
  const cases = [
    ['done',          'ok',     'Done'],
    ['polling',       'run',    'Polling'],
    ['cartoon_ready', 'warn',   'Cartoon ready'],
    ['keyframes',     'accent', 'Keyframes'],
    ['split',         'idle',   'Split'],
    ['succeeded',     'ok',     'Succeeded'],
    ['running',       'run',    'Running'],
    ['queued',        'warn',   'Queued'],
    ['failed',        'bad',    'Failed'],
  ];

  it.each(cases)('statusTag(%s) → tone=%s label=%s', (status, tone, label) => {
    const result = statusTag(status);
    expect(result.tone).toBe(tone);
    expect(result.label).toBe(label);
  });

  it('returns idle for unknown status', () => {
    const result = statusTag('unknown_xyz');
    expect(result.tone).toBe('idle');
    expect(result.label).toBe('unknown_xyz');
  });
});
