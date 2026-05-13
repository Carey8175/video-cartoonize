from dataclasses import dataclass, field
from typing import List


@dataclass
class ClipInfo:
    clip_id: int
    raw_path: str
    resized_path: str

    subshot_frame_paths: List[str] = field(default_factory=list)
    subshot_cartoon_paths: List[str] = field(default_factory=list)
    subshot_cartoon_urls: List[str] = field(default_factory=list)

    output_url: str = ""
    output_path: str = ""
    status: str = "pending"
    retries: int = 0
    task_id: str = ""
