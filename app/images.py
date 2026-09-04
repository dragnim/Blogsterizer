"""Prepare a post's images for the new site.

The workflow: you put the post's images in a folder and give the app the path.
The app pairs each `<img>` in the HTML with a file in that folder, processes the
files, and replaces each tag with a visible placeholder for you to fill in by
hand.

Deliberate limits:

* Nothing is written outside the output folder, and an existing file is never
  overwritten silently.
* The originals are only ever read.
* An `<img>` with no matching file is reported, never guessed at. Likewise a
  file in the folder that no `<img>` references — that is usually one you meant
  to include.
* Existing alt text is a real human description. It is carried through, not
  thrown away and re-generated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from PIL import Image, ImageOps


TARGET_WIDTH = 1200

# An image much narrower than the target cannot be improved by processing: it is
# usually a WordPress thumbnail rather than the original, and putting it on the
# new site would look soft. Reported so it can be replaced with the full-size
# original or dropped. Not deleted: that is an editorial decision.
UNDERSIZE_RATIO = 0.75
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}

# Photographs need lossy compression to be a sensible size. Screenshots of code
# do not survive it: quality-80 WebP rings around crisp monospaced glyphs, and
# APL glyphs are dense enough that it shows.
PHOTO_QUALITY = 82
SCREENSHOT_NEAR_LOSSLESS = 60


@dataclass
class ImagePlan:
    """One image, matched or not, before anything is written."""

    index: int
    source: Path | None
    src_attribute: str
    output_name: str
    existing_alt: str = ""
    width: int | None = None
    height: int | None = None
    kind: str = "unknown"          # screenshot | photo
    encoding: str = ""             # near-lossless | lossy
    matched: bool = True
    note: str = ""
    undersize: bool = False

    @property
    def placeholder(self) -> str:
        return f"Image here: {self.output_name}"


@dataclass
class ImageReport:
    plans: list[ImagePlan] = field(default_factory=list)
    unreferenced: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def matched(self) -> list[ImagePlan]:
        return [plan for plan in self.plans if plan.matched]

    @property
    def unmatched(self) -> list[ImagePlan]:
        return [plan for plan in self.plans if not plan.matched]


def slugify(value: str) -> str:
    """Derive a slug from a blog URL or a plain title.

    A full URL keeps its last meaningful path segment, which is the post slug on
    a WordPress site.
    """
    value = value.strip()
    if not value:
        return "post"
    if "://" in value or value.startswith("/"):
        parts = [part for part in urlparse(value).path.split("/") if part]
        # Trailing numeric segments are dates, not the slug.
        while parts and parts[-1].isdigit():
            parts.pop()
        value = parts[-1] if parts else "post"
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "post"


def basename_of(src: str) -> str:
    """The filename an <img src> refers to, whatever form the src takes."""
    path = urlparse(src).path if "://" in src else src
    return unquote(Path(path).name)


def list_folder(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} is not a folder.")
    return sorted(
        entry for entry in folder.iterdir()
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_SUFFIXES
    )


def classify(image: Image.Image) -> str:
    """Guess whether this is a screenshot of text or a photograph.

    Screenshots use few distinct colours and large flat areas; photographs use
    many colours and gradients. Sampled at low resolution, which is plenty for
    this decision and keeps a large image cheap to inspect.
    """
    sample = image.convert("RGB")
    sample.thumbnail((200, 200))
    colours = sample.getcolors(maxcolors=200 * 200) or []
    if not colours:
        return "photo"

    pixels = sum(count for count, _ in colours)
    distinct = len(colours)
    # Share of the image taken up by its dozen most common colours.
    dominant = sum(count for count, _ in sorted(colours, reverse=True)[:12]) / pixels

    if distinct <= 256 or dominant >= 0.6:
        return "screenshot"
    return "photo"


def _open(path: Path) -> Image.Image:
    image = Image.open(path)
    image.load()
    return image


def plan_images(html: str, folder: Path, slug: str, prefix: str = "blog") -> ImageReport:
    """Pair each <img> with a file, in document order. Writes nothing."""
    report = ImageReport()
    available = {path.name.lower(): path for path in list_folder(folder)}
    used: set[str] = set()

    soup = BeautifulSoup(html, "html.parser")
    images = soup.find_all("img")

    for position, tag in enumerate(images, start=1):
        src = str(tag.get("src", "")).strip()
        name = basename_of(src).lower()
        source = available.get(name)
        output_name = f"{prefix}_{slug}_{position:02d}.webp"

        plan = ImagePlan(
            index=position,
            source=source,
            src_attribute=src,
            output_name=output_name,
            existing_alt=str(tag.get("alt", "")).strip(),
            matched=source is not None,
        )

        if source is None:
            plan.note = (
                f"No file named {basename_of(src) or '(no src)'} in the folder. "
                "Nothing was guessed."
            )
            report.plans.append(plan)
            continue

        used.add(name)
        try:
            with _open(source) as image:
                plan.width, plan.height = image.size
                plan.kind = classify(image)
        except Exception as exc:  # noqa: BLE001 - Pillow raises a variety
            plan.matched = False
            plan.note = f"Could not read {source.name}: {type(exc).__name__}."
            report.plans.append(plan)
            continue

        plan.encoding = "near-lossless" if plan.kind == "screenshot" else "lossy"
        if plan.width is not None and plan.width < TARGET_WIDTH * UNDERSIZE_RATIO:
            plan.undersize = True
            plan.note = (
                f"{plan.width}px wide, well short of the {TARGET_WIDTH}px target. "
                "Enlarging it would only make it soft, so it was converted at its own "
                "size. This is often a WordPress thumbnail rather than the original — "
                "find the full-size file, or drop the image."
            )
        report.plans.append(plan)

    report.unreferenced = sorted(
        path.name for key, path in available.items() if key not in used
    )
    return report


def process_images(
    report: ImageReport,
    output_folder: Path,
    target_width: int = TARGET_WIDTH,
    overwrite: bool = False,
) -> ImageReport:
    """Write the processed files. Only touches `output_folder`."""
    output_folder.mkdir(parents=True, exist_ok=True)

    for plan in report.matched:
        if plan.source is None:
            continue
        destination = output_folder / plan.output_name

        if destination.exists() and not overwrite:
            report.errors.append(
                f"{plan.output_name} already exists and was left alone. "
                "Tick overwrite to replace it."
            )
            continue

        try:
            with _open(plan.source) as image:
                # Honour any EXIF rotation, then drop the metadata: photographs
                # can carry camera and location data that has no business on a
                # public site.
                image = ImageOps.exif_transpose(image)
                image = image.convert("RGBA" if _has_alpha(image) else "RGB")

                # Never upscale: enlarging an image cannot add detail.
                if image.width > target_width:
                    height = round(image.height * target_width / image.width)
                    image = image.resize((target_width, height), Image.LANCZOS)

                if plan.kind == "screenshot":
                    image.save(
                        destination,
                        format="WEBP",
                        lossless=True,
                        near_lossless=SCREENSHOT_NEAR_LOSSLESS,
                        method=6,
                    )
                else:
                    image.save(
                        destination,
                        format="WEBP",
                        quality=PHOTO_QUALITY,
                        method=6,
                    )

                plan.width, plan.height = image.size
                report.written.append(plan.output_name)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{plan.source.name}: {type(exc).__name__} while processing.")

    return report


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info


def replace_with_placeholders(html: str, report: ImageReport) -> tuple[str, list[str]]:
    """Swap each <img> for a visible placeholder.

    This adds words to the copy, which the copy guard would otherwise reject, so
    it is an explicitly authorised change in the same way as the resource labels
    in section 7. The text is meant to be conspicuous: it is there to be found
    and replaced with a real image block by hand.
    """
    soup = BeautifulSoup(html, "html.parser")
    placeholders: list[str] = []
    plans = {plan.index: plan for plan in report.plans}

    for position, tag in enumerate(soup.find_all("img"), start=1):
        plan = plans.get(position)
        if plan is None or not plan.matched:
            continue

        # An <img> that is the whole content of a wrapper takes the wrapper with
        # it: a block placeholder nested inside a <p> is invalid HTML, and a
        # placeholder wrapped in a link is nonsense. A wrapper carrying its own
        # text — a <figure> with a <figcaption> — is left in place.
        target = tag
        for _ in range(3):
            parent = target.parent
            if parent is None or parent.name not in {"a", "p", "figure", "span", "div"}:
                break
            if parent.get_text(strip=True):
                break
            if any(
                child is not target and getattr(child, "name", None) is not None
                for child in parent.children
            ):
                break
            target = parent

        # An image sitting inside a sentence needs an inline placeholder, or the
        # paragraph ends up containing a block element.
        inline = target is tag and bool(
            tag.parent is not None and tag.parent.get_text(strip=True)
        )

        if inline:
            marker = soup.new_tag("strong")
            marker["class"] = ["image-placeholder"]
            marker.string = f"[{plan.placeholder}]"
        else:
            marker = soup.new_tag("p")
            marker["class"] = ["image-placeholder"]
            strong = soup.new_tag("strong")
            strong.string = plan.placeholder
            marker.append(strong)

        target.replace_with(marker)
        placeholders.append(plan.placeholder)

    return soup.decode(formatter="minimal"), placeholders
