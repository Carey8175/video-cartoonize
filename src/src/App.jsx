import React, { useState, useEffect, useMemo } from 'react';
import { Icon, statusTag, fmt } from './components';
import { INITIAL_STATE, STYLES } from './data';
import { StageSetup } from './StageSetup';
import { StageSource, StageClips, StageKeyframes } from './StageSource';
import { StageCartoonized, StageMerge } from './StageCartoonMerge';
import { TaskPanel, ClipBoard, RegenModal } from './TasksBoard';

const STAGES = [
  { id: 'setup',       step: '01', name: 'Setup',           meta: 'API · style · model',    icon: 'key',    section: 'Config' },
  { id: 'source',      step: '02', name: 'Source',          meta: 'video.mp4',               icon: 'film',   section: 'Pipeline' },
  { id: 'clips',       step: '03', name: 'Clips',           meta: 'split',                   icon: 'film',   section: 'Pipeline' },
  { id: 'keyframes',   step: '04', name: 'Keyframes',       meta: 'extract + I2I',           icon: 'image',  section: 'Pipeline' },
  { id: 'cartoonized', step: '05', name: 'Cartoonized clip', meta: 'Seedance · video',       icon: 'video',  section: 'Pipeline' },
  { id: 'merge',       step: '06', name: 'Mux & merge',     meta: 'ffmpeg · final',          icon: 'merge',  section: 'Pipeline' },
];

function hexA(hex, a) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substr(0, 2), 16);
  const g = parseInt(h.substr(2, 2), 16);
  const b = parseInt(h.substr(4, 2), 16);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

export default function App() {
  const [state, setState] = useState(() => ({
    ...INITIAL_STATE,
    api_key: 'sk-ark-9f3a2c1e44b780be9a1c3d',
    api_key_status: 'connected',
    config: { ...INITIAL_STATE.config, seedance_model_id: 'seedance-2-0' },
  }));

  const [stageId, setStageId] = useState('clips');
  const [selectedClipId, setSelectedClipId] = useState(0);
  const [boardOpen, setBoardOpen] = useState(false);
  const [regenCtx, setRegenCtx] = useState(null);
  const [accent] = useState('#f97316');

  useEffect(() => {
    document.documentElement.style.setProperty('--accent', accent);
    document.documentElement.style.setProperty('--accent-soft', hexA(accent, 0.14));
    document.documentElement.style.setProperty('--accent-line', hexA(accent, 0.35));
  }, [accent]);

  const stageStatus = useMemo(() => {
    const c = state.clips;
    return {
      setup: state.api_key_status === 'connected' ? 'done' : 'partial',
      source: 'done',
      clips: 'done',
      keyframes: c.filter((x) => x.subshots.every((s) => s.cartoon)).length === c.length ? 'done'
        : c.some((x) => x.subshots.some((s) => s.cartoon)) ? 'partial' : 'running',
      cartoonized: c.every((x) => x.status === 'done') ? 'done'
        : c.some((x) => x.status === 'polling') ? 'running' : 'partial',
      merge: state.merged ? 'done' : 'pending',
    };
  }, [state]);

  function jumpToClip(clipId) {
    setSelectedClipId(clipId);
    const c = state.clips.find((x) => x.clip_id === clipId);
    if (!c) return;
    if (c.status === 'done' || c.status === 'polling') setStageId('cartoonized');
    else if (c.status === 'cartoon_ready' || c.status === 'keyframes') setStageId('keyframes');
    else setStageId('clips');
  }

  function runMerge() {
    setStageId('merge');
    setTimeout(() => setState((s) => ({ ...s, merged: true })), 1500);
  }

  return (
    <div className="app">
      <TopBar state={state} setState={setState} />
      <div className="shell">
        <Rail stageId={stageId} setStageId={setStageId} state={state} stageStatus={stageStatus} />
        <Main
          stageId={stageId}
          state={state}
          setState={setState}
          selectedClipId={selectedClipId}
          setSelectedClipId={setSelectedClipId}
          openRegenModal={(ctx) => setRegenCtx(ctx)}
          runMerge={runMerge}
        />
        <TaskPanel
          state={state}
          setState={setState}
          onTaskClick={jumpToClip}
          onOpenHistory={() => {}}
        />
      </div>

      <ClipBoard
        state={state}
        setState={setState}
        open={boardOpen}
        setOpen={setBoardOpen}
        onClipClick={jumpToClip}
        onMerge={runMerge}
      />

      {regenCtx && (
        <RegenModal ctx={regenCtx} onClose={() => setRegenCtx(null)} setState={setState} />
      )}
    </div>
  );
}

