"""
Character identification, keyframe mapping and anime-ref generation.

Pipeline:
  1. identify_characters()    → face clustering, role classification, state.characters
  2. map_keyframes_to_characters() → per-keyframe face matching, state.char_keyframe_map
  3. generate_anime_refs()    → Seedream I2I for each char, state.characters[i].anime_ref

Role thresholds (configurable):
  protagonist  freq >= PROTAGONIST_FREQ_DEFAULT (0.10)
  supporting   freq >= SUPPORTING_FREQ_DEFAULT  (0.04)
  extra        freq <  SUPPORTING_FREQ_DEFAULT   → discarded
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# ── defaults ──────────────────────────────────────────────────────────────────
SAMPLE_FPS              = 0.5
CLUSTER_THRESHOLD       = 0.55   # AgglomerativeClustering cosine-distance threshold
MIN_DET_SCORE           = 0.72   # InsightFace detection confidence minimum
PROTAGONIST_FREQ_DEFAULT = 0.10
SUPPORTING_FREQ_DEFAULT  = 0.04
MATCH_THRESHOLD         = 0.50   # keyframe → character cosine-distance threshold


# ── InsightFace lazy singleton ─────────────────────────────────────────────────

_face_app = None


def get_face_app():
    """Lazy-load InsightFace FaceAnalysis (buffalo_l, CPU)."""
    global _face_app
    if _face_app is None:
        try:
            from insightface.app import FaceAnalysis
        except ImportError as e:
            raise ImportError(
                "insightface not installed. Run: pip install insightface onnxruntime"
            ) from e
        _face_app = FaceAnalysis(name="buffalo_l",
                                 providers=["CPUExecutionProvider"])
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
    return _face_app


def insightface_available() -> bool:
    try:
        from insightface.app import FaceAnalysis  # noqa: F401
        return True
    except ImportError:
        return False


# ── frame sampling ─────────────────────────────────────────────────────────────

def sample_video_frames(video_path: str, out_dir: str,
                        fps: float = SAMPLE_FPS) -> List[str]:
    """Sample frames from video at given fps. Returns sorted list of jpg paths."""
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", video_path, "-vf", f"fps={fps}", "-q:v", "2",
         os.path.join(out_dir, "frame_%04d.jpg")],
        check=True, timeout=300,
    )
    from pathlib import Path
    return sorted(str(p) for p in Path(out_dir).glob("frame_*.jpg"))


# ── face helpers ──────────────────────────────────────────────────────────────

def detect_faces(app, img: np.ndarray,
                 min_score: float = MIN_DET_SCORE) -> List[Dict]:
    """Return list of {emb, bbox, det_score} for high-confidence faces."""
    faces = app.get(img)
    result = []
    for face in faces:
        if float(face.det_score) < min_score:
            continue
        result.append({
            "emb":   face.normed_embedding.copy(),
            "bbox":  [int(v) for v in face.bbox],
            "score": float(face.det_score),
        })
    return result


def embed_from_file(app, path: str,
                    min_score: float = 0.55) -> Optional[np.ndarray]:
    """Get best face embedding from a single image file."""
    img = cv2.imread(path)
    if img is None:
        return None
    faces = app.get(img)
    if not faces:
        return None
    best = max(faces, key=lambda f: f.det_score)
    if float(best.det_score) < min_score:
        return None
    return best.normed_embedding.copy()


def cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


# ── clustering ────────────────────────────────────────────────────────────────

def cluster_embeddings(embs: List[np.ndarray],
                       threshold: float = CLUSTER_THRESHOLD) -> List[int]:
    """AgglomerativeClustering on cosine distance matrix. Returns label per embedding."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics.pairwise import cosine_distances

    n = len(embs)
    if n == 0:
        return []
    if n == 1:
        return [0]

    D = cosine_distances(np.stack(embs))
    labels = AgglomerativeClustering(
        n_clusters=None, metric="precomputed",
        linkage="average", distance_threshold=threshold,
    ).fit_predict(D)
    return list(map(int, labels))


# ── face crop ────────────────────────────────────────────────────────────────

def best_face_crop(img: np.ndarray, bbox: List[int],
                   pad_ratio: float = 0.35) -> np.ndarray:
    """Crop face with padding, resize to 256×256."""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    fh, fw = y2 - y1, x2 - x1
    pad = int(max(fh, fw) * pad_ratio)
    x1c = max(0, x1 - pad)
    y1c = max(0, y1 - pad)
    x2c = min(w, x2 + pad)
    y2c = min(h, y2 + pad)
    crop = img[y1c:y2c, x1c:x2c]
    if crop.size == 0:
        return img
    return cv2.resize(crop, (256, 256), interpolation=cv2.INTER_AREA)


# ── identify ──────────────────────────────────────────────────────────────────

