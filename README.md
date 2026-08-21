# NUST Faculty Housing Registry — multi-snapshot tracker

A static site that turns the Directorate of Accommodation's periodic
"Faculty Accommodation Waiting Lists" PDF into a searchable registry with
a **projected turn estimate** per applicant, based on how fast each
category has actually been clearing between registers.

Live logic lives entirely in `index.html` (no build step, no framework).
Data lives in `data/`, one JSON file per register. Adding a new register
does **not** require touching `index.html` at all.

## How it works

- `data/manifest.json` lists every snapshot file, in the order you add them.
- `index.html` fetches the manifest, then fetches every snapshot listed in
  it, and computes everything client-side:
  - **Queue rank** — an applicant's position is their row order within
    their category in the *latest* register (this mirrors the PDF's own
    Ser numbering, which is the institution's actual queue order).
  - **Velocity** — between each pair of consecutive registers, per
    category, anyone who *was* on the list and no longer is counts as a
    departure (almost always an allocation; occasionally a withdrawal or
    a move to a different category — the register alone can't fully
    distinguish these). `departures ÷ days ÷ 30.44` gives a monthly
    clearance rate. With more than one interval on file, the rate is
    computed across the whole history, which smooths out any one
    unusually quiet or busy stretch.
  - **Projected turn** — `your rank ÷ monthly rate`, added to the latest
    register's date. Shown in the table and in the "Find your position"
    search box. Categories with only one interval of data carry a wider
    margin of error; this narrows as more registers are added.
  - **Movement log** — who left and who joined each category's list
    since the last register.
- Name matching across registers strips titles/punctuation and falls
  back to a fuzzy match (checked against department + request date) to
  catch OCR/typo drift between PDFs — e.g. "Iftikhar" vs "Iftiikhar" in
  the source documents.

## Adding a new register

1. Get the new PDF from DDAdmin (same naming pattern: *Faculty
   Accomodation Waiting Lists Upto \<date\>.pdf*).
2. Draft a snapshot JSON from it:
   ```
   python3 pdf_to_snapshot.py path/to/list.pdf 2026-11-02 --label "2 Nov 2026"
   ```
   This writes `data/2026-11-02.json` and prints a per-category row count.
   **Check that count against the PDF's own table of contents (page 2)
   before doing anything else** — if a category is short, the most
   likely cause is a name that wraps across two lines in an unusual way;
   open the JSON and fix that row by hand (the format is
   `["Name", "Designation", "Dept", "YYYY-MM-DD"]`).
3. Add the new filename to `data/manifest.json`:
   ```json
   { "snapshots": ["2026-05-13.json", "2026-08-03.json", "2026-11-02.json"] }
   ```
4. Commit and push. That's it — `index.html` re-reads the manifest on
   every load and recomputes rates, ranks, and projections automatically.

The extractor handles this PDF template's known quirks (names that wrap
onto a second line, Ser numbers that get split onto their own line, and a
mid-word-space rendering glitch that affects some pages), but a new
template revision from DDAdmin could introduce something it doesn't
expect — the row-count check in step 2 is what catches that.

If a PDF ever comes without a usable text layer (a pure scan), the
script won't find anything; you'd need to transcribe that one by hand
into the same JSON shape.

## Deploying on GitHub Pages

This replaces the Netlify setup with a marginally simpler one, since
there's no build step:

1. Create a repo (or reuse one) and push this folder's contents
   (`index.html`, `data/`, `pdf_to_snapshot.py`) to its default branch.
2. In the repo's **Settings → Pages**, set the source to that branch,
   root folder.
3. GitHub gives you a URL like `https://<user>.github.io/<repo>/`. Note
   that `fetch('data/manifest.json')` is a relative path, so this works
   whether the site is served from a domain root or a repo subpath —
   don't hardcode an absolute path anywhere.
4. From then on, publishing a new register is exactly the 4 steps above
   — commit and push, no rebuild trigger needed since GitHub Pages serves
   the files directly.

**Local preview**: opening `index.html` directly (`file://`) will not
work — browsers block `fetch()` on local files. Serve it instead:
```
python3 -m http.server 8000
```
and open `http://localhost:8000`.

## Files

```
index.html            the whole site — layout, styles, and analysis logic
pdf_to_snapshot.py     PDF → snapshot JSON drafting tool
data/
  manifest.json        ordered list of snapshot filenames
  2026-05-13.json       first register on file
  2026-08-03.json       second register on file
```
