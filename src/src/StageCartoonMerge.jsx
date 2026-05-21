import React, { useState } from 'react';
import { Icon, Btn, Tag, MetricRow, statusTag, fmt } from './components';
import { Kv } from './StageSource';
import { STYLES } from './data';

export function StageCartoonized({ state, openRegenModal }) {
  const clips = state.clips;
  const ready = clips.filter((c) => c.status === 'done').length;
  const running = clips.filter((c) => c.status === 'polling').length;
  const totalDur = clips.reduce((a, c) => a + c.duration_s, 0);

  return (
    <div>
      <MetricRow items={[
        { k: 'Rendered clips', v: `${ready}/${clips.length}` },
        { k: 'In flight', v: running, sub: 'seedance tasks' },
        { k: 'Output duration', v: fmt.dur(totalDur) },
        { k: 'Avg gen time', v: '3:08', sub: 'queue + render' },
      ]} />

      <div style={{ marginTop: 18 }} className="cartoonized-grid">
        {clips.map((c) => (
          <CartoonizedCard key={c.clip_id} clip={c} openRegenModal={openRegenModal} />
        ))}
      </div>
    </div>
  );
}

function CartoonizedCard({ clip, openRegenModal }) {
  const status = statusTag(clip.status);
  const preview = clip.subshots[0]?.cartoon;
  return (
    <div className="cartoonized-card">
      <div className="preview">
        {clip.status === 'done' || clip.status === 'cartoon_ready' ? (
          <>
            <img src={preview} alt="" />
            <div className="overlay-play"><Icon name="play" size={22} /></div>
          </>
        ) : clip.status === 'polling' ? (
          <div className="ph" style={{ textAlign: 'center' }}>
            <div style={{ width: 28, height: 28, border: '2px solid var(--border-strong)', borderTopColor: 'var(--info)', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 8px' }} />
            rendering<br />{Math.round(clip.task_progress)}%
          </div>
        ) : (
          <div className="ph">— not submitted —</div>
        )}
      </div>
      <div className="body">
        <div className="title">clip_{String(clip.clip_id).padStart(2, '0')}.mp4</div>
        <div className="row">
          <span>{clip.duration_s.toFixed(1)}s · {clip.ratio}</span>
          <Tag tone={status.tone} dot>{status.label}</Tag>
        </div>
        {clip.task_id && (
          <div className="row" style={{ marginTop: 4 }}>
            <code style={{ fontSize: 10.5 }}>{fmt.shortTask(clip.task_id)}</code>
            {clip.retries > 0 && <span title={`${clip.retries} retries`}>↻×{clip.retries}</span>}
          </div>
        )}
      </div>
      <div className="actions">
        <Btn icon="play">Preview</Btn>
        <Btn icon="refresh" onClick={() => openRegenModal({ clip, scope: 'whole-clip' })}>Regen</Btn>
        <span style={{ flex: 1 }} />
        <Btn icon="history" title="Attempts history" />
      </div>
    </div>
  );
}

export function StageMerge({ state, setState }) {
  const clips = state.clips;
  const doneAll = clips.every((c) => c.status === 'done');
  const totalDur = clips.reduce((a, c) => a + c.duration_s, 0);
  const [merging, setMerging] = useState(false);
  const [merged, setMerged] = useState(state.merged || false);

  function runMerge() {
    setMerging(true);
    setTimeout(() => {
      setMerging(false);
      setMerged(true);
      setState((s) => ({ ...s, merged: true }));
    }, 2400);
  }

  return (
    <div>
      <MetricRow items={[
        { k: 'Clips ready', v: `${clips.filter((c) => c.status === 'done').length}/${clips.length}` },
        { k: 'Output duration', v: fmt.dur(totalDur) },
        { k: 'Tracks', v: 'V + A', sub: 'mux original audio' },
        { k: 'Container', v: 'MP4 H.264 + AAC' },
      ]} />

      <div className="mux-timeline" style={{ marginTop: 18 }}>
        <Track name="V1 · Cartoonized video" clips={clips} kind="cartoon" />
        <Track name="V2 · Original (reference)" clips={clips} kind="video" />
        <Track name="A1 · Original audio" clips={clips} kind="audio" />

        <div style={{ marginTop: 18, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
          <div><span style={{ display: 'inline-block', width: 10, height: 10, background: 'linear-gradient(135deg, #2a1f3a, #5a2a6a)', marginRight: 5, verticalAlign: 'middle', borderRadius: 2 }} /> Cartoon clip (Seedance output)</div>
          <div><span style={{ display: 'inline-block', width: 10, height: 10, background: 'linear-gradient(135deg, #3a2418, #5a3a26)', marginRight: 5, verticalAlign: 'middle', borderRadius: 2 }} /> Original (downscaled, kept for reference)</div>
          <div><span style={{ display: 'inline-block', width: 10, height: 10, background: 'linear-gradient(180deg, transparent, var(--info-soft), transparent)', marginRight: 5, verticalAlign: 'middle', borderRadius: 2 }} /> Audio (passthrough)</div>
        </div>
      </div>

      <div className="merge-cta">
        <div className="info">
          <h4>Mux & merge final video</h4>
          <p>ffmpeg concat · re-encode AAC · keep original audio · output → <code>final/merged.mp4</code></p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn icon="logs">Preview ffmpeg cmd</Btn>
          <button className="btn-merge" onClick={runMerge} disabled={merging || !doneAll}>
            {merging ? (
              <><span style={{ width: 12, height: 12, border: '2px solid #1a0a02', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} /> Merging…</>
            ) : merged ? (
              <><Icon name="check" size={13} /> Re-merge</>
            ) : (
              <><Icon name="merge" size={13} /> Mux & merge ({clips.length} clips)</>
            )}
          </button>
        </div>
      </div>

      {merged && (
        <div className="panel" style={{ marginTop: 14 }}>
          <div className="panel-head">
            <Icon name="video" size={14} />
            <span className="title">Final output</span>
            <span className="sub">— final/merged.mp4</span>
            <span style={{ flex: 1 }} />
            <Tag tone="ok" dot>Ready</Tag>
          </div>
          <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 18 }}>
            <div style={{ aspectRatio: '16/9', background: '#000', borderRadius: 6, display: 'grid', placeItems: 'center', border: '1px solid var(--border)' }}>
              <Icon name="play" size={36} />
            </div>
            <div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Kv label="Duration"   value={fmt.dur(totalDur)} mono />
                <Kv label="Resolution" value="1280×720 → 720p" mono />
                <Kv label="Size (est.)" value="68.4 MB" mono />
                <Kv label="Path"       value={`${state.work_dir}/final/merged.mp4`} mono mono_break />
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                <Btn variant="primary" icon="download">Download merged.mp4</Btn>
                <Btn icon="play">Open preview</Btn>
                <Btn icon="copy">Copy path</Btn>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Track({ name, clips, kind }) {
  const totalDur = clips.reduce((a, c) => a + c.duration_s, 0);
  return (
    <div className="mux-track">
      <div className="name">
        <span>{name}</span>
        <span>{clips.length} clips · {fmt.dur(totalDur)}</span>
      </div>
      <div className="strip">
        {clips.map((c) => (
          <div
            key={c.clip_id}
            className={`block ${kind}`}
            style={{ flexGrow: c.duration_s }}
            title={`clip_${String(c.clip_id).padStart(2, '0')} · ${c.duration_s.toFixed(2)}s`}
          />
        ))}
      </div>
    </div>
  );
}