def identify_characters(
    video_path: str,
    work_dir: str,
    fps: float = SAMPLE_FPS,
    cluster_threshold: float = CLUSTER_THRESHOLD,
    min_det_score: float = MIN_DET_SCORE,
    protagonist_freq: float = PROTAGONIST_FREQ_DEFAULT,
    supporting_freq: float = SUPPORTING_FREQ_DEFAULT,
) -> List[Dict]:
    """
    Detect all characters in a video, classify into roles, save face crops.

    Returns list of character dicts (also written to state.json by the caller):
      [{char_id, role, freq, face_ref (path), anime_ref (None until char-refs step)}, ...]
    """
    app = get_face_app()

    # 1. Sample frames
    frames_dir = os.path.join(work_dir, "_identify_frames")
    print(f"[Identify] Sampling at {fps} fps ...")
    frame_paths = sample_video_frames(video_path, frames_dir, fps=fps)
    total_frames = len(frame_paths)
    print(f"[Identify] {total_frames} frames sampled")

    # 2. Detect + embed all faces
    all_dets: List[Dict] = []
    for fi, fp in enumerate(frame_paths):
        img = cv2.imread(fp)
        if img is None:
            continue
        for det in detect_faces(app, img, min_score=min_det_score):
            all_dets.append({**det, "frame_idx": fi, "img_path": fp})

    print(f"[Identify] {len(all_dets)} face detections")
    if len(all_dets) < 2:
        print("[Identify] Not enough faces — check video quality or lower --min-det-score")
        return []

    # 3. Cluster
    labels = cluster_embeddings([d["emb"] for d in all_dets], threshold=cluster_threshold)

    # 4. Compute per-cluster stats
    cluster_frames: Dict[int, set] = {}
    cluster_dets:   Dict[int, List] = {}
    for det, lbl in zip(all_dets, labels):
        cluster_frames.setdefault(lbl, set()).add(det["frame_idx"])
        cluster_dets.setdefault(lbl, []).append(det)

    # 5. Classify by freq, sort by freq descending
    cluster_freq = {lbl: len(frames) / total_frames
                    for lbl, frames in cluster_frames.items()}
    sorted_clusters = sorted(cluster_freq, key=lambda k: -cluster_freq[k])

    # 6. Build character list; save face crop for non-extras
    chars_dir = os.path.join(work_dir, "characters")
    os.makedirs(chars_dir, exist_ok=True)

    characters: List[Dict] = []
    char_id = 0
    for lbl in sorted_clusters:
        freq = cluster_freq[lbl]
        if freq >= protagonist_freq:
            role = "protagonist"
        elif freq >= supporting_freq:
            role = "supporting"
        else:
            continue   # extra → skip

        # Best representative: highest det_score
        dets = cluster_dets[lbl]
        best = max(dets, key=lambda d: d["score"])
        img  = cv2.imread(best["img_path"])
        crop = best_face_crop(img, best["bbox"]) if img is not None else None

        face_ref = os.path.join(chars_dir, f"char_{char_id:02d}_face.jpg")
        if crop is not None:
            cv2.imwrite(face_ref, crop)
        else:
            face_ref = ""

        characters.append({
            "char_id":   char_id,
            "role":      role,
            "freq":      round(freq, 4),
            "face_ref":  face_ref,
            "anime_ref": None,            # filled by generate_anime_refs()
        })
        print(f"[Identify] {role:<12} #{char_id:02d}  freq={freq*100:.1f}%  "
              f"({len(dets)} detections)  crop={'OK' if crop is not None else 'FAIL'}")
        char_id += 1

    print(f"[Identify] {sum(1 for c in characters if c['role']=='protagonist')} protagonist(s), "
          f"{sum(1 for c in characters if c['role']=='supporting')} supporting")
    return characters


# ── keyframe → character mapping ──────────────────────────────────────────────

