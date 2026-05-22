/**
 * Smoke tests for App rendering — verify all 6 stages mount without crashing.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import App from '../App.jsx';

// Mock Google Fonts (jsdom doesn't fetch external resources)
beforeEach(() => {
  document.documentElement.style.setProperty = () => {};
});

describe('App smoke tests', () => {
  it('renders top bar brand mark', () => {
    render(<App />);
    // The brand-mark span contains the single letter "C"
    expect(document.querySelector('.brand-mark')).toBeTruthy();
    expect(document.querySelector('.brand-mark').textContent).toBe('C');
  });

  it('renders all 6 pipeline stage names in the rail', () => {
    render(<App />);
    // Rail step-name divs — use class selector to avoid ambiguity
    const stageNames = Array.from(document.querySelectorAll('.step-name')).map(el => el.textContent);
    expect(stageNames).toContain('Setup');
    expect(stageNames).toContain('Source');
    expect(stageNames).toContain('Clips');
    expect(stageNames).toContain('Keyframes');
    expect(stageNames).toContain('Cartoonized clip');
    expect(stageNames).toContain('Mux & merge');
  });

  it('starts on Clips stage by default', () => {
    render(<App />);
    // Main heading h1 contains "Clips"
    const h1 = document.querySelector('.main-head h1');
    expect(h1.textContent).toBe('Clips (scene-split)');
  });

  it('navigates to Setup when clicking Setup rail item', () => {
    render(<App />);
    // Click the first stage-row (Setup)
    fireEvent.click(document.querySelectorAll('.stage-row')[0]);
    expect(screen.getByText('Credentials')).toBeTruthy();
  });

  it('navigates to Keyframes stage', () => {
    render(<App />);
    fireEvent.click(document.querySelectorAll('.stage-row')[3]);
    const h1 = document.querySelector('.main-head h1');
    expect(h1.textContent).toBe('Keyframes');
  });

  it('navigates to Mux & merge stage', () => {
    render(<App />);
    fireEvent.click(document.querySelectorAll('.stage-row')[5]);
    expect(screen.getByText(/Mux & merge final video/)).toBeTruthy();
  });

  it('shows clip board handle at bottom', () => {
    render(<App />);
    expect(document.querySelector('.board-handle .title').textContent).toBe('Clip board');
  });

  it('right rail shows This task panel', () => {
    render(<App />);
    expect(document.querySelector('.tasks-head h3').textContent).toBe('This task');
  });
});

describe('Regen modal', () => {
  it('does not render modal by default', () => {
    render(<App />);
    expect(screen.queryByText('Regenerate')).toBeFalsy();
  });
});
