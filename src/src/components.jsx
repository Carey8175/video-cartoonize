import React from 'react';

// ─── Icons (inline SVGs) ──────────────────────────────────────────────────
export function Icon({ name, size = 14, className = '' }) {
  const props = {
    width: size, height: size, viewBox: '0 0 16 16',
    fill: 'none', stroke: 'currentColor',
    strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
    className,
  };
  switch (name) {
    case 'check':   return <svg {...props}><polyline points="3 8 6.5 11.5 13 4.5" /></svg>;
    case 'x':       return <svg {...props}><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>;
    case 'play':    return <svg {...props}><polygon points="4.5 3.5 12.5 8 4.5 12.5" fill="currentColor" stroke="none"/></svg>;
    case 'pause':   return <svg {...props}><rect x="4" y="3" width="3" height="10" fill="currentColor" stroke="none"/><rect x="9" y="3" width="3" height="10" fill="currentColor" stroke="none"/></svg>;
    case 'refresh': return <svg {...props}><path d="M13 3.5v3h-3" /><path d="M3 8a5 5 0 0 1 9.5-2.2L13 6.5"/><path d="M3 12.5v-3h3"/><path d="M13 8a5 5 0 0 1-9.5 2.2L3 9.5"/></svg>;
    case 'download':return <svg {...props}><path d="M8 2.5v8"/><polyline points="4.5 7 8 10.5 11.5 7"/><line x1="2.5" y1="13" x2="13.5" y2="13"/></svg>;
    case 'upload':  return <svg {...props}><path d="M8 13.5v-9"/><polyline points="4.5 8 8 4.5 11.5 8"/><line x1="2.5" y1="13.5" x2="13.5" y2="13.5"/></svg>;
    case 'chevron-down':  return <svg {...props}><polyline points="3.5 6 8 10.5 12.5 6"/></svg>;
    case 'chevron-right': return <svg {...props}><polyline points="6 3.5 10.5 8 6 12.5"/></svg>;
    case 'film':    return <svg {...props}><rect x="2" y="2.5" width="12" height="11" rx="1"/><line x1="2" y1="5" x2="14" y2="5"/><line x1="2" y1="11" x2="14" y2="11"/><line x1="5" y1="2.5" x2="5" y2="13.5"/><line x1="11" y1="2.5" x2="11" y2="13.5"/></svg>;
    case 'image':   return <svg {...props}><rect x="2" y="2.5" width="12" height="11" rx="1"/><circle cx="6" cy="6" r="1"/><path d="M14 11l-3.5-3.5L4 13.5"/></svg>;
    case 'brain':   return <svg {...props}><path d="M5.5 3.5a2 2 0 0 0-2 2v.3a2 2 0 0 0-1 1.7v.5a2 2 0 0 0 1 1.8V11a2 2 0 0 0 4 0V3.5a2 2 0 0 0-2 0z"/><path d="M10.5 3.5a2 2 0 0 1 2 2v.3a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.8V11a2 2 0 0 1-4 0V3.5a2 2 0 0 1 2 0z"/></svg>;
    case 'video':   return <svg {...props}><rect x="2" y="3.5" width="9" height="9" rx="1"/><polygon points="11 6 14 4 14 12 11 10" fill="currentColor" stroke="none" /></svg>;
    case 'merge':   return <svg {...props}><path d="M3 3v3a4 4 0 0 0 4 4h5"/><path d="M13 3v3a4 4 0 0 1-4 4H4"/><polyline points="10.5 7.5 13 10 10.5 12.5"/></svg>;
    case 'settings':return <svg {...props}><circle cx="8" cy="8" r="2"/><path d="M8 2v1.5M8 12.5V14M14 8h-1.5M3.5 8H2M12.3 3.7l-1 1M4.7 11.3l-1 1M12.3 12.3l-1-1M4.7 4.7l-1-1"/></svg>;
    case 'key':     return <svg {...props}><circle cx="11" cy="5" r="2.5"/><path d="M9.2 6.8L3 13l1.5 1.5L5.5 13.5l1 1L7.5 13.5l1 1L10 13"/></svg>;
    case 'cpu':     return <svg {...props}><rect x="4" y="4" width="8" height="8" rx="1"/><line x1="6" y1="1.5" x2="6" y2="4"/><line x1="10" y1="1.5" x2="10" y2="4"/><line x1="6" y1="12" x2="6" y2="14.5"/><line x1="10" y1="12" x2="10" y2="14.5"/><line x1="14.5" y1="6" x2="12" y2="6"/><line x1="14.5" y1="10" x2="12" y2="10"/><line x1="1.5" y1="6" x2="4" y2="6"/><line x1="1.5" y1="10" x2="4" y2="10"/></svg>;
    case 'eye':     return <svg {...props}><path d="M1.5 8s2.5-5 6.5-5 6.5 5 6.5 5-2.5 5-6.5 5-6.5-5-6.5-5z"/><circle cx="8" cy="8" r="2"/></svg>;
    case 'edit':    return <svg {...props}><path d="M2.5 13.5v-2L11 3l2 2-8.5 8.5h-2z"/><line x1="9.5" y1="4.5" x2="11.5" y2="6.5"/></svg>;
    case 'plus':    return <svg {...props}><line x1="8" y1="3" x2="8" y2="13"/><line x1="3" y1="8" x2="13" y2="8"/></svg>;
    case 'sparkle': return <svg {...props}><path d="M8 2 L9 6 L13 7 L9 8 L8 12 L7 8 L3 7 L7 6 Z" fill="currentColor" stroke="none"/></svg>;
    case 'circle':  return <svg {...props}><circle cx="8" cy="8" r="5"/></svg>;
    case 'circle-filled': return <svg {...props}><circle cx="8" cy="8" r="5" fill="currentColor" stroke="none"/></svg>;
    case 'arrow-right': return <svg {...props}><line x1="3" y1="8" x2="13" y2="8"/><polyline points="9.5 4.5 13 8 9.5 11.5"/></svg>;
    case 'copy':    return <svg {...props}><rect x="5" y="5" width="8" height="8" rx="1"/><path d="M5 11H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v1"/></svg>;
    case 'logs':    return <svg {...props}><rect x="2.5" y="2.5" width="11" height="11" rx="1"/><line x1="5" y1="6" x2="11" y2="6"/><line x1="5" y1="8.5" x2="11" y2="8.5"/><line x1="5" y1="11" x2="8" y2="11"/></svg>;
    case 'history': return <svg {...props}><path d="M2.5 8a5.5 5.5 0 1 0 1.6-3.9"/><polyline points="2.5 2.5 2.5 5.5 5.5 5.5"/><polyline points="8 5 8 8.5 10.5 10"/></svg>;
    default: return null;
  }
}

