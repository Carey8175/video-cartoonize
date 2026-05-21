"""
Preset cartoon/manga style definitions for the video-cartoonize pipeline.

Each StyleDef contains:
  - id           machine name (used as CLI arg / config value)
  - name / name_zh  display names
  - description  one-line description shown to user
  - seedream_prompt  I2I prompt sent to Seedream when no user ref images are supplied
  - ref_images   optional list of bundled reference image paths
                 (placed under scripts/style_refs/<id>/*.jpg)
  - size         Seedream output size string; set per-run based on clip aspect ratio

When the user supplies their OWN reference images, style-specific prompts are
overridden with CUSTOM_REF_PROMPT and the user images become Image 1..N.

Usage:
    from styles import get_style, STYLES, CUSTOM_STYLE_ID

    # Preset style
    style = get_style("manhwa")
    # → StyleDef with prompt + optional bundled refs

    # User-provided refs (no preset)
    style = get_style(CUSTOM_STYLE_ID, user_ref_paths=["/path/a.jpg", "/path/b.jpg"])
    # → StyleDef using CUSTOM_REF_PROMPT
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

# ─── ID for "user supplied their own reference images" ─────────────────────────
CUSTOM_STYLE_ID = "custom"

# ─── Bundled reference image root ─────────────────────────────────────────────
_STYLE_REFS_ROOT = os.path.join(os.path.dirname(__file__), "style_refs")


@dataclass
class StyleDef:
    id: str
    name: str
    name_zh: str
    description: str
    seedream_prompt: str
    ref_images: List[str] = field(default_factory=list)   # local paths to bundled refs
    user_ref_images: List[str] = field(default_factory=list)  # user-supplied ref paths


# ─── Whole-frame stylization clause (shared by all prompts) ───────────────────
# 0.14.6+: I2I tends to over-apply style to salient regions (faces, characters)
# and leave low-information regions (walls, lockers, sky) closer to the original
# photo. This clause emphasizes that EVERY pixel must be transformed — composition
# is preserved but rendering is uniformly cartoon.
_UNIFORM_STYLE_CLAUSE = (
    "Apply the cartoon rendering UNIFORMLY across the entire frame — every "
    "character, face, clothing, AND every background element (walls, floor, "
    "ceiling, lockers, posters, furniture, props, sky, foliage, lighting, "
    "shadows, ambient elements). NO photorealistic textures should remain "
    "anywhere in the image. Preserve only the COMPOSITION (camera angle, "
    "layout, positions) — do NOT add, remove, or move any element, but every "
    "pixel's rendering MUST match the cartoon style consistently from "
    "foreground to background."
)


# ─── Prompt used when user supplies their own reference images ─────────────────
CUSTOM_REF_PROMPT = (
    "Convert Image 1 into the same illustrated cartoon style shown in "
    "Image 2 (and Image 3 if provided). "
    + _UNIFORM_STYLE_CLAUSE +
    " Match the linework quality, shading technique, and color palette of the "
    "reference style across the full frame."
)


# ─── Preset style prompts ──────────────────────────────────────────────────────
# Rules for writing these prompts (Seedream I2I):
#   • State the target style clearly in the first sentence
#   • Describe linework, shading, color palette, face/eye style
#   • Always include _UNIFORM_STYLE_CLAUSE to force background coverage
#   • ≤150 words — I2I is anchor-driven; too-long prompts dilute attention
# ──────────────────────────────────────────────────────────────────────────────

_MANHWA_PROMPT = (
    "Convert the scene into Korean webtoon (manhwa) illustration style. "
    "Apply smooth gradient cel-shading with clean, precisely blended colors. "
    "Refined facial features with naturally proportioned eyes, slim elegant builds, "
    "and detailed hair with soft highlights. "
    "Warm luminous skin tones, sophisticated clothing textures. "
    "Soft bokeh depth-of-field effect on the background. "
    "Clean professional linework with consistent line weight. "
    + _UNIFORM_STYLE_CLAUSE
)

_ANIME_PROMPT = (
    "Convert the scene into Japanese anime illustration style. "
    "Bold clean outlines with expressive line weight variation. "
    "Cel-shaded flat coloring with sharp shadow cuts. "
    "Large expressive eyes with detailed irises, specular highlights, and visible pupils. "
    "Stylized hair with strong highlight streaks and deep shadow areas. "
    "Simplified but emotionally expressive facial features. "
    "Vibrant saturated color palette. "
    + _UNIFORM_STYLE_CLAUSE
)

_MANHUA_PROMPT = (
    "Convert the scene into Chinese manhua illustration style. "
    "Semi-realistic proportions with idealized, refined facial features. "
    "Smooth gradient shading with rich, saturated colors and cinematic lighting. "
    "Natural eye proportions with delicate double eyelids and detailed lashes. "
    "Elaborate clothing detail and fabric texture rendering. "
    "Warm golden highlights, dramatic rim lighting. "
    "Clean professional linework. "
    + _UNIFORM_STYLE_CLAUSE
)

_PIXAR_PROMPT = (
    "Convert the scene into Pixar-style 3D animated cartoon illustration. "
    "Rounded appealing character proportions with large expressive eyes. "
    "Smooth subsurface skin shading, soft indirect lighting. "
    "Simplified but highly expressive facial features. "
    "Warm soft fill light with subtle ambient occlusion. "
    "Clean polished surfaces, slightly exaggerated proportions. "
    "Friendly family-appropriate aesthetic, high-quality render look. "
    + _UNIFORM_STYLE_CLAUSE
)

_COMIC_PROMPT = (
    "Convert the scene into Western comic book illustration style. "
    "Bold black outlines with strong ink line weight. "
    "High contrast flat coloring with visible halftone dot patterns in midtones. "
    "Strong shadow contrast, limited but vivid color palette. "
    "Graphic, punchy composition with panel-ready framing. "
    "Expressive, slightly exaggerated facial features. "
    + _UNIFORM_STYLE_CLAUSE
)

_NOIR_PROMPT = (
    "Convert the scene into black-and-white noir comic illustration style. "
    "High contrast ink drawing — deep blacks, crisp whites, minimal midtones. "
    "Dramatic chiaroscuro lighting with strong shadows and rim highlights. "
    "Expressive hatching and cross-hatching for texture. "
    "Cinematic, moody atmosphere reminiscent of 1940s detective comics. "
    "Bold graphic silhouettes. "
    + _UNIFORM_STYLE_CLAUSE
)


# ─── Preset registry ──────────────────────────────────────────────────────────

def _bundled_refs(style_id: str) -> List[str]:
    """Return sorted list of bundled reference JPEGs for a preset style, if any."""
    d = os.path.join(_STYLE_REFS_ROOT, style_id)
    if not os.path.isdir(d):
        return []
    return sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )


STYLES: dict[str, StyleDef] = {
    "manhwa": StyleDef(
        id="manhwa",
        name="Korean Manhwa",
        name_zh="韩漫",
        description="Korean webtoon style — gradient cel-shading, refined features, soft bokeh",
        seedream_prompt=_MANHWA_PROMPT,
        ref_images=_bundled_refs("manhwa"),
    ),
    "anime": StyleDef(
        id="anime",
        name="Japanese Anime",
        name_zh="日漫",
        description="Japanese anime — bold outlines, large expressive eyes, cel-shaded flat colors",
        seedream_prompt=_ANIME_PROMPT,
        ref_images=_bundled_refs("anime"),
    ),
    "manhua": StyleDef(
        id="manhua",
        name="Chinese Manhua",
        name_zh="国漫",
        description="Chinese manhua — semi-realistic, rich colors, cinematic lighting",
        seedream_prompt=_MANHUA_PROMPT,
        ref_images=_bundled_refs("manhua"),
    ),
    "pixar": StyleDef(
        id="pixar",
        name="Pixar 3D",
        name_zh="皮克斯3D",
        description="Pixar-style 3D animation — rounded characters, soft lighting, polished render",
        seedream_prompt=_PIXAR_PROMPT,
        ref_images=_bundled_refs("pixar"),
    ),
    "comic": StyleDef(
        id="comic",
        name="Western Comic",
        name_zh="美漫",
        description="Western comic book — bold outlines, halftone coloring, high contrast",
        seedream_prompt=_COMIC_PROMPT,
        ref_images=_bundled_refs("comic"),
    ),
    "noir": StyleDef(
        id="noir",
        name="Noir Comic",
        name_zh="黑白noir漫画",
        description="Black-and-white noir comic — chiaroscuro, ink hatching, moody atmosphere",
        seedream_prompt=_NOIR_PROMPT,
        ref_images=_bundled_refs("noir"),
    ),
}


def get_style(
    style_id: str,
    user_ref_paths: Optional[List[str]] = None,
) -> StyleDef:
    """Return a StyleDef for the given style_id.

    If style_id == CUSTOM_STYLE_ID ("custom"), user_ref_paths must be provided.
    These become the reference images and CUSTOM_REF_PROMPT is used as the prompt.

    If style_id is a preset and user_ref_paths is also given, the user refs
    SUPPLEMENT (not replace) any bundled refs. The preset prompt is still used.

    Raises ValueError for unknown style_id (when not "custom").
    """
    if style_id == CUSTOM_STYLE_ID:
        if not user_ref_paths:
            raise ValueError(
                'style_id="custom" requires user_ref_paths to be provided.'
            )
        return StyleDef(
            id=CUSTOM_STYLE_ID,
            name="Custom Style",
            name_zh="自定义风格",
            description="User-supplied reference images",
            seedream_prompt=CUSTOM_REF_PROMPT,
            ref_images=[],
            user_ref_images=list(user_ref_paths),
        )

    if style_id not in STYLES:
        available = ", ".join(STYLES.keys())
        raise ValueError(
            f"Unknown style_id '{style_id}'. Available: {available}, or 'custom'."
        )

    style = STYLES[style_id]
    if user_ref_paths:
        # User adds extra refs on top of the preset
        style = StyleDef(
            id=style.id,
            name=style.name,
            name_zh=style.name_zh,
            description=style.description,
            seedream_prompt=style.seedream_prompt,
            ref_images=style.ref_images,
            user_ref_images=list(user_ref_paths),
        )
    return style


def list_styles() -> str:
    """Return a formatted table of available preset styles."""
    lines = ["Available preset styles:\n"]
    for sid, s in STYLES.items():
        has_refs = "✓ bundled refs" if s.ref_images else "  prompt only"
        lines.append(f"  {sid:<10} {s.name_zh} / {s.name:<20} [{has_refs}]  — {s.description}")
    lines.append(f"\n  {'custom':<10} 自定义 / Custom"
                 "                    — pass --ref-images to supply your own style references")
    return "\n".join(lines)
