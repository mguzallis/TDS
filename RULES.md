# TDS Builder — Consolidated Rules Reference

This file exists so nothing we worked out across many rounds of forensic
comparison against the real shipped catalog gets lost again to context
limits. If you (future Claude, or Mike) are ever unsure why a value is
what it is, check here first — most of these were measured directly off
real production PDFs with pymupdf/PIL, not guessed.

Everything in this file is already implemented in `build/template.html.j2`
and `build/generate_tds.py` as of this writing. Treat this as the spec
those files must keep matching — if you change the template, check it
against this list, and if you deliberately change a rule, update it here
too.

## 1. Rendering pipeline / scale

- Playwright renders the HTML at a fixed viewport of **816×1056 CSS px**,
  and `page.pdf()` emits that as true **US Letter (612×792pt)**. That's a
  flat **0.75 pt per px** ratio across the whole page.
- Consequence (important, easy to forget): any CSS `font-size` written
  directly in **pt units** survives into the final PDF as that *exact*
  point size, regardless of the px↔pt viewport conversion. That's how we
  were able to match font sizes measured from real PDFs' embedded font
  data exactly — write the measured pt value straight into the CSS.
- Hard gate: `verify_two_pages()` in `generate_tds.py` `SystemExit`s if the
  rendered PDF is not exactly 2 pages at exactly 612.0×792.0 pt. Every
  build must pass this. If a build fails it, the fix is to shorten copy
  or use `compact_table`, never to change the page geometry.

## 2. Fonts

- **Kallisto** (900/black weight) — SKU number and product name ONLY.
  Nothing else uses it.
- **Poppins** (Regular 400 for body, Bold 700 for headings/labels) —
  everything else: doc label, section headings, bullets, intro, technical
  data table, packaging boxes, footer, disclaimers.
- Confirmed via `page.get_text("dict")` span-level font name + size on
  real shipped PDFs. Exact measured sizes (all now baked into the CSS as
  literal pt values):
  | Element | Font | Size |
  |---|---|---|
  | "TECHNICAL DATA SHEET" doc label | Poppins Bold | 16.2pt |
  | SKU number | Kallisto | 40.8pt |
  | Product name | Kallisto | 19.9pt |
  | Section headings (Features, Applications, etc.) | Poppins Bold | 15.1pt |
  | Body / intro / bullets | Poppins Regular | 8.1pt |
  | Technical Data header row (Properties/Value labels) | Poppins Bold | 7.2pt |
  | Technical Data value-bar text | Poppins Bold | 6.2pt (smaller than the header row — easy to get backwards) |
  | Packaging boxes | Poppins Bold | 7.2pt |

## 3. Colors

Two distinct navys are used — do not collapse them into one:

- `#173F66` (rgb 23,63,102) — heading/body text color (the darker one).
- `#2A4267` (rgb 42,66,103) — footer background AND Technical
  Data/Packaging/Bead Chart bar fill (the lighter, more saturated one).

Confirmed by direct PIL pixel sampling against real shipped PDFs. An
earlier round collapsed these into a single too-dark navy — that was wrong
and was caught by comparing crops side by side.

## 4. Watermark (eagle graphic)

- Placement is an exact embedded-image rect, confirmed **identical across
  every real file checked** (IC947, M-OS764, R-T600, and the T310 mock):
  PDF rect `(32.25, 151.5)` to `(579.75, 653.25)` pt on a 612×792pt page.
  Converted to our 816×1056 canvas: `left: 43px; top: 202px; width: 730px;
  height: 669px`.
- Rendered at **full opacity** — confirmed via the PDF's ExtGState
  (`/ca 1`). The image itself is already pale/faint in its source pixels.
  **Do not add extra CSS opacity on top of it** — that was a real bug
  (double-fading) in an earlier round, fixed by removing the CSS opacity
  rule entirely and trusting the image's own alpha.

## 5. Header product photo

- Confirmed against R-T600's embedded photo rect: `(331.5, -15.75)` to
  `(573.75, 225.75)` pt on a 612×792pt page → our canvas: `top: -21px;
  right: 51px; width: 323px; height: 322px; object-fit: contain`.
- The photo **bleeds above the header's top edge** into negative space and
  down into the body — this is intentional/matches production, not a bug.
- Roughly square, right-aligned with ~51px margin from the right edge.
- Each SKU's photo should be the real product shot for that SKU — never
  reuse a different SKU's photo.

## 6. Header vertical → color

Each vertical has its own header gradient, set via `"vertical"` in the
product JSON (lowercase, matches a file in `assets/headers/`):

