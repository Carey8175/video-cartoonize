// Mock state shaped after the real state.json schema (v4).
// All names + IDs mimic the actual pipeline.

const CARTOON_THUMBS = [
  'assets/cartoons/clip_00_sub_00.jpg',
  'assets/cartoons/clip_00_sub_01.jpg',
  'assets/cartoons/clip_00_sub_02.jpg',
  'assets/cartoons/clip_05_sub_00.jpg',
  'assets/cartoons/clip_05_sub_01.jpg',
  'assets/cartoons/clip_12_sub_00.jpg',
  'assets/cartoons/clip_12_sub_01.jpg',
];

function rng(seed) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

export const STYLE_OPTIONS = [
  { id: 'anime',  name: 'Japanese Anime',  blurb: 'Bold outlines · large eyes · cel-shaded' },
  { id: 'manhwa', name: 'Korean Manhwa',   blurb: 'Gradient cel · refined features · soft bokeh' },
  { id: 'manhua', name: 'Chinese Manhua',  blurb: 'Semi-realistic · cinematic light · rich color' },
  { id: 'pixar',  name: 'Pixar 3D',        blurb: 'Rounded · soft fill · polished render' },
  { id: 'comic',  name: 'Western Comic',   blurb: 'Halftone · bold ink · high contrast' },
  { id: 'noir',   name: 'Noir B&W',        blurb: 'Chiaroscuro · ink hatching · moody' },
  { id: 'custom', name: 'Custom Refs',     blurb: 'Upload 1–4 reference images' },
];

export const MODEL_OPTIONS = [
  {
    id: 'seedance-2-0',
    name: 'Seedance 2.0',
    tier: 'Pro',
    blurb: 'Best stylistic fidelity · 9:16 + 16:9 · 720p only',
    avg_s: 180,
    price_in:  '$0.50',
    price_out: '$15.00',
    endpoint: 'ap-southeast-1.ark.bytepluses.com',
  },
  {
    id: 'seedance-2-0-fast',
    name: 'Seedance 2.0',
    tier: 'Fast',
    blurb: '~2× throughput · 720p · slight loss of detail',
    avg_s: 92,
    price_in:  '$0.25',
    price_out: '$7.00',
    endpoint: 'ap-southeast-1.ark.bytepluses.com',
  },
  {
    id: 'custom',
    name: 'Custom Endpoint',
    tier: 'BYO',
    blurb: 'Point at your own OpenAI-compatible server · 720p',
    avg_s: null,
    price_in:  null,
    price_out: null,
    endpoint: '—',
  },
];

export const CLIP_COUNT = 21;
export const PROJECT_NAME = 'output_musk_ep1';
export const SOURCE_FILE = '7506075125058407711_Episode-1_MrMusk_I-am-w.mp4';

function makeClips() {
  const r = rng(0xb0bafe71);
  const clips = [];
  const statusBuckets = [
    ...Array(5).fill('done'),
    ...Array(5).fill('polling'),
    ...Array(5).fill('cartoon_ready'),
    ...Array(3).fill('keyframes'),
    ...Array(3).fill('split'),
  ];
  for (let i = 0; i < CLIP_COUNT; i++) {
    const id = i;
    const status = statusBuckets[i];
    const dur = +(3.6 + r() * 7).toFixed(2);
    const n_sub = 1 + Math.floor(r() * 3);
    const subshots = [];
    // cartoon path is only present once Seedream I2I has actually run
    const hasCartoon = ['cartoon_ready', 'polling', 'done'].includes(status);
    for (let j = 0; j < n_sub; j++) {
      subshots.push({
        idx: j,
        cartoon: hasCartoon ? CARTOON_THUMBS[(i * 3 + j) % CARTOON_THUMBS.length] : null,
        keyframe: CARTOON_THUMBS[(i * 3 + j + 1) % CARTOON_THUMBS.length],
        t_start: +(j * (dur / n_sub)).toFixed(2),
        t_end: +(((j + 1) * dur) / n_sub).toFixed(2),
        vlm_pass: status === 'done' || status === 'cartoon_ready'
          ? (r() > 0.18 ? true : false) : null,
        vlm_score: status === 'done' || status === 'cartoon_ready'
          ? +(0.62 + r() * 0.35).toFixed(2) : null,
        vlm_reason: '',
      });
    }
    subshots.forEach(s => {
      if (s.vlm_pass === false) {
        const reasons = [
          'Background walls retain photographic texture; cel-shading missing on lockers.',
          'Skin tone too realistic; cartoon stylisation only applied to face, not arms.',
          'Hair lacks defined highlight streaks expected in anime style.',
          'Floor and ceiling are photoreal; whole-frame stylisation incomplete.',
        ];
        s.vlm_reason = reasons[Math.floor(r() * reasons.length)];
      }
    });

    const task_id = (status === 'split' || status === 'keyframes' || status === 'cartoon_ready')
      ? ''
      : `cgt-2026051420${(3653 + i * 47).toString().padStart(4, '0')}-${'56rsxbtq9k4mh'.substr(i % 8, 5)}`;

    const ratio = r() > 0.3 ? '9:16' : '16:9';

    clips.push({
      clip_id: id,
      raw_path: `clips/${SOURCE_FILE.replace('.mp4', `-Clip-${(id+1).toString().padStart(3,'0')}.mp4`)}`,
      resized_path: `resized/clip_${String(id).padStart(2,'0')}.mp4`,
      duration_s: dur,
      ratio,
      width: ratio === '9:16' ? 720 : 1280,
      height: ratio === '9:16' ? 1280 : 720,
      subshots,
      n_subshots: n_sub,
      task_id,
      task_status: {
        done: 'succeeded',
        polling: r() > 0.5 ? 'running' : 'queued',
        cartoon_ready: null,
        keyframes: null,
        split: null,
      }[status],
      task_progress: status === 'polling' ? Math.floor(r() * 80 + 10) : (status === 'done' ? 100 : 0),
      status,
      style_verified: status === 'done',
      verify_attempts: status === 'done' ? (r() > 0.7 ? 2 : 1) : 0,
      retries: status === 'done' && r() > 0.8 ? 1 : 0,
      attempts: [],
      polls: 0,
      created_at: 1778762214 + i * 50,
      updated_at: 1778762214 + i * 50 + (status === 'done' ? 1700 : 0),
    });

    if (status === 'done' && clips[i].retries > 0) {
      clips[i].attempts.push({
        task_id: `cgt-202605142035${i*7}-old${i}`,
        verdict: 'fail',
        reason: 'VLM marked sub_01 as non-uniform stylisation; resubmitted.',
        output_url: '',
      });
    }
  }
  return clips;
}

export const INITIAL_STATE = {
  version: 4,
  project: PROJECT_NAME,
  work_dir: `~/cartoonize/${PROJECT_NAME}`,
  source: {
    name: SOURCE_FILE,
    size_mb: 38.4,
    duration_s: 142.6,
    resolution: '1280×720',
    fps: 30,
    codec: 'h264',
  },
  config: {
    style_id: 'anime',
    seedream_model: 'seedream-5-0-260128',
    seedance_model: 'dreamina-seedance-2-0-260128',
    seedance_resolution: '720p',
    seedream_image_size: 'auto',
    scene_threshold: 25.0,
    min_clip_duration: 4.0,
    max_clip_duration: 15.0,
    subshot_threshold: 27.0,
  },
  clips: makeClips(),
};

export const STYLES = STYLE_OPTIONS;
export const MODELS = MODEL_OPTIONS;
export const CARTOON_REF_IMAGES = CARTOON_THUMBS;