// ─── Top bar ─────────────────────────────────────────────────────────────
function TopBar({ state }) {
  const inFlight = state.clips.filter((c) => c.task_status === 'running' || c.task_status === 'queued').length;
  return (
    <div className="topbar">
      <div className="brand">
        <span className="brand-mark">C</span>
        <span className="brand-name">cartoonize<span className="dim">/console</span></span>
      </div>
      <div className="crumb">
        <span>~/cartoonize</span>
        <span className="sep">/</span>
        <span className="active">{state.project}</span>
      </div>
      <div className="spacer" />

      <span className="tb-chip" title={state.api_key ? `Key: ${state.api_key.slice(0, 8)}…` : 'No API key'}>
        <span className={`dot ${state.api_key_status === 'connected' ? '' : 'warn'}`} />
        <span>ARK · connected</span>
      </span>

      <span className="tb-chip">
        <Icon name="cpu" size={12} />
        <span>Seedance 2.0 Pro</span>
        <Icon name="chevron-down" size={11} />
      </span>

      <span className="tb-chip">
        <Icon name="sparkle" size={12} />
        <span>{STYLES.find((s) => s.id === state.config.style_id)?.name || state.config.style_id}</span>
      </span>

      <span className="tb-chip" title="All tasks (queryable by API key)">
        <Icon name="history" size={12} />
        <span>Tasks</span>
        <kbd>{inFlight}</kbd>
      </span>

      <button className="tb-iconbtn" title="Settings"><Icon name="settings" size={14} /></button>
    </div>
  );
}

// ─── Left rail ───────────────────────────────────────────────────────────
function Rail({ stageId, setStageId, state, stageStatus }) {
  const sections = [...new Set(STAGES.map((s) => s.section))];
  const clipsDone = state.clips.filter((c) => c.status === 'done').length;

  return (
    <div className="rail">
      {sections.map((sec) => (
        <React.Fragment key={sec}>
          <div className="group-title">
            <span>{sec}</span>
            <span className="count">{sec === 'Pipeline' ? `${clipsDone}/${state.clips.length}` : ''}</span>
          </div>
          {STAGES.filter((s) => s.section === sec).map((s) => {
            const status = stageStatus[s.id];
            return (
              <div
                key={s.id}
                className={`stage-row ${stageId === s.id ? 'active' : ''}`}
                onClick={() => setStageId(s.id)}
              >
                <span className="step-id">{s.step}</span>
                <div>
                  <div className="step-name">{s.name}</div>
                  <div className="step-meta">{s.meta}</div>
                </div>
                <span className={`step-status ${status === 'pending' ? '' : status}`} title={status} />
              </div>
            );
          })}
        </React.Fragment>
      ))}

      <div className="footer">
        <div className="row"><span>state.json</span><span>v4</span></div>
        <div className="row"><span>schema</span><span>{state.version}</span></div>
        <div className="row"><span>region</span><span>ap-se-1</span></div>
        <div className="row" style={{ marginTop: 8, color: 'var(--success)' }}>
          <span>⏵ alive</span>
          <span>{Math.floor(Date.now() / 1000).toString().slice(-6)}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Main column ─────────────────────────────────────────────────────────
function Main({ stageId, state, setState, selectedClipId, setSelectedClipId, openRegenModal, runMerge }) {
  const stage = STAGES.find((s) => s.id === stageId);
  const heads = {
    setup:       { h1: 'Setup',             sub: 'Provide credentials, pick a style, choose a Seedance model.' },
    source:      { h1: 'Source video',      sub: 'Original input file · resized + analysed before splitting.' },
    clips:       { h1: 'Clips (scene-split)', sub: 'PySceneDetect · threshold-driven splits + sub-shot detection.' },
    keyframes:   { h1: 'Keyframes',         sub: 'One frame per sub-shot · cartoonized via Seedream I2I.' },
    cartoonized: { h1: 'Cartoonized clips', sub: 'Seedance generates the full clip from cartoon keyframes.' },
    merge:       { h1: 'Mux & merge',       sub: 'Concat the cartoonized clips and mux original audio.' },
  };
  const head = heads[stageId];

  return (
    <div className="main">
      <div className="main-head">
        <span className="step-tag">STEP {stage.step}</span>
        <div>
          <h1>{head.h1}</h1>
          <div className="sub">{head.sub}</div>
        </div>
        <span className="spacer" />
      </div>
      <div className="main-body">
        {stageId === 'setup' && <StageSetup state={state} setState={setState} />}
        {stageId === 'source' && <StageSource state={state} />}
        {stageId === 'clips' && (
          <StageClips state={state} selectedClipId={selectedClipId} setSelectedClipId={setSelectedClipId} />
        )}
        {stageId === 'keyframes' && (
          <StageKeyframes
            state={state} setState={setState}
            selectedClipId={selectedClipId} setSelectedClipId={setSelectedClipId}
            openRegenModal={openRegenModal}
          />
        )}
        {stageId === 'cartoonized' && (
          <StageCartoonized state={state} openRegenModal={openRegenModal} />
        )}
        {stageId === 'merge' && <StageMerge state={state} setState={setState} />}
      </div>
    </div>
  );
}
