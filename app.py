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

st.set_page_config(page_title="Forza TDS Generator", page_icon="📄", layout="wide")


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


def extract_candidate_statements(pdf_bytes):
    """Heuristic pull of Hazard/Precautionary statement text from an SDS PDF.

    This is intentionally rough — it searches for the section labels and
    grabs the text up to the next likely section break. It is NEVER
    auto-confirmed: the caller always surfaces this in an editable field
    for a human to review against the actual SDS before it's used.
    """
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    stop_patterns = [
        r"\n\s*section\s*\d",
        r"\n\s*\d+\.\d+\s+[A-Z]",
        r"\n\s*(other hazards|classification|precautionary statements?|hazard statements?)\s*:?\s*\n",
    ]

    def grab(label_pattern):
        m = re.search(label_pattern, full_text, re.IGNORECASE)
        if not m:
            return ""
        rest = full_text[m.end():]
        stop_idx = len(rest)
        for sp in stop_patterns:
            sm = re.search(sp, rest, re.IGNORECASE)
            if sm and 0 < sm.start() < stop_idx:
                stop_idx = sm.start()
        return rest[:stop_idx].strip()

    hazard = grab(r"hazard\s+statements?\s*:?\s*\n?")
    precaution = grab(r"precautionary\s+statements?\s*:?\s*\n?")
    return "\n".join(x for x in [hazard, precaution] if x)


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

st.title("Forza TDS Generator")
st.caption(
    "Generates the real two-page Technical Data Sheet template (verified font, "
    "colors, watermark and footer placement against the shipped catalog) from a "
    "simple form instead of hand-edited JSON."
)

# ---------------------------------------------------------------------------
# Start from: new product, or load an existing one to edit
# ---------------------------------------------------------------------------
existing = list_products()
col_a, col_b = st.columns([2, 1])
with col_a:
    choice = st.selectbox(
        "Start from",
        ["New product"] + [f"Edit existing: {sku}" for sku in existing],
    )

loaded = {}
if choice != "New product":
    sku_to_load = choice.replace("Edit existing: ", "")
    loaded = json.loads((PRODUCTS_DIR / f"{sku_to_load}.json").read_text())

