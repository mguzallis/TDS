#!/usr/bin/env python3
"""
Forza TDS Builder
-----------------
Renders a two-page Technical Data Sheet PDF from a product JSON file,
using the real Forza brand assets (logo, header graphic, eagle watermark)
pulled from the catalog rebuild project.

Page size is true US Letter (8.5" x 11" / 612x792pt), matching the
production catalog TDS files.

Usage:
    python3 generate_tds.py products/T461.json
    python3 generate_tds.py products/T461.json --out output/T461_custom.pdf

Requires: jinja2, playwright, qrcode, pymupdf
    pip install jinja2 playwright qrcode[pil] pymupdf
First time only: playwright install chromium
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pymupdf
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
OUTPUT_DIR = ROOT / "output"

# Standard precautionary language, locked in after several rounds of review.
# Use these verbatim via the product JSON's "precautionary" block rather than
# re-wording per product:
#   - SDS-required products: PRECAUTION_SDS_REFERRAL
#   - Non-hazardous, no SDS required (e.g. GHS non-hazardous tape): PRECAUTION_NON_HAZARDOUS
# Never state a classification that hasn't actually been confirmed for that
# specific SKU — if unknown, leave "confirmed": false in the product JSON so
# it renders as a flagged placeholder instead.
PRECAUTION_SDS_REFERRAL = (
    "For complete hazard, handling, and precautionary information, refer to "
    "the product label and Safety Data Sheet (SDS) before use."
)
PRECAUTION_NON_HAZARDOUS = "This product is classified as Non-Hazardous under GHS."

LETTER_WIDTH_PX = 816   # 8.5in @ 96dpi -> 612pt via Playwright's 0.75 px->pt conversion
LETTER_HEIGHT_PX = 1056  # 11in @ 96dpi -> 792pt


def ensure_qr(url: str = "https://www.forzabuilt.com"):
    qr_path = ASSETS_DIR / "qr.png"
    if not qr_path.exists():
        import qrcode
        qrcode.make(url).save(qr_path)
    return qr_path


def precaution_paragraph(statements):
    """Join GHS hazard/precautionary statements into the single run-on,
    lower-case, comma-separated paragraph the shipped catalog uses for
    Precautionary Information (confirmed on 81-0389, C804, IC947 -- NOT
    separate paragraphs). Strips H/P codes and heading lines."""
    import re
    code = re.compile(r"^\s*[HP]\d{3}(\s*\+\s*[HP]\d{3})*\s*[\u2013\u2014-]\s*")
    parts = []
    for line in statements:
        line = code.sub("", line.strip())
        if not line or (line.endswith(":") and "statement" in line.lower()):
            continue
        segs = re.split(r"(?<=[.:])\s+(?=[A-Z])", line)
        for seg in segs:
            seg = seg.strip().rstrip(".:").strip()
            if not seg:
                continue
            words = seg.split(" ")
            if words[0].isupper() and len(words[0]) > 1 and words[0] not in {"CO2", "CO\u2082"}:
                i = 0
                while i < len(words) and words[i].isupper() and len(words[i]) > 1:
                    words[i] = words[i].lower(); i += 1
                seg = " ".join(words)
            elif len(seg) > 1 and seg[1].islower():
                seg = seg[0].lower() + seg[1:]
            seg = seg.replace("POISON CENTER", "poison center")
            if seg.lower() not in {x.lower() for x in parts}:
                parts.append(seg)
    if not parts:
        return ""
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + "."


def verify_two_pages(pdf_path: Path):
    """Hard ground-truth check: every TDS in this catalog is exactly 2 pages.
    Mirrors the check build_product.py used to run before any mockup was
    ever delivered. Raises instead of silently shipping a bad page count."""
    import pymupdf
    doc = pymupdf.open(str(pdf_path))
    n = len(doc)
    sizes = {(round(p.rect.width, 1), round(p.rect.height, 1)) for p in doc}
    if n != 2:
        raise SystemExit(
            f"FAILED page-count check: {pdf_path.name} rendered as {n} page(s), expected 2. "
            f"Trim copy — features/applications/left_sections are the usual culprits."
        )
    if sizes != {(612.0, 792.0)}:
        raise SystemExit(
            f"FAILED page-size check: {pdf_path.name} is {sizes}, expected (612.0, 792.0) "
            f"i.e. true US Letter."
        )
    print(f"Verified: {pdf_path.name} is 2 pages at true US Letter (8.5x11in).")


# "(Forza Test Method)" is shown only for the T205/T215/T220 family and their crosses.
FTM_KEEP = {"T205", "T215", "T220", "C-T550", "C-T553", "C-T557", "M-T815", "M-T820", "T-T246", "T-T415", "T-T420"}


_REG = re.compile(r"(Forza\s?(?:BOND|SEAL|TAPE))(?!\s?\u00ae)", re.I)


def add_reg(obj):
    """Every ForzaBOND / ForzaSEAL / ForzaTAPE in print gets a registered mark."""
    if isinstance(obj, str):
        return _REG.sub(lambda m: m.group(1) + "\u00ae", obj)
    if isinstance(obj, list):
        return [add_reg(x) for x in obj]
    if isinstance(obj, dict):
        return {k: (v if k in ("sku", "photo", "vertical", "brand", "product_type") else add_reg(v)) for k, v in obj.items()}
    return obj


def strip_ftm(data):
    if data.get("sku") in FTM_KEEP:
        return data
    data["tech_data"] = [[str(r[0]).replace(" (Forza Test Method)", "").replace("(Forza Test Method)", "").strip()] + list(r[1:])
                         for r in data.get("tech_data", [])]
    return data


def build(product_path: Path, out_path: Path | None = None, photo: str | None = None):
    data = add_reg(strip_ftm(json.loads(product_path.read_text())))
    ensure_qr()

    env = Environment(loader=FileSystemLoader(str(BUILD_DIR)))
    template = env.get_template("template.html.j2")

    data["photo"] = photo or data.get("photo")
    data.setdefault("vertical", "insulation")
    brand = data.get("brand") or "tape"
    logo = ASSETS_DIR / f"logo_{brand}.png"
    if not logo.exists():
        have = sorted(p.stem[len("logo_"):] for p in ASSETS_DIR.glob("logo_*.png"))
        raise SystemExit(
            f"Missing logo file assets/logo_{brand}.png (logos available: {', '.join(have) or 'none'}). "
            f"Upload it to the assets folder in GitHub."
        )

    if out_path is None:
        out_path = OUTPUT_DIR / f"{data['sku']}_TDS.pdf"
    html_path = OUTPUT_DIR / f"{data['sku']}.html"

    # Spacing is automatic unless the product JSON forces it: first try the
    # standard (roomier) layout and, only if that spills past 2 pages, switch
    # to the compact layout. If even compact doesn't fit, the check below
    # reports the failure so copy can be trimmed.
    if "compact" in data:
        attempts = ["compact" if data["compact"] else "standard"]
    else:
        attempts = ["standard", "compact", "tight"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": LETTER_WIDTH_PX, "height": LETTER_HEIGHT_PX})
        for layout in attempts:
            html = template.render(
                assets_dir=str(ASSETS_DIR.as_posix()),
                **{**data, "compact": layout != "standard", "tight": layout == "tight"},
            )
            html_path.write_text(html)
            page.goto(html_path.as_uri())
            page.pdf(
                path=str(out_path),
                width=f"{LETTER_WIDTH_PX}px",
                height=f"{LETTER_HEIGHT_PX}px",
                print_background=True,
            )
            build.last_layout = layout
            doc = pymupdf.open(str(out_path))
            pages = len(doc)
            doc.close()
            if pages == 2:
                break
        browser.close()

    verify_two_pages(out_path)
    print(f"Built: {out_path} ({build.last_layout} spacing)")
    return out_path


build.last_layout = "standard"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("product_json", help="Path to a product JSON file (see products/_example.json)")
    parser.add_argument("--out", help="Output PDF path (default: output/<SKU>_TDS.pdf)")
    parser.add_argument("--photo", help="Filename of a product photo in assets/ to show in the header")
    args = parser.parse_args()

    build(Path(args.product_json), Path(args.out) if args.out else None, args.photo)
