import React, { useState, useEffect } from 'react';
import { Icon, Btn, Tag, fmt } from './components';
import { STYLES } from './data';

// ─── Progress ring ─────────────────────────────────────────────────────────
export function ProgressRing({ percent, size = 86, stroke = 7 }) {
  const r = (size - stroke) / 2;
  const C = 2 * Math.PI * r;
  const off = C - (percent / 100) * C;
  return (
    <svg width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r}
        stroke="var(--surface-3)" strokeWidth={stroke} fill="none" />
      <circle cx={size / 2} cy={size / 2} r={r}
        stroke="var(--accent)" strokeWidth={stroke} fill="none"
        strokeDasharray={C} strokeDashoffset={off}
        strokeLinecap="round"
        style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%', transition: 'stroke-dashoffset 0.5s ease' }} />
    </svg>
  );
}

// ─── Task Panel (right rail) ───────────────────────────────────────────────
export function TaskPanel({ state, setState, onTaskClick, onOpenHistory }) {
  const c = state.clips;
  const splitDone = c.length;
  const keyframesDone = c.filter((x) => x.subshots.length > 0).length;
  const cartoonDone = c.filter((x) => x.subshots.every((s) => s.cartoon)).length;
  const submittedDone = c.filter((x) => x.task_id).length;
  const renderDone = c.filter((x) => x.status === 'done').length;
  const merged = state.merged ? 1 : 0;
  const inFlight = c.filter((x) => x.task_status === 'running' || x.task_status === 'queued');

  const weights = { split: 5, keyframes: 10, cartoon: 25, submit: 10, render: 45, merge: 5 };
  const overall = Math.round(
    (splitDone / c.length) * weights.split +
    (keyframesDone / c.length) * weights.keyframes +
    (cartoonDone / c.length) * weights.cartoon +
    (submittedDone / c.length) * weights.submit +
    (renderDone / c.length) * weights.render +
    merged * weights.merge
  );

  const elapsed = '00:24:12';
  const eta = renderDone === c.length ? '—' : '~00:18:30';
  const tokensOut = renderDone * 92000 + inFlight.length * 35000;
  const tokensIn = cartoonDone * 4500;
  const tokensStr = tokensOut > 1e6 ? `${(tokensOut / 1e6).toFixed(2)}M` : `${Math.round(tokensOut / 1000)}k`;

  // Simulate progress on running clips
  useEffect(() => {
    const id = setInterval(() => {
      setState((s) => ({
        ...s,
        clips: s.clips.map((cl) => {
          if (cl.task_status !== 'running') return cl;
          const p = Math.min(100, cl.task_progress + 1.5 + Math.random() * 2);
          return { ...cl, task_progress: p, updated_at: Math.floor(Date.now() / 1000) };
        }),
      }));
    }, 1800);
    return () => clearInterval(id);
  }, []);

  const stages = [
    { id: 'split',     label: 'Split',       done: splitDone,     total: c.length },
    { id: 'keyframes', label: 'Keyframes',   done: keyframesDone, total: c.length },
    { id: 'cartoon',   label: 'Cartoon I2I', done: cartoonDone,   total: c.length },
    { id: 'submit',    label: 'Submit',      done: submittedDone, total: c.length },
    { id: 'render',    label: 'Seedance',    done: renderDone,    total: c.length, runners: inFlight.length },
    { id: 'merge',     label: 'Mux & merge', done: merged,        total: 1 },
  ];

  const taskId = `task-202605142035-${state.project}`;

  return (
    <div className="tasks">
      <div className="tasks-head">
        <Icon name="cpu" size={14} />
        <div style={{ minWidth: 0 }}>
          <h3>This task</h3>
          <div className="sub" title={taskId} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {taskId}
          </div>
        </div>
        <span className="spacer" />
        <Btn icon="history" onClick={onOpenHistory} title="Open task history">History</Btn>
      </div>

      <div className="ct-body">
        {/* Overall progress ring */}
        <div className="ct-overall">
          <div className="ct-ring">
            <ProgressRing percent={overall} />
          </div>
          <div className="ct-overall-info">
            <div className="ct-stage">
              {overall === 100 ? 'Done' : renderDone < c.length ? 'Rendering' : 'In progress'}
            </div>
            <div className="ct-headline">{overall}<span style={{ fontSize: 14, color: 'var(--muted)' }}>%</span></div>
            <div className="ct-row"><span>elapsed</span><code>{elapsed}</code></div>
            <div className="ct-row"><span>eta</span><code>{eta}</code></div>
            <div className="ct-row">
              <span>tokens</span>
              <code title={`${tokensIn.toLocaleString()} in · ${tokensOut.toLocaleString()} out`}>{tokensStr}</code>
            </div>
          </div>
        </div>

        {/* Source meta */}
        <div className="ct-source">
          <div className="ct-source-row">
            <Icon name="film" size={11} />
            <span className="ct-source-name" title={state.source.name}>{state.source.name}</span>
          </div>
          <div className="ct-source-meta">
            <span>{fmt.dur(state.source.duration_s)}</span>
            <span>·</span>
            <span>{state.source.resolution}</span>
            <span>·</span>
            <span>{state.source.fps}fps</span>
            <span>·</span>
            <span>{fmt.bytes(state.source.size_mb)}</span>
          </div>
          <div className="ct-source-meta">
            <span style={{ color: 'var(--accent)' }}>
              <Icon name="sparkle" size={10} /> {STYLES.find((s) => s.id === state.config.style_id)?.name}
            </span>
            <span>·</span>
            <span>Seedance 2.0 Pro</span>
          </div>
        </div>

        {/* Stage progress bars */}
        <div className="ct-stages">
          {stages.map((s) => {
            const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
            const isActive = s.done > 0 && s.done < s.total;
            const isDone = s.done === s.total;
            return (
              <div key={s.id} className="ct-stage-row">
                <div className="ct-stage-name">
                  {isDone && <Icon name="check" size={11} className="dn" />}
                  {isActive && <span className="run-dot" />}
                  {!isDone && !isActive && <span className="idle-dot" />}
                  <span>{s.label}</span>
                </div>
                <div className="ct-stage-bar">
                  <span style={{ width: `${pct}%`, background: isDone ? 'var(--success)' : isActive ? 'var(--info)' : 'var(--muted-dim)' }} />
                </div>
                <div className="ct-stage-count">{s.done}<span style={{ color: 'var(--muted-dim)' }}>/{s.total}</span></div>
              </div>
            );
          })}
        </div>

        {/* In-flight sub-tasks */}
        {inFlight.length > 0 && (
          <>
            <div className="ct-subhead">
              <span>In flight</span>
              <span style={{ color: 'var(--muted)' }}>· seedance sub-tasks</span>
            </div>
            <div className="ct-subtasks">
              {inFlight.slice(0, 6).map((cl) => (
                <div key={cl.clip_id} className="ct-subtask" onClick={() => onTaskClick(cl.clip_id)}>
                  <span className="ct-sub-id">clip_{String(cl.clip_id).padStart(2, '0')}</span>
                  <div className="ct-sub-bar">
                    <span style={{ width: `${cl.task_progress}%` }} />
                  </div>
                  <span className="ct-sub-pct">{Math.round(cl.task_progress)}%</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="tasks-foot">
        <span className="led" />
        <span>Live · polling every 45s</span>
      </div>
    </div>
  );
}

// ─── Clip Board (bottom drawer) ────────────────────────────────────────────
export function ClipBoard({ state, setState, open, setOpen, onClipClick, onMerge }) {
  const clips = state.clips;
  const allDone = clips.every((c) => c.status === 'done');

  function pip(active, tone) {
    return <span className={`pip ${active ? tone || 'on' : 'miss'}`} />;
  }

  return (
    <div className={`board-overlay ${open ? 'open' : ''}`}>
      <div className="board-handle" onClick={() => setOpen((o) => !o)}>
        <span className="grip" />
        <span className="title">Clip board</span>
        <span className="meta">— {clips.length} clips · {clips.filter((c) => c.status === 'done').length} ready · {clips.filter((c) => c.status === 'polling').length} in flight</span>
        <span className="spacer" />
        <Btn variant="primary" icon="merge" onClick={(e) => { e.stopPropagation(); onMerge(); }} disabled={!allDone}>
          Mux & merge {allDone ? `(${clips.length})` : '(pending)'}
        </Btn>
        <Btn icon={open ? 'chevron-down' : 'chevron-right'} />
      </div>
      <div className="board-body">
        <div className="board-grid">
          <div className="h">ID</div>
          <div className="h">Clip</div>
          <div className="h">Stages</div>
          <div className="h">VLM</div>
          <div className="h">Task</div>
          <div className="h">Status</div>
          <div className="h" style={{ textAlign: 'right' }}>Actions</div>

          {clips.map((c) => {
            const hasCartoon = c.subshots.some((s) => s.cartoon);
            const stages = ['split', 'keyframes', 'cartoon_ready', 'polling', 'done'];
            const reachedIdx = stages.indexOf(c.status);
            const vlmPass = c.subshots.filter((s) => s.vlm_pass === true).length;
            const vlmTot = c.subshots.filter((s) => s.vlm_pass !== null).length;
            const { tone, label } = statusTagLocal(c.status);
            return (
              <div key={c.clip_id} className="r board-row" style={{ display: 'contents' }}>
                <div className="c id">{String(c.clip_id).padStart(2, '0')}</div>
                <div className="c">
                  <div style={{ width: 48, height: 28, background: hasCartoon ? `url(${c.subshots[0].cartoon}) center/cover` : 'var(--surface-3)', borderRadius: 3, marginRight: 8, border: '1px solid var(--border)' }} />
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    <div>{c.duration_s.toFixed(1)}s</div>
                    <div style={{ color: 'var(--muted)', fontSize: 10 }}>{c.ratio}</div>
                  </div>
                </div>
                <div className="c">
                  {pip(reachedIdx >= 0)}
                  {pip(reachedIdx >= 1, c.status === 'keyframes' ? 'on' : reachedIdx > 1 ? 'on' : null)}
                  {pip(reachedIdx >= 2, c.status === 'cartoon_ready' ? 'warn' : reachedIdx > 2 ? 'on' : null)}
                  {pip(reachedIdx >= 3, c.status === 'polling' ? 'run' : reachedIdx > 3 ? 'on' : null)}
                  {pip(reachedIdx >= 4, 'on')}
                </div>
                <div className="c" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
                  {vlmTot ? `${vlmPass}/${vlmTot}` : '—'}
                </div>
                <div className="c" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
                  {c.task_id ? fmt.shortTask(c.task_id) : '—'}
                </div>
                <div className="c"><Tag tone={tone} dot>{label}</Tag></div>
                <div className="c" style={{ justifyContent: 'flex-end', gap: 4 }}>
                  <Btn icon="eye" onClick={() => onClipClick(c.clip_id)}>Open</Btn>
                  <Btn icon="refresh" title="Resubmit" />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function statusTagLocal(status) {
  const map = {
    done: { tone: 'ok', label: 'Done' },
    polling: { tone: 'run', label: 'Polling' },
    cartoon_ready: { tone: 'warn', label: 'Cartoon ready' },
    keyframes: { tone: 'accent', label: 'Keyframes' },
    split: { tone: 'idle', label: 'Split' },
  };
  return map[status] || { tone: 'idle', label: status };
}

// ─── Regen modal ──────────────────────────────────────────────────────────
export function RegenModal({ ctx, onClose, setState }) {
  const [prompt, setPrompt] = useState(
    'Convert the scene into Japanese anime illustration style. Bold clean outlines, cel-shaded coloring…'
  );
  const [scope, setScope] = useState(ctx?.scope || 'frame');
  const [strength, setStrength] = useState(0.75);

  if (!ctx) return null;
  const { clip, frame, frameIdx } = ctx;

  function submit() {
    setState((s) => ({
      ...s,
      clips: s.clips.map((c) => {
        if (c.clip_id !== clip.clip_id) return c;
        if (scope === 'whole-clip') {
          return {
            ...c,
            task_status: 'queued', status: 'polling', task_progress: 5,
            retries: (c.retries || 0) + 1,
            attempts: [
              { task_id: c.task_id, verdict: 'fail', reason: 'Manual regen', output_url: '' },
              ...(c.attempts || []),
            ],
            task_id: `cgt-${Date.now().toString().slice(-8)}-regen`,
          };
        }
        return {
          ...c,
          subshots: c.subshots.map((s, i) =>
            i === frameIdx ? { ...s, vlm_pass: null, vlm_score: null, vlm_reason: '' } : s
          ),
        };
      }),
    }));
    onClose();
  }

  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <Icon name="refresh" size={14} />
          <div>
            <div className="title">Regenerate {scope === 'whole-clip' ? 'cartoonized clip' : 'frame'}</div>
            <div className="sub">clip_{String(clip.clip_id).padStart(2, '0')} {frameIdx != null && `· sub_${String(frameIdx).padStart(2, '0')}`}</div>
          </div>
          <span className="spacer" />
          <Btn icon="x" onClick={onClose} />
        </div>
        <div className="modal-body">
          <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
            {['frame', 'whole-clip'].map((s) => (
              <button key={s} className="btn" onClick={() => setScope(s)} style={{
                background: scope === s ? 'var(--accent-soft)' : null,
                color: scope === s ? 'var(--accent)' : null,
                borderColor: scope === s ? 'var(--accent-line)' : null,
              }}>
                <Icon name={s === 'frame' ? 'image' : 'video'} size={12} />
                {s === 'frame' ? 'Just this frame' : 'Re-render whole clip'}
              </button>
            ))}
          </div>

          {scope === 'frame' && frame && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
              <div style={{ position: 'relative', aspectRatio: '9/16', maxHeight: 220, borderRadius: 5, overflow: 'hidden', border: '1px solid var(--border)' }}>
                <img src={frame.keyframe} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', filter: 'saturate(0.55)' }} />
                <span style={{ position: 'absolute', bottom: 4, left: 4, fontFamily: 'var(--font-mono)', fontSize: 10, background: 'rgba(0,0,0,0.7)', padding: '2px 5px', borderRadius: 3 }}>SOURCE</span>
              </div>
              <div style={{ position: 'relative', aspectRatio: '9/16', maxHeight: 220, borderRadius: 5, overflow: 'hidden', border: '1px solid var(--border)' }}>
                <img src={frame.cartoon} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                <span style={{ position: 'absolute', bottom: 4, left: 4, fontFamily: 'var(--font-mono)', fontSize: 10, background: 'rgba(0,0,0,0.7)', padding: '2px 5px', borderRadius: 3 }}>CURRENT</span>
              </div>
            </div>
          )}

          <label className="label">Prompt (Seedream I2I)</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className="input mono"
            rows={5}
            style={{ resize: 'vertical', lineHeight: 1.55 }}
          />

          {frame?.vlm_reason && (
            <div style={{ marginTop: 10, padding: 10, background: 'var(--danger-soft)', border: '1px solid rgba(248,113,113,0.22)', borderRadius: 5, fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-dim)' }}>
              <strong style={{ color: 'var(--danger)' }}>VLM verdict: </strong>{frame.vlm_reason}
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
            <div>
              <label className="label">Style strength · {strength.toFixed(2)}</label>
              <input type="range" min="0.3" max="1.0" step="0.05" value={strength}
                onChange={(e) => setStrength(+e.target.value)}
                style={{ width: '100%' }} />
            </div>
            <div>
              <label className="label">Seed</label>
              <input className="input mono" defaultValue="0x7f3a1c" />
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <span style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
            ~{scope === 'whole-clip' ? '3m 10s' : '14s'} estimated · ~{scope === 'whole-clip' ? '180k' : '12k'} video tokens
          </span>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn variant="primary" icon="refresh" onClick={submit}>Submit regen</Btn>
        </div>
      </div>
    </div>
  );
}
