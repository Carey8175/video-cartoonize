import React, { useState } from 'react';
import { Icon, Btn, Tag, StyleSwatch } from './components';
import { STYLES, MODELS } from './data';

export function StageSetup({ state, setState }) {
  const [showKey, setShowKey] = useState(false);
  const [keyVal, setKeyVal] = useState(state.api_key || '');
  const [aksk, setAksk] = useState({ ak: '', sk: '' });
  const [showAk, setShowAk] = useState(false);
  const [showSk, setShowSk] = useState(false);
  const [styleId, setStyleId] = useState(state.config.style_id);
  const [modelId, setModelId] = useState(state.config.seedance_model_id || 'seedance-2-0');
  const [customEndpoint, setCustomEndpoint] = useState('https://your-server.com/v1');
  const [customRefs, setCustomRefs] = useState([]);

  function applyConfig() {
    setState((s) => ({
      ...s,
      api_key: keyVal,
      api_key_status: keyVal ? 'connected' : 'missing',
      config: {
        ...s.config,
        style_id: styleId,
        seedance_model_id: modelId,
        custom_endpoint: modelId === 'custom' ? customEndpoint : undefined,
      },
    }));
  }

  return (
    <div>
      {/* Credentials */}
      <div className="panel" style={{ marginBottom: 18 }}>
        <div className="panel-head">
          <Icon name="key" size={14} />
          <span className="title">Credentials</span>
          <span className="sub">— ARK API key + AK/SK</span>
          <span style={{ flex: 1 }} />
          <Tag tone={state.api_key_status === 'connected' ? 'ok' : 'warn'} dot>
            {state.api_key_status === 'connected' ? 'CONNECTED' : 'NOT SET'}
          </Tag>
        </div>
        <div className="panel-body">
          <div className="privacy-note">
            <Icon name="key" size={12} />
            <span>
              <strong>We don't store your credentials.</strong> Keys live in the browser for this session only;
              all calls go direct from your machine to ARK / TOS. Forget the tab to forget them.
            </span>
          </div>

          {/* ARK API key */}
          <div className="cred-group">
            <div className="cred-label">
              <span>ARK API Key</span>
              <span className="sub">— Seedream I2I · Seedance video · VLM</span>
            </div>
            <div className="api-row">
              <input
                className="input mono"
                type={showKey ? 'text' : 'password'}
                value={keyVal}
                onChange={(e) => setKeyVal(e.target.value)}
                placeholder="sk-…"
                spellCheck={false}
              />
              <Btn icon={showKey ? 'circle' : 'eye'} onClick={() => setShowKey((v) => !v)}>
                {showKey ? 'Hide' : 'Show'}
              </Btn>
              <Btn icon="check" onClick={applyConfig}>Verify</Btn>
            </div>
          </div>

          {/* TOS AK/SK */}
          <div className="cred-group" style={{ marginTop: 14 }}>
            <div className="cred-label">
              <span>Access Key / Secret Key</span>
              <span className="sub">— required for the assets library (input video + reference image uploads)</span>
            </div>
            <div className="api-row">
              <input
                className="input mono"
                type={showAk ? 'text' : 'password'}
                value={aksk.ak}
                onChange={(e) => setAksk((s) => ({ ...s, ak: e.target.value }))}
                placeholder="AKLT…"
                spellCheck={false}
              />
              <Btn icon={showAk ? 'circle' : 'eye'} onClick={() => setShowAk((v) => !v)}>
                {showAk ? 'Hide' : 'Show'} AK
              </Btn>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>Access Key</span>
            </div>
            <div className="api-row" style={{ marginTop: 6 }}>
              <input
                className="input mono"
                type={showSk ? 'text' : 'password'}
                value={aksk.sk}
                onChange={(e) => setAksk((s) => ({ ...s, sk: e.target.value }))}
                placeholder="—"
                spellCheck={false}
              />
              <Btn icon={showSk ? 'circle' : 'eye'} onClick={() => setShowSk((v) => !v)}>
                {showSk ? 'Hide' : 'Show'} SK
              </Btn>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>Secret Key</span>
            </div>
            <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
              The region and bucket for the assets library are configured by the backend and don't need to be entered here.
            </div>
          </div>
        </div>
      </div>

      {/* Style picker */}
      <div className="panel" style={{ marginBottom: 18 }}>
        <div className="panel-head">
          <Icon name="sparkle" size={14} />
          <span className="title">Cartoon style</span>
          <span className="sub">— Seedream I2I preset · pick one, or supply your own refs</span>
          <span style={{ flex: 1 }} />
          <Tag tone="accent" mono={false}>
            {styleId === 'custom' ? 'Custom Refs' : STYLES.find((s) => s.id === styleId)?.name || styleId}
          </Tag>
        </div>
        <div className="panel-body">
          <div className="style-grid">
            {STYLES.map((s) => (
              <div
                key={s.id}
                className={`style-card ${styleId === s.id ? 'selected' : ''}`}
                onClick={() => setStyleId(s.id)}
              >
                <StyleSwatch id={s.id} />
                <div className="title">
                  <span>{s.name}</span>
                </div>
                <div className="blurb">{s.blurb}</div>
              </div>
            ))}
          </div>

          {styleId === 'custom' && (
            <div style={{ marginTop: 14, padding: 14, background: 'var(--surface-1)', border: '1px dashed var(--border-strong)', borderRadius: 6 }}>
              <div className="label" style={{ marginBottom: 8 }}>Reference images · 1–4 files</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {[...customRefs, ...Array(Math.max(0, 4 - customRefs.length)).fill(null)].slice(0, 4).map((src, i) => (
                  <div key={i} style={{
                    width: 80, height: 80,
                    border: '1px dashed var(--border-strong)', borderRadius: 4,
                    background: src ? `url(${src}) center/cover` : 'var(--surface-2)',
                    display: 'grid', placeItems: 'center',
                    color: 'var(--muted)',
                  }}>
                    {!src && <Icon name="plus" size={16} />}
                  </div>
                ))}
                <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', marginLeft: 6 }}>
                  <Btn icon="upload" onClick={() => setCustomRefs(['assets/refs/character1_boy.jpg', 'assets/refs/character2_girl.jpg'])}>
                    Pick demo refs
                  </Btn>
                  <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--muted)', marginTop: 6 }}>
                    JPEG / PNG · ≤ 4 MB each
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Model picker */}
      <div className="panel">
        <div className="panel-head">
          <Icon name="cpu" size={14} />
          <span className="title">Seedance model</span>
          <span className="sub">— video generation backend</span>
        </div>
        <div className="panel-body">
          <div className="model-list">
            {MODELS.map((m) => (
              <div
                key={m.id}
                className={`model-card ${modelId === m.id ? 'selected' : ''}`}
                onClick={() => setModelId(m.id)}
              >
                <div className="radio" />
                <div>
                  <div className="name">
                    {m.name}
                    <span className="tier-pill">{m.tier}</span>
                  </div>
                  <div className="desc">{m.blurb}</div>
                </div>
                <div className="price">
                  {m.price_out ? (
                    <>
                      <div>{m.price_out}<small style={{ display: 'inline', marginLeft: 3, color: 'var(--muted)' }}>/ 1M video tokens</small></div>
                      <small>+ {m.price_in} / 1M input · ~{m.avg_s}s per clip</small>
                    </>
                  ) : (
                    <>
                      <div>self-hosted</div>
                      <small>BYO endpoint</small>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>

          {modelId === 'custom' && (
            <div style={{ marginTop: 12 }}>
              <label className="label">CUSTOM ENDPOINT</label>
              <input
                className="input mono"
                value={customEndpoint}
                onChange={(e) => setCustomEndpoint(e.target.value)}
                placeholder="https://your-server/v1"
              />
            </div>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
        <Btn icon="logs">View config diff</Btn>
        <Btn variant="primary" icon="arrow-right" onClick={applyConfig}>
          Save · proceed to source
        </Btn>
      </div>
    </div>
  );
}
