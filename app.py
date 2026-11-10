#!/usr/bin/env python3
"""
Forza TDS Generator (Streamlit app)
------------------------------------
A form-driven front end for build/generate_tds.py. Fill in a product's
fields, hit Generate, and download the finished two-page TDS PDF -- same
pipeline, same real brand assets, same verified template as the
command-line tool, just without hand-editing JSON.

Run locally:
    pip install -r requirements.txt
    playwright install chromium      # one-time
    streamlit run app.py

Matches the pattern of the other Forza apps (SDS Formatter, Label
Generator): a Streamlit front end over an existing generation pipeline,
meant to eventually sit alongside them on the Forza App Hub.
"""
import json
import re
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "build"))

from generate_tds import (  # noqa: E402
    build,
    PRECAUTION_SDS_REFERRAL,
    PRECAUTION_NON_HAZARDOUS,
)

ASSETS_DIR = ROOT / "assets"
PRODUCTS_DIR = ROOT / "products"
OUTPUT_DIR = ROOT / "output"
HEADERS_DIR = ASSETS_DIR / "headers"

BRAND_NAVY = "#1B3764"    # Regal Blue (Brand Standards V6)
BRAND_ORANGE = "#F16022"  # Blaze Orange (Brand Standards V6)

# Tapes have no SDS, so Storage & Disposal uses this standard language
# (same wording as the approved T461 tape sheet; change the shelf life per product).
TAPE_STORAGE_BOILERPLATE = (
    "Store material in original unopened packaging at temperatures between 40\u00b0F and 100\u00b0F. "
    "Shelf life is 12 months when stored as recommended."
)

try:
    from PIL import Image as _PILImage
    _page_icon = _PILImage.open(ASSETS_DIR / "eagle_icon.png")
except Exception:
    _page_icon = "📄"
st.set_page_config(page_title="Forza TDS Generator", page_icon=_page_icon, layout="wide")


def apply_brand():
    """Forza brand standards for the app itself: Kallisto Heavy headings,
    Poppins body, Regal Blue / Blaze Orange, eagle logo header."""
    import base64
    try:
        kal = base64.b64encode((ASSETS_DIR / "fonts" / "Kallisto_Heavy.otf").read_bytes()).decode()
        eagle = base64.b64encode((ASSETS_DIR / "eagle_icon.png").read_bytes()).decode()
    except Exception:
        return
    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap');
@font-face {{
  font-family: 'Kallisto Heavy';
  src: url(data:font/otf;base64,{kal}) format('opentype');
  font-weight: 900; font-style: normal;
}}
html, body, [class*="css"], .stApp, .stMarkdown, label, p, li, input, textarea, select, button {{
  font-family: 'Poppins', sans-serif;
}}
h1, h2, h3, h4, [data-testid="stHeading"] * {{
  font-family: 'Kallisto Heavy', 'Poppins', sans-serif !important;
  color: {BRAND_NAVY};
  font-weight: 900;
  letter-spacing: 0.01em;
}}
h3 {{ border-bottom: 2px solid {BRAND_ORANGE}; padding-bottom: .25rem; }}
.stApp a {{ color: {BRAND_ORANGE}; }}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: {BRAND_ORANGE}; border-color: {BRAND_ORANGE}; color: #fff; font-weight: 700;
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {{
  background: #d94f14; border-color: #d94f14;
}}
.stButton > button, .stFormSubmitButton > button {{ border-radius: 6px; }}
.forza-header {{
  background: {BRAND_NAVY}; border-bottom: 4px solid {BRAND_ORANGE};
  border-radius: 8px; padding: 14px 22px; margin: -0.5rem 0 1.25rem 0;
  display: flex; align-items: center; gap: 18px;
}}
.forza-header img {{ height: 64px; width: auto; }}
.forza-header .t {{ font-family: 'Kallisto Heavy', 'Poppins', sans-serif; color: #fff;
  font-size: 2rem; line-height: 1.1; font-weight: 900; }}