| Vertical | Color | Source file used |
|---|---|---|
| Insulation | Purple → magenta/pink | R-T600 |
| Industrial | Navy → orange/red | T310 |
| Transportation | Navy → red | T-T415 |
| Marine | Navy → teal/green | M-T815 |
| Construction | Navy → amber/gold | C-T500 |

Composites may also swap the wordmark to "ForzaSEAL" for some products
instead of "ForzaTAPE" — not yet handled (depends on product line/brand,
not just vertical). Flag it if a Composites/other vertical or a
BOND/TAPE/SEAL/COAT brand mismatch needs handling.

## 7. Footer

- Background `#2A4267`, true height ~102pt (136px on our canvas) —
  confirmed across IC947, M-OS764, R-T600, and T310. An earlier round had
  it ~25% too short with the wrong, too-dark navy.
- Claim line ("PURPOSE-BUILT. PERFORMANCE. GUARANTEED STRENGTH."): 11pt
  Poppins Bold, centered, letter-spacing 1px.
- Contact info is **stacked**, not middot-joined on one line — two groups:
  phone / email / website on their own lines, a 6px gap, then address on
  its own lines below. Font size 8.1pt, line-height 1.25.
- Flag/USA badge: 188px wide. QR code: 88×88px. Both vertically centered
  against the contact block (`align-items: center` on `.bottom-row`).
  These sizes went *up* from earlier too-small/off-center attempts once the
  contact block was made more compact — getting the ratio right took a
  couple of rounds of direct crop-comparison against the real R-T600
  footer; don't shrink them again without re-checking against a reference.

## 8. Technical Data table

- **Two columns only: Properties / Value.** No "Test Method" column — an
  earlier mockup round (IC947/M-OS764/T310 mockups) piloted a 3-column
  zebra-striped version with Test Method; **that was never adopted
  catalog-wide**. Every real shipped file, including the real (non-mockup)
  T310, uses the simpler 2-column format. Do not reintroduce the 3-column
  version without an explicit decision to do so.
- Each row renders as its own separate rounded "bubble" (solid `#2A4267`
  bar, `border-radius: 3px`) with a visible gap between rows
  (`margin-bottom: 4px` on `.techdata-row`) — **not** one continuous bar
  with internal dividers. This was an explicit correction.
- Header row text 7.2pt, data row text 6.2pt (smaller — see §2).
- The same bubble/bar style (navy `#2A4267`, same two sizes) is reused for
  **Bead Chart** rows (see §11) and **Packaging** boxes.

## 9. Column width / layout discipline

- `.col-left` is 374px, `.col-right` is 345px (29px gap between).
- The **intro/description text is constrained to the left column width
  only** — it must not span the full page width.
- The **product name** is allowed to extend wider than the column grid
  (it sits in `.title-block`, which spans the full content width) — don't
  force-wrap it to column width.

## 10. Precautionary Information — tape-category boilerplate rule

- ForzaTAPE products **default to a CONFIRMED, non-flagged line**:
  `"This product is classified as Non-Hazardous under GHS."` — this is
  `PRECAUTION_NON_HAZARDOUS` in `generate_tds.py`. Do **not** render this
  as an orange "needs confirmation" placeholder for tape products — that
  was a real miscalibration caught and fixed this session. Only use the
  flagged placeholder (`confirmed: false`) when the classification for a
  *specific* SKU genuinely hasn't been confirmed yet.
- For products that actually carry GHS hazard classifications (typically
  canister/cartridge, not tape), use `precautionary.statements` — a list
  of individual hazard/precautionary sentences, each rendered as its own
  paragraph — instead of the single boilerplate sentence. See §12.