def map_keyframes_to_characters(
    work_dir: str,
    characters: List[Dict],
    clips,                          # List[ClipInfo] — already loaded from state
    min_det_score: float = MIN_DET_SCORE,
    match_threshold: float = MATCH_THRESHOLD,
) -> Dict[str, Dict[str, List[int]]]:
    """
    For every keyframe image, detect faces and match against known character refs.

    Returns char_keyframe_map:
      { "clip_id": { "kf_idx": [char_id, ...] } }

    Only protagonist and supporting characters are tracked; extras are ignored.
    """
    if not characters:
        return {}

    app      = get_face_app()
    char_dir = os.path.join(work_dir, "characters")

    # Pre-embed each character's face ref
    char_embs: List[Tuple[int, np.ndarray]] = []
    for c in characters:
        face_ref = c.get("face_ref", "")
        if not face_ref or not os.path.exists(face_ref):
            print(f"[MapKF] Char #{c['char_id']} has no face_ref, skipping")
            continue
        emb = embed_from_file(app, face_ref)
        if emb is None:
            print(f"[MapKF] Char #{c['char_id']} face_ref has no detectable face, skipping")
            continue
        char_embs.append((c["char_id"], emb))

    if not char_embs:
        print("[MapKF] No character embeddings available — run `cartoonize identify` first")
        return {}

    kf_root = os.path.join(work_dir, "keyframes")
    mapping: Dict[str, Dict[str, List[int]]] = {}
    total_kf = matched_kf = 0

    for clip in clips:
        clip_kf_dir = os.path.join(kf_root, f"clip_{clip.clip_id:02d}")
        if not os.path.isdir(clip_kf_dir):
            continue

        from pathlib import Path
        kf_files = sorted(Path(clip_kf_dir).glob("*.jpg"))
        clip_map: Dict[str, List[int]] = {}

        for kf_idx, kf_path in enumerate(kf_files):
            total_kf += 1
            img = cv2.imread(str(kf_path))
            if img is None:
                continue

            face_dets = detect_faces(app, img, min_score=min_det_score)
            matched_char_ids = []
            for det in face_dets:
                best_char_id = None
                best_dist    = match_threshold
                for char_id, char_emb in char_embs:
                    d = cosine_dist(det["emb"], char_emb)
                    if d < best_dist:
                        best_dist    = d
                        best_char_id = char_id
                if best_char_id is not None and best_char_id not in matched_char_ids:
                    matched_char_ids.append(best_char_id)

            if matched_char_ids:
                clip_map[str(kf_idx)] = matched_char_ids
                matched_kf += 1

        if clip_map:
            mapping[str(clip.clip_id)] = clip_map

    match_rate = matched_kf / max(total_kf, 1) * 100
    print(f"[MapKF] {total_kf} keyframes → {matched_kf} matched "
          f"({match_rate:.0f}%)")
    return mapping


# ── anime ref generation ──────────────────────────────────────────────────────

def generate_anime_refs(
    work_dir: str,
    characters: List[Dict],
    style,                      # StyleDef
    api_key: str,
    model: str = "seedream-5-0-260128",
    size: Optional[str] = None,
    max_workers: int = 5,
) -> List[Dict]:
    """
    Run Seedream I2I to create an anime-style reference image for each
    protagonist / supporting character — concurrently (default 5 threads).

    Updates each character dict in-place (sets anime_ref) and returns the
    updated list. Records billing via billing.record().
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from video_cartoonize.scene_describe import _seedream_i2i

    chars_dir  = os.path.join(work_dir, "characters")
    style_refs = list(style.ref_images) + list(style.user_ref_images)

    # Separate chars with valid face_ref from those without
    to_process = [c for c in characters if c.get("face_ref") and os.path.exists(c["face_ref"])]
    skipped    = [c for c in characters if c not in to_process]
    for c in skipped:
        print(f"[CharRefs] #{c['char_id']:02d} no face_ref — skipping")

    def _process_one(c: Dict) -> Dict:
        anime_path = os.path.join(chars_dir, f"char_{c['char_id']:02d}_anime.jpg")
        img_bytes  = _seedream_i2i(
            frame_path=c["face_ref"],
            style_ref_paths=style_refs,
            api_key=api_key,
            prompt=style.seedream_prompt,
            model=model,
            size=size,
            clip_id=c["char_id"],
        )
        if img_bytes:
            with open(anime_path, "wb") as f:
                f.write(img_bytes)
            c["anime_ref"] = anime_path
            print(f"[CharRefs] #{c['char_id']:02d} {c['role']:<12} ✓")
        else:
            c["anime_ref"] = None
            print(f"[CharRefs] #{c['char_id']:02d} {c['role']:<12} ✗ Seedream failed")
        return c

    results: Dict[int, Dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_process_one, c): c["char_id"] for c in to_process}
        for fut in as_completed(futures):
            c = fut.result()
            results[c["char_id"]] = c

    # Reconstruct in original order
    char_map = {c["char_id"]: results.get(c["char_id"], c) for c in characters}
    updated  = [char_map[c["char_id"]] for c in characters]

    n_ok = sum(1 for c in updated if c.get("anime_ref"))
    print(f"[CharRefs] {n_ok}/{len(updated)} anime refs generated (concurrency={max_workers})")
    return updated


# ── per-keyframe ref resolver ─────────────────────────────────────────────────

def resolve_keyframe_char_refs(
    clip_id: int,
    kf_idx: int,
    characters: List[Dict],
    char_keyframe_map: Dict,
) -> List[str]:
    """
    Return a list of anime_ref paths for characters appearing in this keyframe.

    Called by cmd_cartoon to build per-frame extra_refs.
    Returns [] if no characters mapped or no anime refs generated yet.
    """
    clip_map = char_keyframe_map.get(str(clip_id), {})
    char_ids = clip_map.get(str(kf_idx), [])
    if not char_ids:
        return []

    char_by_id = {c["char_id"]: c for c in characters}
    refs = []
    for cid in char_ids:
        c = char_by_id.get(cid)
        if c and c.get("anime_ref") and os.path.exists(c["anime_ref"]):
            refs.append(c["anime_ref"])
    return refs
