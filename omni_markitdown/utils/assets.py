"""画像アセット管理・決定論的ハッシュ採番
"""

import hashlib
from pathlib import Path
from typing import Optional, Tuple
from omni_markitdown.core.models import VisualAsset


def save_visual_asset(
    image_bytes: bytes,
    doc_hash: str,
    page_number: int,
    image_index: int,
    output_dir: Path,
    assets_dir_name: str = "_assets",
    ext: str = "png",
    bbox: Optional[Tuple[float, float, float, float]] = None,
    width: Optional[int] = None,
    height: Optional[int] = None
) -> VisualAsset:
    """抽出された画像バイト列を決定論的ファイル名で保存し、VisualAsset を返す"""
    sha256 = hashlib.sha256(image_bytes).hexdigest()[:12]
    asset_id = f"fig_p{page_number:03d}_{image_index:02d}_{sha256}"
    filename = f"{asset_id}.{ext}"

    assets_path = output_dir / assets_dir_name
    assets_path.mkdir(parents=True, exist_ok=True)
    file_path = assets_path / filename

    if not file_path.exists():
        with open(file_path, "wb") as f:
            f.write(image_bytes)

    rel_path = f"{assets_dir_name}/{filename}"

    return VisualAsset(
        asset_id=asset_id,
        file_path=file_path,
        rel_path=rel_path,
        page_number=page_number,
        index=image_index,
        sha256=sha256,
        width=width,
        height=height,
        bbox=bbox
    )
