import React from 'react';
import { Icon, Btn, Tag, MetricRow, Thumb, statusTag, fmt } from './components';

export function Kv({ label, value, mono = false, mono_break = false, tone }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 12, fontSize: 12.5 }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em', paddingTop: 1 }}>{label}</div>
      <div style={{
        fontFamily: mono ? 'var(--font-mono)' : 'inherit',
        fontSize: mono ? 11.5 : 12.5,
        color: tone === 'ok' ? 'var(--success)' : 'var(--text)',
        wordBreak: mono_break ? 'break-all' : 'normal',
      }}>{value}</div>
    </div>
  );
}

export function StageSource({ state }) {
  const src = state.source;
  return (
    <div>
      <div className="source-grid">
        <div>
          <div className="player">
            <div className="center-play"><Icon name="play" size={20} /></div>
            <div className="filmstrip">
              {Array.from({ length: 12 }).map((_, i) => <div key={i} className="cell" />)}
            </div>
          </div>
          <div style={{ marginTop: 10, padding: '10px 14px', background: 'var(--surface-0)', border: '1px solid var(--border)', borderRadius: 6, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 10 }}>
            <Icon name="play" size={11} />
            <span>0:00</span>
            <div style={{ flex: 1, height: 4, background: 'var(--surface-2)', borderRadius: 2, position: 'relative' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '0%', background: 'var(--accent)', borderRadius: 2 }} />
              <div style={{ position: 'absolute', left: '0%', top: -4, width: 2, height: 12, background: 'var(--accent)' }} />
            </div>
            <span>{fmt.dur(src.duration_s)}</span>
          </div>
        </div>

        <div>
          <div className="panel">
            <div className="panel-head">
              <Icon name="film" size={14} />
              <span className="title">Source</span>
              <span style={{ flex: 1 }} />
              <Tag tone="ok" dot>Ready</Tag>
            </div>
            <div className="panel-body">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Kv label="File"       value={src.name} mono mono_break />
                <Kv label="Duration"   value={fmt.dur(src.duration_s)} />
                <Kv label="Size"       value={fmt.bytes(src.size_mb)} />
                <Kv label="Resolution" value={`${src.resolution} · ${src.fps}fps`} />
                <Kv label="Codec"      value={src.codec.toUpperCase()} />
                <Kv label="Work dir"   value={state.work_dir} mono />
              </div>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 14 }}>
            <div className="panel-head">
              <Icon name="settings" size={14} />
              <span className="title">Split config</span>
              <span className="sub">— scene threshold</span>
            </div>
            <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Kv label="Scene threshold"    value={state.config.scene_threshold} />
              <Kv label="Min clip"           value={`${state.config.min_clip_duration}s`} />
              <Kv label="Max clip"           value={`${state.config.max_clip_duration}s`} />
              <Kv label="Pixel limit"        value="927408" />
              <Kv label="Subshot threshold"  value={state.config.subshot_threshold} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function StageClips({ state, selectedClipId, setSelectedClipId }) {
  const clips = state.clips;
  const totalDur = clips.reduce((a, c) => a + c.duration_s, 0);
  const selected = clips.find((c) => c.clip_id === selectedClipId) || clips[0];
  const minW = 60;
  const widths = clips.map((c) => Math.max(minW, Math.round(c.duration_s * 18)));

  return (
    <div>
      <MetricRow items={[
        { k: 'Total clips', v: clips.length },
        { k: 'Avg duration', v: (totalDur / clips.length).toFixed(1), unit: 's' },
        { k: 'Sum duration', v: fmt.dur(totalDur) },
        { k: 'Detected ratios', v: '9:16 + 16:9' },
        { k: 'Detector', v: 'PySceneDetect', sub: 'threshold 25.0' },
      ]} />

      <div style={{ marginTop: 18 }}>
        <div className="timeline">
          <div className="ruler" style={{ width: widths.reduce((a, b) => a + b + 2, 32) + 'px' }}>
            {[0, 30, 60, 90, 120].map((t) => (
              <span key={t} className="tick" style={{ left: 16 + t * 18 + 'px' }}>
                <span className="label" style={{ position: 'absolute', bottom: 8, left: 0 }}>{fmt.dur(t)}</span>
              </span>
            ))}
          </div>
          <div className="track">
            {clips.map((c, i) => (
              <div
                key={c.clip_id}
                className={`timeline-clip ${selectedClipId === c.clip_id ? 'selected' : ''}`}
                style={{ width: widths[i] }}
                onClick={() => setSelectedClipId(c.clip_id)}
                title={`clip_${String(c.clip_id).padStart(2, '00')} · ${c.duration_s}s · ${c.status}`}
              >
                <div className={`status-stripe ${c.status}`} />
                <div className="stripe" />
                <div className="footer">
                  <span>{String(c.clip_id).padStart(2, '0')}</span>
                  <span>{c.duration_s.toFixed(1)}s</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {selected && <ClipDetailCard clip={selected} state={state} />}
    </div>
  );
}

function ClipDetailCard({ clip, state }) {
  const status = statusTag(clip.status);
  return (
    <div className="panel" style={{ marginTop: 18 }}>
      <div className="panel-head">
        <Icon name="film" size={14} />
        <span className="title">clip_{String(clip.clip_id).padStart(2, '0')}</span>
        <span className="sub">— {clip.duration_s.toFixed(2)}s · {clip.ratio} · {clip.width}×{clip.height}</span>
        <span style={{ flex: 1 }} />
        <Tag tone={status.tone} dot>{status.label}</Tag>
      </div>
      <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 18 }}>
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
            {clip.subshots.map((s, i) => (
              <Thumb
                key={i}
                src={null}
                stamp={`sub_${String(i).padStart(2, '0')}`}
                timecode={`${s.t_start}s→${s.t_end}s`}
              />
            ))}
          </div>
          <div style={{ marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
            <span style={{ color: 'var(--text-dim)' }}>{clip.n_subshots}</span> sub-shots detected ·
            threshold {state.config.subshot_threshold} ·
            raw: <code style={{ color: 'var(--text-dim)' }}>{clip.raw_path.split('/').pop()}</code>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Kv label="clip_id"  value={String(clip.clip_id).padStart(2, '0')} mono />
          <Kv label="ratio"    value={clip.ratio} mono />
          <Kv label="resized"  value={`${clip.width}×${clip.height}`} mono />
          <Kv label="duration" value={`${clip.duration_s.toFixed(2)}s`} mono />
          <Kv label="status"   value={clip.status} mono />
          <div style={{ marginTop: 12, display: 'flex', gap: 6 }}>
            <Btn icon="play">Preview</Btn>
            <Btn icon="logs">JSONL</Btn>
            <Btn icon="copy">Copy ID</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

export function StageKeyframes({ state, setState, selectedClipId, setSelectedClipId, openRegenModal }) {
  const clips = state.clips;
  const totalKf = clips.reduce((a, c) => a + c.n_subshots, 0);
  const cartoonized = clips.reduce((a, c) => a + c.subshots.filter((s) => s.cartoon).length, 0);
  const [filter, setFilter] = React.useState('all');
  const shown = filter === 'all' ? clips
    : filter === 'cartoon' ? clips.filter((c) => c.subshots.some((s) => s.cartoon))
    : clips.filter((c) => !c.subshots.some((s) => s.cartoon));

  return (
    <div>
      <MetricRow items={[
        { k: 'Total keyframes', v: totalKf },
        { k: 'Cartoonized', v: `${cartoonized}/${totalKf}`, sub: 'Seedream I2I' },
        { k: 'Avg / clip', v: (totalKf / clips.length).toFixed(2) },
        { k: 'Detector', v: 'ffmpeg-scene', sub: 'threshold 27.0' },
        { k: 'I2I model', v: 'seedream-5.0', sub: 'image_size: auto' },
      ]} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '18px 0 12px' }}>
        <div className="tasks-tabs" style={{ background: 'transparent', border: '1px solid var(--border)', borderRadius: 6, padding: 4 }}>
          {[
            { id: 'all', label: 'All', count: clips.length },
            { id: 'cartoon', label: 'Cartoonized', count: clips.filter((c) => c.subshots.some((s) => s.cartoon)).length },
            { id: 'pending', label: 'Pending', count: clips.filter((c) => !c.subshots.some((s) => s.cartoon)).length },
          ].map((t) => (
            <div key={t.id} className={`tab ${filter === t.id ? 'active' : ''}`} onClick={() => setFilter(t.id)}>
              {t.label} <span className="count">{t.count}</span>
            </div>
          ))}
        </div>
        <span style={{ flex: 1 }} />
        <Btn icon="refresh">Re-extract all</Btn>
        <Btn icon="sparkle">Cartoonize all keyframes</Btn>
      </div>

      {shown.slice(0, 6).map((c) => (
        <KfClipBlock key={c.clip_id} clip={c} openRegenModal={openRegenModal} />
      ))}
      {shown.length > 6 && (
        <div style={{ textAlign: 'center', padding: 18, fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--muted)' }}>
          … and {shown.length - 6} more clips · open the board to view all
        </div>
      )}
    </div>
  );
}

function KfClipBlock({ clip, openRegenModal }) {
  const hasCartoon = clip.subshots.some((s) => s.cartoon);
  return (
    <div className="kf-clip">
      <div className="kf-clip-head">
        <span className="id">clip_{String(clip.clip_id).padStart(2, '0')}</span>
        <span className="meta">{clip.duration_s.toFixed(2)}s · {clip.ratio}</span>
        <Tag tone="accent">{clip.n_subshots} keyframes</Tag>
        {hasCartoon ? <Tag tone="ok" dot>Cartoonized</Tag> : <Tag tone="idle">Pending I2I</Tag>}
        <span className="spacer" />
        <Btn icon="refresh">Re-extract</Btn>
        <Btn icon="sparkle">Cartoonize</Btn>
      </div>
      <div className="kf-pairs">
        {clip.subshots.map((s, i) => (
          <KfPair key={i} clip={clip} s={s} idx={i} openRegenModal={openRegenModal} />
        ))}
      </div>
    </div>
  );
}

function KfPair({ clip, s, idx, openRegenModal }) {
  return (
    <div className="kf-pair">
      <div className="kf-pair-tile orig">
        <img src={s.keyframe} alt="" style={{ filter: 'saturate(0.55) brightness(0.92) contrast(1.05)' }} />
        <span className="lbl">Original</span>
        <span className="time">{s.t_start.toFixed(1)}s</span>
      </div>
      <div className="kf-pair-arrow">
        <Icon name="arrow-right" size={14} />
      </div>
      <div className="kf-pair-tile cart">
        {s.cartoon
          ? <img src={s.cartoon} alt="" />
          : (
            <div className="kf-pair-empty">
              <Icon name="sparkle" size={18} />
              <span>Pending I2I</span>
            </div>
          )}
        <span className="lbl">Cartoon</span>
        <span className="kf-pair-actions">
          <button className="kf-pair-btn" title="Regenerate" onClick={() => openRegenModal({ clip, frame: s, frameIdx: idx })}>
            <Icon name="refresh" size={11} />
          </button>
          <button className="kf-pair-btn" title="Edit prompt" onClick={() => openRegenModal({ clip, frame: s, frameIdx: idx })}>
            <Icon name="edit" size={11} />
          </button>
        </span>
      </div>
      <div className="kf-pair-meta">
        <span className="kf-pair-id">sub_{String(idx).padStart(2, '0')}</span>
        <span>{s.t_start.toFixed(1)}s – {s.t_end.toFixed(1)}s</span>
      </div>
    </div>
  );
}
