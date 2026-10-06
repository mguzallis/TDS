# Forza TDS Builder

A reusable pipeline for generating two-page Technical Data Sheet PDFs in the
new Forza catalog template (the one piloted on T310, M-OS764, and IC947).

Unlike the mockup files from earlier sessions, this is **data-driven**: you
describe a product in a JSON file, and the script renders it into the real
template using the actual brand assets (logo, header graphic, eagle
watermark) pulled from a finished catalog PDF.

**See `RULES.md` for the full consolidated spec** — every exact measurement,
color, font size, and content rule we derived by forensically comparing
against real shipped catalog PDFs (plus the product-type-specific section
rules below). If you're ever unsure why a value is what it is, check there
first before re-deriving it from scratch.

## Folder layout

```
Forza TDS Builder/
  assets/            Real brand assets: logo.png, header_bg.png, watermark.png, qr.png
  build/             The template + render script
    template.html.j2   Jinja2 HTML template (2 pages, English only)
    _footer.html.j2     Shared footer partial
    generate_tds.py     Run this to build a PDF from a product JSON
  products/          One JSON file per product
    _example.json      Annotated template — copy this to start a new SKU
    T461.json          First product built this way (Insulation transfer tape)
  output/            Generated PDFs and intermediate HTML land here
```

## Requirements (one-time setup)

```
pip3 install jinja2 playwright qrcode[pil] pymupdf
playwright install chromium
```

## Building a TDS

```
cd "Forza TDS Builder"
python3 build/generate_tds.py products/T461.json
```

Output goes to `output/T461_TDS.pdf`. Pass `--out some/path.pdf` to change
the destination, or `--photo filename.png` to drop a real product photo
into the header (put the photo in `assets/` first).

The script hard-fails if the rendered PDF isn't exactly 2 pages at true
US Letter (8.5x11in) — it won't silently hand you a 3-page or oddly-sized
file. If it fails on page count, that's the signal to turn on
`"compact_table": true` (see below) or trim copy.

## Adding a new product