- The other standard sentence, `PRECAUTION_SDS_REFERRAL` ("For complete
  hazard, handling, and precautionary information, refer to the product
  label and Safety Data Sheet (SDS) before use."), is used verbatim where
  that's the appropriate referral — never reworded per product.

## 11. Tape-specific section: Clean Up Information

- ForzaTAPE technical data sheets include a **"Clean Up Information"**
  section on page 2, positioned between **Application Instructions** and
  **Storage & Disposal**. Confirmed via real reference PDFs. This is part
  of the standard tape `left_sections` sequence:
  Surface Preparation → Application Instructions → Clean Up Information →
  Storage & Disposal.

## 12. Product-type-specific sections (canister / MS-cartridge)

Different product "shapes" need different optional sections — this is the
newest layer of rules, added to support non-tape product types:

- **Canister products** (confirmed via IC947): include a **"Recommended
  Equipment"** section on **page 1**, in the right column, immediately
  after Packaging (before falling off into page 2). Template field:
  `recommended_equipment` (a plain bullet list).
- **MS/cartridge sealant products** (confirmed via M-OS764): include a
  **"Bead Chart"** section on **page 2**, left column, positioned
  immediately after **Application Instructions** and before **Clean Up
  Information** — i.e. the real M-OS764 ordering is Surface Prep →
  Application Instructions → Bead Chart → Clean Up Information → Storage &
  Disposal. Template field: `bead_chart`, a list of `[bead width, linear
  yield]` pairs, rendered in the same techdata-head/techdata-row bubble
  style as the main Technical Data table, with column headers "Bead Width"
  / "Linear Yield / oz".
- **Hazardous products** (canister/cartridge, as opposed to the
  non-hazardous tape default) typically need **multiple** precautionary
  statements rather than one boilerplate sentence — see
  `precautionary.statements` in §10.
- These three fields (`recommended_equipment`, `bead_chart`,
  `precautionary.statements`) are all optional/additive in the Jinja
  template — a plain tape product JSON that omits them renders exactly as
  before. Both the canister-shape and cartridge-shape paths have been
  smoke-tested end to end and pass the 2-page/Letter-size gate.
- Still to be wired up: an explicit "Product type" selector in the
  Streamlit app (Tape / Canister / MS-Cartridge Sealant) that reveals the
  right optional fields for the chosen type, rather than requiring the
  user to know which JSON fields apply to their product.

## 13. SDS upload (Storage & Disposal only) -- UPDATED Nov 10 2026

- Hazard/precautionary-statement extraction was REMOVED. Every TDS uses the
  standard boilerplate in Precautionary Information ("refer to the product
  label and Safety Data Sheet (SDS)"), so there is nothing to pull.
- The SDS upload (any product type, optional) now fills **Storage & Disposal**
  word for word from the SDS: the storage paragraph of SECTION 7 (Handling
  and Storage) plus the body of SECTION 13 (Disposal Considerations)
  (`extract_storage_disposal` in `app.py`). Only line breaks, page footers
  and the leading field labels ("Storage:", "Waste treatment methods:")
  are dropped; the wording must match the SDS verbatim. The field stays
  editable and the app warns if Section 7 or 13 can't be found.
- Default Precautionary Information option is "Requires SDS referral".
- **Who needs the SDS:** any non-tape product (canister, pail/drum/tote,
  MS/cartridge) must have its SDS uploaded to generate or save, unless an
  existing product is loaded that already has Storage & Disposal text.
  **Tape products have no SDS**: the uploader is not shown and Storage &
  Disposal defaults to the standard tape language ("Store material in original
  unopened packaging at temperatures between 40°F and 100°F. Shelf life is 12
  months when stored as recommended."), editable per product (shelf life).

## 13b. Vendor/current TDS pre-fill (optional)

- The app also lets the user upload an existing TDS (PDF) — their own
  current sheet, or a vendor/competitor's — to pre-fill the main form
  fields (`extract_tds_fields` in `app.py`): intro, features, applications,
  substrates, technical data, packaging, and the page-2 section bodies
  (Surface Preparation / Application Instructions / Clean Up Information /
  Storage & Disposal).
- Implementation: a plain text-position split on recognized section
  heading lines (regex per heading, case-insensitive), slicing the text
  between consecutive recognized headings. `tech_data` lines are further
  split into Property/Value pairs on 2+ spaces, a tab, or a colon.
- This is explicitly a **pre-fill of default values in the editable form
  fields**, never a direct write to a product JSON — the same
  review-before-use discipline as the SDS extraction (§13) and the
  no-fabrication rule (§14). It's rough (not real layout/table parsing),
  so review every field it touches, especially the intro line (can retain
  a stray title line) and the tech_data split (fails silently on anything
  that isn't a two-column line).
- A freshly-loaded existing product JSON ("Edit existing: <SKU>") always
  takes priority over a vendor TDS pull — the vendor TDS only pre-fills
  when starting a genuinely new product.

## 14. Sourcing discipline (tech_data, substrates, etc.)

- `tech_data` "Forza Test Method"-style attribution is only used for
  properties that are actually lab-tested; descriptive/categorical values
  (Appearance, Shelf Life, Color) don't get one. Never invent a named
  standard (ASTM or otherwise) unless it's actually been confirmed.
- `substrates`: omit the section entirely (`null`) rather than invent
  substrates a product doesn't actually support.
- `substrate_table`: only for structural bonding products; `null` for
  tapes/sealants where overlap shear doesn't apply.

## 15. Verification method (for any future visual-fidelity question)

Don't eyeball it — cross-reference real shipped PDFs directly with
pymupdf/PIL. This is the method that actually found and fixed every real
bug this session (wrong fonts, wrong colors, wrong watermark opacity,
wrong footer size):

- `page.get_images(full=True)` + `page.get_image_rects(xref)` → exact
  embedded-image placement rects (watermark, photos).
- `page.get_text("dict")` → exact font name + size (pt) per text span.
- PIL `im.getpixel()` / numpy diff-from-reference-color masks (and, when
  noise contaminates plain thresholding, `scipy.ndimage.label` connected-
  component analysis) → exact hex colors and element bounding boxes.
- `doc.xref_object(gs_ref)` on a PDF's ExtGState → confirms actual opacity
  (`/ca`) rather than guessing from how faded something looks.
- Cross-check against **multiple** real files (not just one), since a
  single file could be an outlier — this session confirmed several values
  identically across IC947, M-OS764, R-T600, and T310.

## 16. Rebuilding / re-verifying confidence

If anything in `template.html.j2` or `_footer.html.j2` is changed, rebuild
every existing product JSON (not just the one you're actively editing) and
re-run `verify_two_pages` on all of them before considering the change
done — a layout change that's fine for a short tape product can silently
blow a longer canister/cartridge product past 2 pages.

## 17. Corrections and additions from the FZD107 / ForzaBOND round

Found by comparing against real shipped ForzaBOND files (81-0389 Pail,
C804 Pail, IC947 Canister) and `Forza_TDS_Data_Master_with_FAQ_EN.csv`
(the 177-product master data, with `Brand Line`, Packaging, Recommended
Equipment, Precautionary Information etc. per SKU — use it as the source
of truth when a SKU is in it).

- **Precautionary Information for hazardous products is ONE run-on,
  lower-case, comma-separated paragraph** (H/P codes stripped), not
  separate paragraphs. This corrects §10/§12's earlier
  `precautionary.statements` description. Use
  `precaution_paragraph()` in `build/generate_tds.py` (the app now does
  this for SDS-extracted text) and store the result in
  `precautionary.text`. `statements` is still supported by the template
  but should not be used for new products.
- **Brand line picks the logo.** `"brand": "tape" | "bond"` in the
  product JSON selects `assets/logo_<brand>.png` (ForzaTAPE / ForzaBOND).
  ForzaBOND is used for adhesives incl. the Industrial canister IC947
  (not ForzaEAGLE). Add a new brand by dropping `logo_<name>.png` in
  `assets/` (extract from a shipped file, alpha restored).
- ForzaBOND logo placement measured on IC947: PDF rect
  (30.0,22.5)-(284.2,105.8)pt -> CSS `left:40px; top:30px; height:111px`.
  NOTE (open question): the shipped ForzaTAPE logo (T325) measures
  (28.5,20.2)-(288.0,108.0)pt, i.e. ~15% larger than our current tape
  logo CSS (height 100px). Left unchanged because the tape header was
  already approved; revisit if exact fidelity is wanted.
- Catalog container types are wider than our 3 app types: Aerosol, Bottle,
  Can, Canister, Cartridge, Drum, Pail, Pellet, Sausage, Tape, Tote. The
  app now has a "Pail / Drum / Tote (bulk)" type (SDS upload enabled,
  Recommended Equipment available, like Canister).
- Content missing from a source sheet is omitted, never invented
  (Surface Preparation, Clean Up Information, Substrates, Packaging,
  Recommended Equipment, product photo were all absent from the old
  FZD107 sheet and are left out until real data is supplied).
- **`"compact": true`** (optional product flag) turns on a dense layout
  (tighter bullet/row spacing, 2-up packaging grid) for long canister/pail
  sheets that overflow 2 pages at default spacing (needed for FZD107 built
  from IC933 content: 13 substrates + 9 tech rows + 5 packaging + equipment).
  Off by default, so approved sheets (T461 etc.) are unchanged.
- FZD107 (current `products/FZD107.json`) was built from IC933's content with
  only Features/Applications replaced by FZD107's own. IC933-derived text
  (description, substrates, tech data, packaging, equipment, instructions,
  clean up, storage, precautionary) is NOT verified for FZD107. The earlier
  FZD107-own-data version is kept as `products/_FZD107_own_data.json` and
  `output/FZD107_own-data_TDS.pdf`.

## 18. App look and dropdowns (Nov 10 2026)

- The Streamlit app itself follows the Forza brand standards: Kallisto Heavy
  headings (embedded from `assets/fonts/Kallisto_Heavy.otf`), Poppins body,
  Regal Blue #1B3764 and Blaze Orange #F16022, and the eagle mark
  (`assets/eagle_icon.png`, cropped from the Forza logo) in a navy header band.
  This is the app UI only -- the PDF template colors in sections 2-3 are
  unchanged (do not merge those navies with the brand blue).
- Dropdown options show the first letter capitalized (e.g. "Industrial");
  stored values stay lower-case because they match file names in assets/headers.
- Substrates wording: "seal"/"prime" instead of "bond" applies only to
  sealants, certain tapes and primers -- it is not a rule for every product.