// ─── Status helpers ────────────────────────────────────────────────────────
export function statusTag(status) {
  const map = {
    done:           { tone: 'ok',   label: 'Done' },
    polling:        { tone: 'run',  label: 'Polling' },
    cartoon_ready:  { tone: 'warn', label: 'Cartoon ready' },
    keyframes:      { tone: 'accent', label: 'Keyframes' },
    split:          { tone: 'idle', label: 'Split' },
    pending:        { tone: 'idle', label: 'Pending' },
    succeeded:      { tone: 'ok',   label: 'Succeeded' },
    running:        { tone: 'run',  label: 'Running' },
    queued:         { tone: 'warn', label: 'Queued' },
    failed:         { tone: 'bad',  label: 'Failed' },
  };
  return map[status] || { tone: 'idle', label: status };
}

export function Tag({ tone = 'idle', children, dot, mono = true }) {
  return (
    <span className={`tag ${tone}`} style={mono ? null : { fontFamily: 'var(--font-sans)' }}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

export function Btn({ variant = 'default', children, icon, kbd, onClick, disabled, title }) {
  return (
    <button
      className={`btn ${variant === 'default' ? '' : variant}`}
      onClick={onClick}
      disabled={disabled}
      title={title}
    >
      {icon && <Icon name={icon} size={12} />}
      {children}
      {kbd && <span className="kbd">{kbd}</span>}
    </button>
  );
}

// ─── Metric tile row ───────────────────────────────────────────────────────
export function MetricRow({ items }) {
  return (
    <div className="metric-row">
      {items.map((m, i) => (
        <div className="metric" key={i}>
          <div className="k">{m.k}</div>
          <div className="v">{m.v}{m.unit && <span className="unit">{m.unit}</span>}</div>
          {m.sub && <div className="sub">{m.sub}</div>}
        </div>
      ))}
    </div>
  );
}

// ─── Thumb ─────────────────────────────────────────────────────────────────
export function Thumb({ src, stamp, timecode, alt = '' }) {
  return (
    <div className="thumb">
      {src ? <img src={src} alt={alt} /> : <div style={{ aspectRatio: '9 / 16', background: '#111' }} />}
      {stamp && <span className="stamp">{stamp}</span>}
      {timecode && <span className="timecode">{timecode}</span>}
      <span className="play"><Icon name="play" size={28} /></span>
    </div>
  );
}

// ─── Style swatch ─────────────────────────────────────────────────────────
export function StyleSwatch({ id }) {
  const palettes = {
    anime:  ['#f8b4d9', '#5c5cff', '#1a0a40'],
    manhwa: ['#ffd6cc', '#ffa68a', '#8a4a3c'],
    manhua: ['#d4a574', '#7a3a1a', '#241008'],
    pixar:  ['#a8e6cf', '#5a9fd4', '#3a1f5c'],
    comic:  ['#ffe066', '#ff5a5a', '#1a1a1a'],
    noir:   ['#eaeaea', '#7a7a7a', '#0a0a0a'],
    custom: ['#1c1c22', '#2a2a32', '#1c1c22'],
  };
  const c = palettes[id] || palettes.custom;
  const glyph = { anime: 'JP', manhwa: 'KR', manhua: 'CN', pixar: '3D', comic: 'POW', noir: 'B&W', custom: '+' }[id];
  return (
    <div className="swatch" style={{ background: `linear-gradient(135deg, ${c[0]} 0%, ${c[1]} 50%, ${c[2]} 100%)` }}>
      <span className="glyph" style={{ color: id === 'noir' || id === 'comic' ? '#1a1a1a' : '#ffffffd9', mixBlendMode: 'overlay' }}>{glyph}</span>
    </div>
  );
}

// ─── Formatters ───────────────────────────────────────────────────────────
export const fmt = {
  dur: (s) => {
    if (s == null) return '—';
    const m = Math.floor(s / 60);
    const r = Math.floor(s % 60);
    return `${m}:${String(r).padStart(2, '0')}`;
  },
  shortTask: (id) => id ? id.slice(0, 8) + '…' + id.slice(-4) : '—',
  bytes: (mb) => `${mb.toFixed(1)} MB`,
};