.forza-header .s {{ color: #cfd8e8; font-size: .85rem; margin-top: 2px; }}
</style>
<div class="forza-header">
  <img src="data:image/png;base64,{eagle}" alt="Forza eagle"/>
  <div><div class="t">TDS Generator</div>
  <div class="s">Purpose-built. Performance. Guaranteed strength.</div></div>
</div>
""",
        unsafe_allow_html=True,
    )


apply_brand()


@st.cache_resource(show_spinner="Setting up PDF renderer (first run only)...")
def _ensure_chromium():
    """On hosted deploys (e.g. Streamlit Cloud) Chromium isn't preinstalled.
    Playwright's installer is a fast no-op if it's already there."""
    import subprocess
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)


_ensure_chromium()

# Non-photo assets to exclude from the "pick an existing photo" dropdown.
_NON_PHOTO_ASSETS = {
    "logo.png", "watermark.png", "flag.png", "qr.png", "qr_example.png",
    "header_bg.png",
}


def list_verticals():
    if not HEADERS_DIR.exists():
        return ["insulation"]
    names = sorted(p.stem for p in HEADERS_DIR.glob("*.png"))
    return names or ["insulation"]


def list_brands():
    """Brand lines that have a logo_<brand>.png in assets/ (tape, bond, ...)."""
    names = sorted(p.stem.replace("logo_", "", 1) for p in ASSETS_DIR.glob("logo_*.png"))
    return names or ["tape"]


def list_products():
    if not PRODUCTS_DIR.exists():
        return []
    return sorted(
        p.stem for p in PRODUCTS_DIR.glob("*.json") if not p.stem.startswith("_")
    )


def list_existing_photos():
    if not ASSETS_DIR.exists():
        return []
    return sorted(
        p.name for p in ASSETS_DIR.glob("*.png") if p.name not in _NON_PHOTO_ASSETS
    )


def lines_to_list(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def list_to_lines(items):
    return "\n".join(items or [])


# ---------------------------------------------------------------------------
# Source-of-truth draft saving. Apps never write to the approved master
# (data/); they only add or replace one row in drafts/tds.csv through the
# shared helper tools/master_repo.py (copied in unchanged). The owner
# approves drafts. Needs GITHUB_TOKEN in the app's Secrets.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(ROOT / "tools"))

_SECTION_TO_COLUMN = {
    "Surface Preparation": "Surface Preparation",
    "Application Instructions": "Application Instructions",
    "Clean Up Information": "Clean Up Information",
    "Storage & Disposal": "Storage",
}


def build_master_row(data):
    """Map this app's product JSON onto the exact columns of the `tds` tab."""
    def lines(items):
        return "\n".join(i for i in (items or []) if i)

    row = {
        "Category": (data.get("vertical") or "").title(),
        "Product Code": data["sku"],
        "Brand Line": (data.get("brand") or "").upper(),
        # Product Type and TDS Title both hold the exact title printed on the TDS.
        "Product Type": data["product_name"],
        "TDS Title": data["product_name"],
        "Description": data["intro"],
        "Features": lines(data.get("features")),
        "Applications Intro": data.get("applications_lead") or "",
        "Applications": lines(data.get("applications")),
        "Substrates Intro": data.get("substrates_lead") or "",
        "Substrates": lines(data.get("substrates")),
        "Technical Data Table": "\n".join(f"{p}: {v}" for p, v in data.get("tech_data", []) if p),
        "Packaging": lines(data.get("packaging")),
        "Precautionary Information": (data.get("precautionary") or {}).get("text", ""),
    }
    if data.get("recommended_equipment") is not None:
        row["Recommended Equipment"] = lines(data["recommended_equipment"])
    for sec in data.get("left_sections", []):
        col = _SECTION_TO_COLUMN.get(sec["title"])
        if col:
            row[col] = "\n".join(sec["paragraphs"])
    return row


def save_tds_draft(data):
    """Save one draft row to the source of truth. Returns (status, error)."""
    try:
        import master_repo
    except Exception as e:  # helper missing
        return None, f"GitHub helper not available: {e}"
    row = build_master_row(data)
    try:
        approved = {m.get("Product Code") for m in master_repo.read_master("tds")}
        if row["Product Code"] in approved:
            # Existing product: keep the master's Category / Brand Line.
            row.pop("Category", None)
            row.pop("Brand Line", None)
        return master_repo.save_draft("tds", row, who="TDS Builder"), None
    except Exception as e:
        return None, str(e)


def standard_bead_chart():
    """The one standard Bead Chart used on every cartridge/MS product.

    Pure geometry: 1 fl oz = 1.8046875 in^3, so linear yield = volume divided
    by the cross-section of a round bead (pi * d^2 / 4). Matches the chart
    printed on the shipped TDSs (1/8" = 12.25 ft ... 3/4" = 4.08 in).
    """
    import math
    rows = []
    for num, den in [(1, 8), (1, 4), (3, 8), (1, 2), (5, 8), (3, 4)]:
        d = num / den
        length_in = 1.8046875 / (math.pi * d * d / 4)
        rows.append([f'{num}/{den}"', f"{length_in / 12:.2f} ft" if length_in >= 12 else f"{length_in:.2f} in"])
    return rows


def extract_product_photo(pdf_bytes):
    """Pull the header product photo out of an existing TDS (PDF) as PNG bytes
    with its transparency, or None if the sheet has no product photo."""
    import io
    import pymupdf
    from PIL import Image

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[0]
        best = None
        for im in page.get_images(full=True):
            xref, smask, w, h = im[0], im[1], im[2], im[3]
            if w < 200 or h < 200:
                continue
            rects = page.get_image_rects(xref)
            if not rects:
                continue
            r = rects[0]
            # header photo: upper right, not the full-width header art, logo or watermark
            if r.width > 400 or r.x1 < 350 or r.y0 > 260 or r.y1 < 100:
                continue
            if best is None or w * h > best[2] * best[3]:
                best = (xref, smask, w, h)
        if best is None:
            return None
        xref, smask, _, _ = best
        pm = pymupdf.Pixmap(doc, xref)
        if pm.colorspace is None or pm.colorspace.n != 3:
            pm = pymupdf.Pixmap(pymupdf.csRGB, pm)
        if pm.alpha:
            pm = pymupdf.Pixmap(pm, 0)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples).convert("RGBA")
        if smask:
            mask = pymupdf.Pixmap(doc, smask)
            img.putalpha(Image.frombytes("L", (mask.width, mask.height), mask.samples))
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        img.save(out, "PNG", optimize=True)
        return out.getvalue()
    finally:
        doc.close()


def extract_storage_disposal(pdf_bytes):
    """Pull the Storage & Disposal language verbatim from an SDS PDF.

    Storage = the storage paragraph of SECTION 7 (Handling and Storage);
    Disposal = the body of SECTION 13 (Disposal Considerations). The wording
    is kept exactly as written in the SDS (only line breaks, page footers and
    the leading field labels such as "Storage:" are removed) so the TDS and
    SDS always match. Returns (storage, disposal) -- either may be "" if that
    section/label isn't found, so the caller can warn the user.
    """
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    # Drop page footers that land in the middle of a section.
    text = re.sub(r"\n\s*Page\s+\d+\s+of\s+\d+\s*\n", "\n", text)
    text = re.sub(r"\n\s*DCN:[^\n]*\n", "\n", text)

    def section(start_pat, end_pat):
        m = re.search(start_pat, text, re.IGNORECASE)
        if not m:
            return ""
        rest = text[m.end():]
        e = re.search(end_pat, rest, re.IGNORECASE)
        return rest[: e.start()] if e else rest

    def tidy(t):
        return re.sub(r"\s+", " ", t).strip()

    s7 = section(r"SECTION\s*7\s*[\u2013\u2014-]\s*Handling[^\n]*\n", r"SECTION\s*8\b")
    s13 = section(r"SECTION\s*13\s*[\u2013\u2014-]\s*Disposal[^\n]*\n", r"SECTION\s*14\b")

    storage = ""
    m = re.search(r"(?:Conditions\s+for\s+safe\s+storage|Storage)\s*:\s*", s7, re.IGNORECASE)
    if m:
        body = s7[m.end():]
        nxt = re.search(r"\n\s*[A-Z][A-Za-z/ ]{2,40}:\s", body)
        storage = tidy(body[: nxt.start()] if nxt else body)

    # Disposal: every paragraph of Section 13, minus the field label in front
    # (e.g. "Waste treatment methods:") and pure waste-code lines.
    label = r"^\s*(?:Waste\s+treatment(?:\s+methods?)?|Method|Waste\s+Disposal|Contaminated\s+packaging|Disposal)\s*:\s*"
    parts = []
    for line in s13.split("\n"):
        if re.match(r"^\s*Waste\s+Code\s*:", line, re.IGNORECASE):
            continue
        parts.append(re.sub(label, "", line, flags=re.IGNORECASE))
    disposal = tidy(" ".join(parts))
    return storage, disposal


# Section labels we know how to recognize in a vendor/competitor TDS, mapped
# to the field(s) they should pre-fill. Order matters — it's also the order
# we scan for heading boundaries in.
_TDS_HEADING_MAP = [
    (r"features?", "features"),
    (r"applications?", "applications"),
    (r"substrates?", "substrates"),
    (r"technical\s+data|typical\s+properties", "tech_data"),
    (r"packaging", "packaging"),
    (r"surface\s+preparation", "Surface Preparation"),
    (r"application\s+instructions?", "Application Instructions"),
    (r"clean\s*-?\s*up(\s+information)?", "Clean Up Information"),
    (r"storage\s*(&|and)\s*disposal", "Storage & Disposal"),
]


def extract_tds_fields(pdf_bytes):
    """Best-effort heuristic pull of common fields from a vendor/current TDS.

    This is a rough text-position split on recognized section headings —
    it will miss or mis-split anything that doesn't follow a fairly
    standard TDS layout. It is only ever used to PRE-FILL the editable
    form fields below (never to silently build a product JSON) — review
    and correct every field it touches before generating.
    """
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    # Find every heading occurrence (as its own line) with its position.
    found = []
    for pattern, key in _TDS_HEADING_MAP:
        for m in re.finditer(rf"\n\s*{pattern}\s*:?\s*\n", full_text, re.IGNORECASE):
            found.append((m.start(), m.end(), key))
    found.sort(key=lambda x: x[0])

    sections = {}
    for i, (start, end, key) in enumerate(found):
        next_start = found[i + 1][0] if i + 1 < len(found) else len(full_text)
        sections[key] = full_text[end:next_start].strip()

    result = {}
    if found:
        intro_text = full_text[:found[0][0]].strip()
        # Drop an obvious doc title / SKU line if present on its own first line.
        intro_lines = [l for l in intro_text.splitlines() if l.strip()]
        if intro_lines and len(intro_lines) > 1 and len(intro_lines[0]) < 40:
            intro_lines = intro_lines[1:]
        result["intro"] = "\n".join(intro_lines).strip()

    for key in ("features", "applications", "substrates", "packaging"):
        if key in sections:
            result[key] = lines_to_list(sections[key])

    if "tech_data" in sections:
        rows = []
        for line in sections["tech_data"].splitlines():
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"\s{2,}|\t|:\s", line, maxsplit=1)
            if len(parts) == 2:
                rows.append([parts[0].strip(), parts[1].strip()])
        if rows:
            result["tech_data"] = rows

    left_section_titles = ["Surface Preparation", "Application Instructions", "Clean Up Information", "Storage & Disposal"]
    left_sections = []
    for title in left_section_titles:
        if title in sections and sections[title]:
            paragraphs = [p.strip() for p in sections[title].split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [sections[title]]
            left_sections.append({"title": title, "paragraphs": paragraphs})
    if left_sections:
        result["left_sections"] = left_sections

    return result


DEFAULT_SECTIONS = [
    "Surface Preparation",
    "Application Instructions",
    "Clean Up Information",
    "Storage & Disposal",
]

st.caption(
    "Generates the real two-page Technical Data Sheet template (verified font, "
    "colors, watermark and footer placement against the shipped catalog) from a "
    "simple form instead of hand-edited JSON."
)

# ---------------------------------------------------------------------------
# Start from: a new TDS, or edit an existing one. Existing TDSs come from the
# approved master sheet (data/tds.csv in the product-data repo); if the master
# can't be reached, it falls back to the product JSON files in products/.
# ---------------------------------------------------------------------------
_COLUMN_TO_SECTION = {v: k for k, v in _SECTION_TO_COLUMN.items()}


@st.cache_data(ttl=300, show_spinner="Loading TDS list from the master sheet...")
def load_master_tds():
    import master_repo
    return master_repo.read_master("tds")


def _split_lines(text):
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def _infer_product_type(row):
    pkg = (row.get("Packaging") or "").lower()
    if (row.get("Brand Line") or "").upper() == "TAPE" or "roll" in pkg:
        return "tape"
    if any(w in pkg for w in ("cartridge", "sausage", "tube")):
        return "cartridge"
    if "canister" in pkg or "cylinder" in pkg:
        return "canister"
    return "bulk"


def master_row_to_loaded(row):
    """Inverse of build_master_row: master row -> the builder's product JSON shape."""
    code = row.get("Product Code", "")
    local = PRODUCTS_DIR / f"{code}.json"
    data = json.loads(local.read_text()) if local.exists() else {}
    verticals_ = [v.lower() for v in list_verticals()]
    cat = (row.get("Category") or "").lower()
    tech = []
    for line in _split_lines(row.get("Technical Data Table")):
        p, _, v = line.partition(": ")
        tech.append([p.strip(), v.strip()])
    if code not in {"T205","T215","T220","C-T550","C-T553","C-T557","M-T815","M-T820","T-T246","T-T415","T-T420"}:
        tech = [[p_.replace(" (Forza Test Method)", "").replace("(Forza Test Method)", "").strip(), v_] for p_, v_ in tech]
    sections = []
    for col, title in _COLUMN_TO_SECTION.items():
        paras = _split_lines(row.get(col))
        if paras:
            sections.append({"title": title, "paragraphs": paras})
    order = ["Surface Preparation", "Application Instructions", "Clean Up Information", "Storage & Disposal"]
    sections.sort(key=lambda s_: order.index(s_["title"]))
    data.update({
        "sku": code,
        "product_name": row.get("TDS Title") or row.get("Product Type") or data.get("product_name", ""),
        "intro": row.get("Description", ""),
        "features": _split_lines(row.get("Features")),
        "applications_lead": row.get("Applications Intro", ""),
        "applications": _split_lines(row.get("Applications")),
        "substrates_lead": row.get("Substrates Intro", ""),
        "substrates": _split_lines(row.get("Substrates")),
        "tech_data": tech,
        "packaging": _split_lines(row.get("Packaging")),
        "left_sections": sections,
    })
    if cat in verticals_:
        data["vertical"] = cat
    brand_ = (row.get("Brand Line") or "").lower()
    if brand_:
        data["brand"] = brand_
    data.setdefault("product_type", _infer_product_type(row))
    eq = _split_lines(row.get("Recommended Equipment"))
    if eq:
        data["recommended_equipment"] = eq
    prec = row.get("Precautionary Information")
    if prec:
        data["precautionary"] = {**(data.get("precautionary") or {}), "confirmed": True, "text": prec}
    return data


start_mode = st.radio(
    "What would you like to do?",
    ["Create a new TDS", "Edit an existing TDS"],
    horizontal=True,
)

loaded = {}
if start_mode == "Edit an existing TDS":
    master_rows, master_err = [], None
    try:
        master_rows = load_master_tds()
    except Exception as e:
        master_err = str(e)
    if master_rows:
        by_code = {r["Product Code"]: r for r in master_rows if r.get("Product Code")}
        label = lambda c: f"{c} - {by_code[c].get('TDS Title') or by_code[c].get('Product Type', '')}"
        pick = st.selectbox("Select a TDS from the master sheet", sorted(by_code), format_func=label)
        loaded = master_row_to_loaded(by_code[pick])
        st.caption(f"Loaded {pick} from the master sheet. Edit anything below, then generate the PDF or save it as a draft.")
    else:
        if master_err:
            st.warning(f"Couldn't reach the master sheet ({master_err}). Showing the products saved in this app instead.")
        local_products = list_products()
        if local_products:
            pick = st.selectbox("Select a saved product", local_products)
            loaded = json.loads((PRODUCTS_DIR / f"{pick}.json").read_text())
        else:
            st.info("No saved products found. Switch to 'Create a new TDS'.")

# ---------------------------------------------------------------------------
# Product type — outside the form so picking it immediately reveals the
# right conditional fields below (Clean Up Info is always available for
# tape; Recommended Equipment is canister-only; Bead Chart is
# cartridge/MS-only). See RULES.md section 12.
# ---------------------------------------------------------------------------
st.subheader("Product type")
PRODUCT_TYPE_LABELS = ["Tape", "Canister", "Pail / Drum / Tote (bulk)", "MS / Cartridge Sealant"]
_PRODUCT_TYPE_TO_LABEL = {"tape": "Tape", "canister": "Canister", "bulk": "Pail / Drum / Tote (bulk)", "cartridge": "MS / Cartridge Sealant"}
_LABEL_TO_PRODUCT_TYPE = {v: k for k, v in _PRODUCT_TYPE_TO_LABEL.items()}
default_product_type_label = _PRODUCT_TYPE_TO_LABEL.get(loaded.get("product_type", "tape"), "Tape")
product_type_label = st.selectbox(
    "Determines which optional sections/tables apply",
    PRODUCT_TYPE_LABELS,
    index=PRODUCT_TYPE_LABELS.index(default_product_type_label),
)
st.caption(
    "Tape → includes a Clean Up Information section. Canister and Pail / Drum / Tote → add a "
    "Recommended Equipment section on page 1. MS / Cartridge Sealant → adds a Bead Chart table on "
    "page 2, right after Application Instructions."
)
is_tape = product_type_label == "Tape"

# ---------------------------------------------------------------------------
# Vendor/current TDS upload — pre-fills the form fields below from an
# existing TDS (yours or a competitor's) so you're editing/correcting
# instead of typing from scratch. Outside the form so the pre-fill is
# visible before you start editing. Never silently builds the product JSON
# itself — it only ever changes what shows up as the default text in the
# fields you'd be filling in anyway.
# ---------------------------------------------------------------------------
st.subheader("Pre-fill from a current or vendor TDS (optional)")
tds_upload = st.file_uploader(
    "Upload a TDS (PDF) — yours or a vendor/competitor's — to pre-fill the fields below",
    type=["pdf"],
    key="tds_uploader",
)
if tds_upload is not None:
    if st.session_state.get("_tds_uploader_name") != tds_upload.name:
        st.session_state["_tds_extracted_fields"] = extract_tds_fields(tds_upload.getvalue())
        try:
            st.session_state["_tds_photo"] = extract_product_photo(tds_upload.getvalue())
        except Exception:
            st.session_state["_tds_photo"] = None
        st.session_state["_tds_uploader_name"] = tds_upload.name
    st.caption(
        "Pre-filled the fields below where it could find a recognizable section — a "
        "rough, best-effort text pull. Review and correct everything before generating; "
        "nothing here is sourced or verified automatically."
    )

# A freshly-loaded existing product JSON ("Edit existing: ...") always wins
# over a vendor TDS pull; the vendor TDS only fills in for a new product.
_tds_extracted = st.session_state.get("_tds_extracted_fields", {}) if tds_upload is not None else {}
loaded = {**_tds_extracted, **loaded}
tds_photo = st.session_state.get("_tds_photo") if tds_upload is not None else None

# Widget state key namespace. Streamlit keeps a keyed widget's value for the
# life of the session, so without this the Page 2 boxes (Surface Preparation,
# Application Instructions, ...) stayed blank after picking an existing
# product. Every time the loaded product or uploaded TDS changes, the
# namespace changes and those boxes pick up the new product's text.
import hashlib
_ns_src = f"{start_mode}|{loaded.get('sku', '')}|{tds_upload.name if tds_upload is not None else ''}"
ns = hashlib.md5(_ns_src.encode()).hexdigest()[:8]


def sec_key(title):
    return f"section_{title}__{ns}"


# ---------------------------------------------------------------------------
# SDS upload — also outside the form so the extracted text appears
# immediately for review. Nothing here is auto-confirmed; the user must
# tick the checkbox after reviewing it before it can be used below. Tapes
# don't require an SDS/hazard statements at all — the tape-category
# non-hazardous boilerplate (see RULES.md section 10) already covers them —
# so this is disabled while "Tape" is the selected product type.
# ---------------------------------------------------------------------------
_last_type = st.session_state.get("_last_product_type")
_sd_key = sec_key("Storage & Disposal")
_loaded_has_storage = any(sec.get("title") == "Storage & Disposal" for sec in loaded.get("left_sections", []))
if _last_type is None:
    if is_tape and _sd_key not in st.session_state and not _loaded_has_storage:
        st.session_state[_sd_key] = TAPE_STORAGE_BOILERPLATE
elif _last_type != product_type_label:
    if is_tape:
        st.session_state[_sd_key] = TAPE_STORAGE_BOILERPLATE
    elif _last_type == "Tape" and st.session_state.get(_sd_key) == TAPE_STORAGE_BOILERPLATE:
        st.session_state[_sd_key] = ""
st.session_state["_last_product_type"] = product_type_label

st.subheader("Storage & Disposal from the SDS" + (" (not needed for tape)" if is_tape else " (required)"))
if is_tape:
    st.caption(
        "Tape products don't have an SDS, so Storage & Disposal below uses the standard tape language "
        "(edit the shelf life if it differs). Switch the Product type above if this product does have an SDS."
    )
    sds_upload = None
else:
    st.caption(
        "This product needs an SDS. Upload it and the Storage & Disposal section below is filled in word for word "
        "from SDS Section 7 (storage) and Section 13 (disposal), so the TDS and SDS always match. "
        "Hazard statements are not pulled: every TDS uses the standard \"refer to the label and SDS\" language."
    )
    sds_upload = st.file_uploader(
        "Upload the product's SDS (PDF)",
        type=["pdf"],
    )
if sds_upload is not None:
    if st.session_state.get("_sds_uploader_name") != sds_upload.name:
        _storage, _disposal = extract_storage_disposal(sds_upload.getvalue())
        st.session_state["_sds_uploader_name"] = sds_upload.name
        st.session_state["_sds_storage"] = _storage
        st.session_state["_sds_disposal"] = _disposal
        st.session_state[sec_key("Storage & Disposal")] = " ".join(x for x in (_storage, _disposal) if x)
    if not st.session_state.get("_sds_storage"):
        st.warning("Couldn't find the storage wording in SDS Section 7 - add it by hand in Storage & Disposal below.")
    if not st.session_state.get("_sds_disposal"):
        st.warning("Couldn't find SDS Section 13 (Disposal Considerations) - add it by hand in Storage & Disposal below.")
    if st.session_state.get("_sds_storage") or st.session_state.get("_sds_disposal"):
        st.success(f"Storage & Disposal filled from {sds_upload.name} (verbatim). Only edit it if the SDS itself changes.")

# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------
with st.form("tds_form"):
    st.subheader("Basics")
    brands = list_brands()
    _pref = [b_ for b_ in ("bond", "seal", "tape") if b_ in brands]
    brands = _pref + [b_ for b_ in brands if b_ not in _pref]
    default_brand = loaded.get("brand") or ("tape" if is_tape else "bond")
    if default_brand not in brands:
        st.warning(
            f"The logo for Forza{default_brand.upper()} (assets/logo_{default_brand}.png) is missing from "
            "the app's assets folder, so a different logo is selected. Upload that logo file to GitHub."
        )
    brand = st.selectbox(
        "Brand line (picks the logo at the top of the sheet: ForzaBOND, ForzaSEAL or ForzaTAPE)",
        brands,
        index=brands.index(default_brand) if default_brand in brands else 0,
        format_func=lambda b: f"Forza{b.upper()}",
    )
    c1, c2 = st.columns(2)
    with c1:
        sku = st.text_input("SKU", value=loaded.get("sku", ""))
    with c2:
        verticals = list_verticals()
        default_vertical = loaded.get("vertical", "insulation")
        vertical = st.selectbox(
            "Vertical (picks the header color)",
            verticals,
            index=verticals.index(default_vertical) if default_vertical in verticals else 0,
            format_func=lambda v: v[:1].upper() + v[1:],
        )

    product_name = st.text_input("Product name", value=loaded.get("product_name", ""))
    intro = st.text_area("Intro / description", value=loaded.get("intro", ""), height=100)

    st.subheader("Features & Applications")
    features = st.text_area(
        "Features (one per line)",
        value=list_to_lines(loaded.get("features")),
        height=140,
    )
    applications_lead = st.text_input(
        "Applications lead-in sentence",
        value=loaded.get("applications_lead", "Product is specifically designed for:"),
    )
    applications = st.text_area(
        "Applications (one per line)",
        value=list_to_lines(loaded.get("applications")),
        height=120,
    )

    st.subheader("Substrates")
    include_substrates = st.checkbox(
        "Include a Substrates section",
        value=bool(loaded.get("substrates")),
    )
    substrates_lead = st.text_input(
        "Substrates lead-in sentence",
        value=loaded.get("substrates_lead", "Product is used to bond:"),
        disabled=not include_substrates,
    )
    substrates = st.text_area(
        "Substrates (one per line)",
        value=list_to_lines(loaded.get("substrates")),
        height=100,
        disabled=not include_substrates,
    )

    st.subheader("Technical Data")
    st.caption("Properties/Value only — the real shipped catalog has no Test Method column.")
    default_tech_rows = [{"Property": r[0], "Value": r[-1]} for r in loaded.get("tech_data", [])] or [
        {"Property": "", "Value": ""}
    ]
    tech_data_rows = st.data_editor(
        default_tech_rows,
        num_rows="dynamic",
        use_container_width=True,
        key=f"tech_data_editor__{ns}",
    )

    st.subheader("Packaging")
    packaging = st.text_area(
        "Packaging sizes (one per line)",
        value=list_to_lines(loaded.get("packaging")),
        height=80,
    )

    recommended_equipment_text = ""
    if product_type_label in ("Canister", "Pail / Drum / Tote (bulk)"):
        st.subheader("Recommended Equipment")
        recommended_equipment_text = st.text_area(
            "Recommended equipment (one per line) — appears on page 1, right after Packaging",
            value=list_to_lines(loaded.get("recommended_equipment")),
            height=100,
        )
    elif product_type_label == "MS / Cartridge Sealant":
        st.subheader("Bead Chart")
        st.caption(
            "Standard chart, added automatically on page 2 after Application Instructions. It is the same "
            "for every product (1 fl oz of product divided by the bead cross-section), so there is nothing to fill in."
        )
        st.dataframe(
            [{"Bead Width": w, "Linear Yield / oz": y} for w, y in standard_bead_chart()],
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Page 2 sections")
    st.caption(
        "ForzaTAPE products include Clean Up Information between Application "
        "Instructions and Storage & Disposal — leave a section blank to omit it."
    )
    loaded_sections = {s["title"]: "\n\n".join(s["paragraphs"]) for s in loaded.get("left_sections", [])}
    section_texts = {}
    for title in DEFAULT_SECTIONS:
        _default = loaded_sections.get(title, "")
        if title == "Storage & Disposal" and is_tape and not _default:
            _default = TAPE_STORAGE_BOILERPLATE
        _kw = {} if sec_key(title) in st.session_state else {"value": _default}
        section_texts[title] = st.text_area(
            title + " (blank lines separate paragraphs)",
            height=200 if title == "Storage & Disposal" else 100,
            key=sec_key(title),
            **_kw,
        )

    st.subheader("Precautionary Information")
    precaution_options = [
        "Requires SDS referral",
        "Non-Hazardous under GHS (standard tape-category boilerplate)",
        "Not yet confirmed (renders as a flagged placeholder)",
        "Custom text",
    ]
    precaution_choice = st.radio("Standard language", precaution_options, index=0)
    custom_precaution_text = ""
    if precaution_choice == "Custom text":
        custom_precaution_text = st.text_area(
            "Custom precautionary text",
            value=loaded.get("precautionary", {}).get("text", ""),
        )

    st.subheader("Product photo")
    photo_options = ["None", "Upload new", "Use existing asset"]
    if tds_photo:
        photo_options = ["Photo from the uploaded TDS"] + photo_options
        st.image(tds_photo, caption="Photo found on the uploaded TDS", width=170)
    else:
        st.caption(
            "To carry over a product's current picture, upload its existing TDS in the pre-fill box near the top "
            "of the page: the photo on it is pulled automatically."
        )
    photo_mode = st.radio("Header photo", photo_options, horizontal=True)
    uploaded_photo = None
    existing_photo_choice = None
    if photo_mode == "Upload new":
        uploaded_photo = st.file_uploader("Upload a product photo (PNG, transparent background)", type=["png"])
    elif photo_mode == "Use existing asset":
        photos = list_existing_photos()
        existing_photo_choice = st.selectbox("Existing photo", photos) if photos else None

    submitted = st.form_submit_button("Generate TDS PDF", type="primary")
    save_clicked = st.form_submit_button("Save as draft")

# ---------------------------------------------------------------------------
# Handle submission
# ---------------------------------------------------------------------------
if submitted or save_clicked:
    if not sku.strip():
        st.error("SKU is required.")
        st.stop()
    _has_saved_storage = any(sec.get("title") == "Storage & Disposal" for sec in loaded.get("left_sections", []))
    if not is_tape and sds_upload is None and not _has_saved_storage:
        st.error(
            "This product needs an SDS. Upload it above so Storage & Disposal matches the SDS word for word, "
            "then generate or save again."
        )
        st.stop()

    # Resolve the photo filename, saving an uploaded file into assets/ first.
    photo_filename = None
    if photo_mode == "Photo from the uploaded TDS" and tds_photo:
        photo_filename = f"{sku.strip()}.png"
        (ASSETS_DIR / photo_filename).write_bytes(tds_photo)
    elif photo_mode == "Upload new" and uploaded_photo is not None:
        photo_filename = f"{sku.strip()}.png"
        (ASSETS_DIR / photo_filename).write_bytes(uploaded_photo.getvalue())
    elif photo_mode == "Use existing asset" and existing_photo_choice:
        photo_filename = existing_photo_choice

    if precaution_choice == "Requires SDS referral":
        precautionary = {"confirmed": True, "text": PRECAUTION_SDS_REFERRAL}
    elif precaution_choice.startswith("Non-Hazardous"):
        precautionary = {"confirmed": True, "text": PRECAUTION_NON_HAZARDOUS}
    elif precaution_choice == "Custom text":
        precautionary = {"confirmed": True, "text": custom_precaution_text.strip()}
    else:
        precautionary = {
            "confirmed": False,
            "text": "GHS classification to be confirmed for this SKU",
        }

    left_sections = [
        {"title": title, "paragraphs": [p.strip() for p in text.split("\n\n") if p.strip()]}
        for title, text in section_texts.items()
        if text.strip()
    ]

    tech_data = [
        [row.get("Property", "").strip(), row.get("Value", "").strip()]
        for row in tech_data_rows
        if row.get("Property", "").strip()
    ]

    recommended_equipment = (
        lines_to_list(recommended_equipment_text)
        if product_type_label in ("Canister", "Pail / Drum / Tote (bulk)") else None
    )
    bead_chart = standard_bead_chart() if product_type_label == "MS / Cartridge Sealant" else None

    data = {
        "sku": sku.strip(),
        "vertical": vertical,
        "brand": brand,
        "product_type": _LABEL_TO_PRODUCT_TYPE[product_type_label],
        "product_name": product_name.strip(),
        "intro": intro.strip(),
        "features": lines_to_list(features),
        "applications_lead": applications_lead.strip(),
        "applications": lines_to_list(applications),
        "substrates_lead": substrates_lead.strip() if include_substrates else None,
        "substrates": lines_to_list(substrates) if include_substrates else None,
        "tech_data": tech_data,
        "packaging": lines_to_list(packaging),
        "recommended_equipment": recommended_equipment,
        "bead_chart": bead_chart,
        "left_sections": left_sections,
        "precautionary": precautionary,
        "photo": photo_filename,
    }

    if save_clicked and not submitted:
        if not data["product_name"]:
            st.error("Product name is required to save a draft (it becomes the TDS title).")
            st.stop()
        status, err = save_tds_draft(data)
        if err:
            st.error(f"Could not save draft: {err}")
        else:
            st.success(f"Draft {status} for {data['sku']}. It is waiting for the owner's approval.")
        st.stop()

    product_path = PRODUCTS_DIR / f"{sku.strip()}.json"
    product_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    try:
        with st.spinner("Rendering PDF..."):
            out_path = build(product_path)
    except SystemExit as e:
        st.error(str(e))
        st.stop()
    except Exception as e:
        st.error(f"Build failed: {e}")
        st.stop()

    _layout = getattr(build, "last_layout", "standard")
    st.success(
        f"Built {out_path.name} — verified 2 pages at true US Letter "
        + ("(standard spacing)." if _layout == "standard" else "(compact spacing, because standard spacing ran past 2 pages).")
    )

    # Preview both pages.
    import pymupdf
    doc = pymupdf.open(str(out_path))
    preview_cols = st.columns(len(doc))
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3))
        preview_cols[i].image(pix.tobytes("png"), caption=f"Page {i + 1}", use_container_width=True)

    st.download_button(
        "Download PDF",
        data=out_path.read_bytes(),
        file_name=out_path.name,
        mime="application/pdf",
        type="primary",
    )

st.divider()
st.caption(
    "Every product JSON saved here is reusable from the command line too: "
    "`python3 build/generate_tds.py products/<SKU>.json`."
)
