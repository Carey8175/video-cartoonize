from dataclasses import dataclass


@dataclass
class PipelineConfig:
    # ── Phase 1: Scene splitting ──────────────────────────────────────
    scene_threshold: float = 25.0
    min_clip_duration: float = 4.0
    max_clip_duration: float = 15.0
    pixel_limit: int = 927408           # Seedance Assets API max pixels

    # ── Phase 2a: Sub-shot + key frame detection ──────────────────────
    subshot_threshold: float = 27.0

    # ── Phase 2b: Seedream I2I ────────────────────────────────────────
    style_id: str = "anime"
    seedream_model: str = "seedream-5-0-260128"
    seedream_image_size: str = "1440x2560"

    # ── Phase 3: video-analyse ────────────────────────────────────────
    analyse_fps: int = 4

    # ── Phase 5: Seedance ─────────────────────────────────────────────
    api_key: str = ""
    seedance_model: str = "dreamina-seedance-2-0-260128"
    seedance_resolution: str = "720p"
    max_retries: int = 2
    poll_interval: int = 10
