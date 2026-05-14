"""Assets API — required to bypass real-person privacy filter."""
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, Tuple

from video_cartoonize.assets_client import (
    create_asset, wait_for_active, list_asset_groups, create_asset_group,
)


def get_or_create_group(name: str, description: str = "") -> str:
    groups = list_asset_groups()
    for g in groups.get("Items", []):
        if g.get("Name") == name:
            return g["Id"]
    r = create_asset_group(name=name, description=description or name)
    if isinstance(r, dict):
        return r.get("Result", {}).get("Id") or r.get("Id") or r["Id"]
    return r


def upload_assets(
    group_id: str,
    items: Iterable[Tuple[str, str, str, str]],
    timeout_s: int = 180,
    max_workers: int = 7,
) -> Dict[str, str]:
    """Upload files in parallel, wait until Active. Returns {label: asset_url}."""
    def one(item):
        label, asset_type, src_url, name = item
        try:
            aid = create_asset(group_id=group_id, url=src_url,
                               asset_type=asset_type, name=name,
                               moderation={"Strategy": "Skip"})
            info = wait_for_active(aid, interval_seconds=3, timeout_seconds=timeout_s)
            if info.get("Status") == "Active":
                return label, f"asset://{aid}", None
            return label, None, f"status={info.get('Status')}"
        except Exception as e:
            return label, None, str(e)

    out: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for label, url, err in pool.map(one, list(items)):
            if url:
                out[label] = url
                print(f"  [{label:<20}] ✓ {url}")
            else:
                print(f"  [{label:<20}] ✗ {err}")
    return out