1. Copy `products/_example.json` to `products/<SKU>.json`.
2. Fill it in from the real TDS/SDS data. Keep the sourcing discipline:
   - `tech_data` test method column: `"Forza Test Method"` only for properties
     that are actually lab-tested; `"N/A"` for descriptive/categorical ones
     (Appearance, Shelf Life, Color, etc.); never invent a named standard
     (ASTM or otherwise) unless Mike Glenn/R&D has confirmed one.
   - `precautionary`: use the two standard sentences verbatim rather than
     re-wording per product — they're in `build/generate_tds.py` as
     `PRECAUTION_SDS_REFERRAL` ("For complete hazard, handling, and
     precautionary information, refer to the product label and Safety Data
     Sheet (SDS) before use.") and `PRECAUTION_NON_HAZARDOUS` ("This product
     is classified as Non-Hazardous under GHS."). Set `confirmed: false`
     until the classification for that specific SKU is actually confirmed —
     it renders as a flagged orange placeholder instead of asserting one.
   - `substrate_table`: only for structural bonding products; leave `null`
     for tapes/sealants where overlap shear doesn't apply. Keep the title
     short enough to stay on one line at full heading size (shorten the
     title text itself, e.g. "Performance Characteristics" with "Typical
     Overlap Shear Strength" as the subtitle below it — don't shrink the
     heading font to force a fit; that reads as inconsistent next to the
     other section headers).
   - `substrates`: leave `null` to omit the section entirely rather than
     invent substrates the product page doesn't support.
   - `vertical`: lowercase name matching a file in `assets/headers/`
     (insulation, industrial, transportation, marine, construction). Picks
     the correct header color for that product's market segment.
3. Run the build script — it verifies the 2-page/Letter-size check itself.

## Notes on the assets

`logo.png`, `watermark.png`, `flag.png`, and the files in `headers/` were
extracted directly from your actual shipped catalog PDFs in
`~/Downloads/2026 TDS Update/English/` — not redrawn approximations. The
header background image is vertical-specific (see below); every other
asset is shared across verticals. Fonts (`fonts/Kallisto_Heavy.otf`,
`fonts/kallisto.black.ttf`) came from the font files already sitting in
`~/Downloads/`. There's no generic product photo yet; each SKU's header
photo (if any) should be the real product shot, not reused from a
different SKU's material/color.

### Header depends on industry/vertical

Each vertical has its own header gradient color — confirmed by comparing
real catalog files side by side:

| Vertical | Color | Source file used |
|---|---|---|
| Insulation | Purple → magenta/pink | R-T600 |
| Industrial | Navy → orange/red | T310 |
| Transportation | Navy → red | T-T415 |
| Marine | Navy → teal/green | M-T815 |
| Construction | Navy → amber/gold | C-T500 |

Set `"vertical"` in the product JSON (lowercase, matching a filename in
`assets/headers/`) to pick the right one. Composites appears to also swap
the wordmark to "ForzaSEAL" for some products rather than "ForzaTAPE" —
not yet handled here since it depends on product line, not just vertical;
flag it if you need a Composites/Tiltup-BlueHorn/other vertical added, or
if a product's actual brand line (BOND/TAPE/SEAL/COAT) differs from what
the logo file shows.

### What the mockup round got right vs. what's actually in production

Earlier mockup work (IC947, M-OS764, T310) piloted a fancier 3-column
Technical Data table (Properties/Test Method/Value, zebra-striped) and a
substrate overlap-shear table. Comparing against your actual shipped
177-product catalog: **that enhancement was never adopted catalog-wide.**
Every real shipped file (including the real T310, not just the mockup)
uses the simpler 2-column Properties/Value table as solid navy bars, no
Test Method column, no substrate-shear table. This builder now matches
what's actually shipped. If you want the enhanced format rolled out
instead, that's a decision to make deliberately, not something to guess at.

## Running it as an app

```
pip install -r requirements.txt
playwright install chromium      # one-time
streamlit run app.py
```

This gives you a form over the same pipeline above — fill it in, hit
Generate, preview both pages, download the PDF. It also writes/updates the
product's JSON file in `products/`, so the form and the command-line tool
stay interchangeable. When ready to share this with others, the plan is to
follow the same pattern as the SDS Formatter app: a private GitHub repo,
deployed on Streamlit Community Cloud, alongside SDS Generator, SDS
Formatter, and Label Generator on the Forza App Hub.

### Product type drives which sections appear

The app's "Product type" selector (Tape / Canister / MS-Cartridge Sealant)
changes which optional sections are available — see `RULES.md` section 12
for the full detail, summarized here:

- **Tape** — standard `left_sections` sequence including a "Clean Up
  Information" section between Application Instructions and Storage &
  Disposal.
- **Canister** — adds a "Recommended Equipment" bullet list on page 1,
  right column, right after Packaging (confirmed against IC947).
- **MS / Cartridge Sealant** — adds a "Bead Chart" table (Bead Width /
  Linear Yield) on page 2, left column, right after Application
  Instructions (confirmed against M-OS764).

### Pre-filling from a current or vendor TDS

The app can also take a TDS PDF upload — your own current sheet, or a
vendor/competitor's — and heuristically pull common fields (intro,
features, applications, substrates, technical data, packaging, and the
page-2 sections) by splitting the text on recognized section headings.
This only ever changes the **default values shown in the form fields
below** — it never writes a product JSON directly — so you're always
editing/correcting pre-filled text rather than typing from scratch, and
nothing is treated as confirmed just because it was extracted. It's rough
(a plain text-position split, not real layout parsing), so expect to clean
it up, especially the tech_data split and the intro line.

### Pulling hazard/precautionary statements from an SDS

The app can take an SDS PDF upload and heuristically pull candidate
Hazard Statement / Precautionary Statement text (a plain text search for
those section labels). This is deliberately **never auto-confirmed** —
the extracted text lands in an editable box, and only becomes usable in
the product's `precautionary.statements` once you've reviewed it against
the actual SDS and ticked the confirmation checkbox. Treat the extraction
as a rough first draft, not a source of truth — SDS formatting varies
enough that it can miss text or grab too much.

This upload is **disabled whenever Product type is set to Tape** —
ForzaTAPE products don't carry hazard statements at all; they default to
the confirmed non-hazardous boilerplate (see RULES.md section 10), so
there's nothing for an SDS upload to usefully extract there.

## Why this exists

Earlier TDS mockup work (IC947, M-OS764, T310, and a first pass at T461)
was done in a cloud session's temporary workspace, which does not persist
between sessions — the pipeline and assets were lost when that container
recycled. This folder lives on your Mac instead, so it survives across
sessions. Hand a Claude session this folder (or just say "use the Forza
TDS Builder in Documents") to pick up where you left off.