# ---------------------------------------------------------------------------
# Product type — outside the form so picking it immediately reveals the
# right conditional fields below (Clean Up Info is always available for
# tape; Recommended Equipment is canister-only; Bead Chart is
# cartridge/MS-only). See RULES.md section 12.
# ---------------------------------------------------------------------------
st.subheader("Product type")
PRODUCT_TYPE_LABELS = ["Tape", "Canister", "MS / Cartridge Sealant"]
_PRODUCT_TYPE_TO_LABEL = {"tape": "Tape", "canister": "Canister", "cartridge": "MS / Cartridge Sealant"}
_LABEL_TO_PRODUCT_TYPE = {v: k for k, v in _PRODUCT_TYPE_TO_LABEL.items()}
default_product_type_label = _PRODUCT_TYPE_TO_LABEL.get(loaded.get("product_type", "tape"), "Tape")
product_type_label = st.selectbox(
    "Determines which optional sections/tables apply",
    PRODUCT_TYPE_LABELS,
    index=PRODUCT_TYPE_LABELS.index(default_product_type_label),
)
st.caption(
    "Tape → includes a Clean Up Information section. Canister → adds a Recommended "
    "Equipment section on page 1. MS / Cartridge Sealant → adds a Bead Chart table on "
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

# ---------------------------------------------------------------------------
# SDS upload — also outside the form so the extracted text appears
# immediately for review. Nothing here is auto-confirmed; the user must
# tick the checkbox after reviewing it before it can be used below. Tapes
# don't require an SDS/hazard statements at all — the tape-category
# non-hazardous boilerplate (see RULES.md section 10) already covers them —
# so this is disabled while "Tape" is the selected product type.
# ---------------------------------------------------------------------------
st.subheader("Extract hazard/precautionary statements from an SDS (optional)")
if is_tape:
    st.caption(
        "Not applicable for Tape — ForzaTAPE products default to the confirmed "
        "\"Non-Hazardous under GHS\" boilerplate and don't carry hazard statements. "
        "Switch Product type above if this product actually needs an SDS."
    )
sds_upload = st.file_uploader(
    "Upload the product's SDS (PDF) to pull candidate Hazard/Precautionary statements",
    type=["pdf"],
    disabled=is_tape,
)
if sds_upload is not None and not is_tape:
    if st.session_state.get("_sds_uploader_name") != sds_upload.name:
        st.session_state["_sds_extracted_text"] = extract_candidate_statements(sds_upload.getvalue())
        st.session_state["_sds_uploader_name"] = sds_upload.name
        st.session_state["_sds_confirmed"] = False

    st.text_area(
        "Extracted candidate text — this is a rough automated pull, review and correct "
        "it against the actual SDS before using it (one statement per line)",
        key="_sds_extracted_text",
        height=150,
    )
    st.checkbox(
        "I've reviewed this text against the SDS and confirm it's accurate",
        key="_sds_confirmed",
    )

# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------
with st.form("tds_form"):
    st.subheader("Basics")
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
        key="tech_data_editor",
    )

    st.subheader("Packaging")
    packaging = st.text_area(
        "Packaging sizes (one per line)",
        value=list_to_lines(loaded.get("packaging")),
        height=80,
    )

    recommended_equipment_text = ""
    bead_chart_rows = None
    if product_type_label == "Canister":
        st.subheader("Recommended Equipment")
        recommended_equipment_text = st.text_area(
            "Recommended equipment (one per line) — appears on page 1, right after Packaging",
            value=list_to_lines(loaded.get("recommended_equipment")),
            height=100,
        )
    elif product_type_label == "MS / Cartridge Sealant":
        st.subheader("Bead Chart")
        st.caption("Appears on page 2, right after Application Instructions.")
        default_bead_rows = [
            {"Bead Width": r[0], "Linear Yield / oz": r[1]} for r in loaded.get("bead_chart") or []
        ] or [{"Bead Width": "", "Linear Yield / oz": ""}]
        bead_chart_rows = st.data_editor(
            default_bead_rows,
            num_rows="dynamic",
            use_container_width=True,
            key="bead_chart_editor",
        )

    st.subheader("Page 2 sections")
    st.caption(
        "ForzaTAPE products include Clean Up Information between Application "
        "Instructions and Storage & Disposal — leave a section blank to omit it."
    )
    loaded_sections = {s["title"]: "\n\n".join(s["paragraphs"]) for s in loaded.get("left_sections", [])}
    section_texts = {}
    for title in DEFAULT_SECTIONS:
        section_texts[title] = st.text_area(
            title + " (blank lines separate paragraphs)",
            value=loaded_sections.get(title, ""),
            height=100,
            key=f"section_{title}",
        )

    st.subheader("Precautionary Information")
    precaution_options = [
        "Non-Hazardous under GHS (standard tape-category boilerplate)",
        "Requires SDS referral",
        "Not yet confirmed (renders as a flagged placeholder)",
        "Custom text",
    ]
    if st.session_state.get("_sds_confirmed") and not is_tape:
        precaution_options.insert(0, "Use reviewed SDS extract (shown above)")
    precaution_choice = st.radio("Standard language", precaution_options, index=0)
    custom_precaution_text = ""
    if precaution_choice == "Custom text":
        custom_precaution_text = st.text_area(
            "Custom precautionary text",
            value=loaded.get("precautionary", {}).get("text", ""),
        )

    st.subheader("Product photo")
    photo_mode = st.radio(
        "Header photo",
        ["None", "Upload new", "Use existing asset"],
        horizontal=True,
    )
    uploaded_photo = None
    existing_photo_choice = None
    if photo_mode == "Upload new":
        uploaded_photo = st.file_uploader("Upload a product photo (PNG, transparent background)", type=["png"])
    elif photo_mode == "Use existing asset":
        photos = list_existing_photos()
        existing_photo_choice = st.selectbox("Existing photo", photos) if photos else None

    submitted = st.form_submit_button("Generate TDS PDF", type="primary")

# ---------------------------------------------------------------------------
# Handle submission
# ---------------------------------------------------------------------------
if submitted:
    if not sku.strip():
        st.error("SKU is required.")
        st.stop()

    # Resolve the photo filename, saving an uploaded file into assets/ first.
    photo_filename = None
    if photo_mode == "Upload new" and uploaded_photo is not None:
        photo_filename = f"{sku.strip()}.png"
        (ASSETS_DIR / photo_filename).write_bytes(uploaded_photo.getvalue())
    elif photo_mode == "Use existing asset" and existing_photo_choice:
        photo_filename = existing_photo_choice

    if precaution_choice == "Use reviewed SDS extract (shown above)":
        precautionary = {
            "confirmed": True,
            "statements": lines_to_list(st.session_state.get("_sds_extracted_text", "")),
        }
    elif precaution_choice.startswith("Non-Hazardous"):
        precautionary = {"confirmed": True, "text": PRECAUTION_NON_HAZARDOUS}
    elif precaution_choice == "Requires SDS referral":
        precautionary = {"confirmed": True, "text": PRECAUTION_SDS_REFERRAL}
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
        lines_to_list(recommended_equipment_text) if product_type_label == "Canister" else None
    )
    bead_chart = None
    if product_type_label == "MS / Cartridge Sealant" and bead_chart_rows:
        bead_chart = [
            [row.get("Bead Width", "").strip(), row.get("Linear Yield / oz", "").strip()]
            for row in bead_chart_rows
            if row.get("Bead Width", "").strip()
        ]

    data = {
        "sku": sku.strip(),
        "vertical": vertical,
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

    st.success(f"Built {out_path.name} — verified 2 pages at true US Letter.")

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
