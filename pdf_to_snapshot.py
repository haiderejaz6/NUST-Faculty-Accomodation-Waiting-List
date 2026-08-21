#!/usr/bin/env python3
"""
Convert a NUST Faculty Accommodation Waiting List PDF into a dated snapshot
JSON for the housing registry site.

Usage:
    python3 pdf_to_snapshot.py path/to/list.pdf 2026-11-02 --label "2 Nov 2026"

This is a best-effort DRAFT extractor: the source PDF wraps long names onto a
second line in a way that reorders slightly when the text layer is read, so
ALWAYS diff the output counts against the PDF's own table of contents and
spot-check a few rows before committing data/<date>.json.
"""
import sys, re, json, argparse
import pdfplumber

DESIG_MAP = {
    "Assoc Prof of Practice": "Associate Professor of Practice",
    "Asst Prof of Practice": "Assistant Professor of Practice",
    "Prof of Practice": "Professor of Practice",
    "Prof of Prac": "Professor of Practice",
    "Principal & Dean": "Principal & Dean",
    "Tenured Prof": "Tenured Professor",
    "Snr Lecturer": "Senior Lecturer",
    "Assoc Prof": "Associate Professor",
    "Asst Prof": "Assistant Professor",
    "Instructor Arabic": "Arabic Instructor",
    "Arabic Instructor": "Arabic Instructor",
    "Demonstrator": "Demonstrator",
    "Principal": "Principal",
    "Professor": "Professor",
    "Lecturer": "Lecturer",
    "Prof": "Professor",
}
DESIG_KEYS = sorted(DESIG_MAP.keys(), key=len, reverse=True)

# Some pages in this template render certain words with a stray mid-word
# space (e.g. "As st Prof" for "Asst Prof", "Pro f" for "Prof", "Te nured"
# for "Tenured"). Collapse the known ones before anything else runs.
WORD_SPLIT_FIXES = [
    (re.compile(r'\bAs\s+st\b'), 'Asst'),
    (re.compile(r'\bAs\s+soc\b'), 'Assoc'),
    (re.compile(r'\bPro\s+f\b'), 'Prof'),
    (re.compile(r'\bTe\s+nured\b'), 'Tenured'),
    (re.compile(r'\bLe\s+cturer\b'), 'Lecturer'),
    (re.compile(r'\bSn\s+r\b'), 'Snr'),
    (re.compile(r'\bDemo\s+nstrator\b'), 'Demonstrator'),
    (re.compile(r'\bPrinci\s+pal\b'), 'Principal'),
    (re.compile(r'\bPr\s+incipal\b'), 'Principal'),
]
def fix_word_splits(line):
    for pat, repl in WORD_SPLIT_FIXES:
        line = pat.sub(repl, line)
    return line

MONTHS = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
          'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}

DATE_RE = re.compile(r'(\d{1,2})-{1,2}(\w{3})-{1,2}(\d{2,4})\s*$')
NUM_RE = re.compile(r'^\d+\.\s*(.*)$')
DEPT_RE = re.compile(r'^[A-Z][A-Z0-9\-]*$')

CATEGORY_HEADERS = [
    ("3bed",  re.compile(r'3\s*BED\s*ROOM', re.I)),
    ("25bed", re.compile(r'2\.5\s*BED\s*ROOM', re.I)),
    ("kkll",  re.compile(r'2\s*BED\s*ROOM\s*KK\s*&?\s*LL', re.I)),
    ("klmn",  re.compile(r'2\s*BED\s*ROOM\s*K,?\s*L,?\s*M,?\s*N', re.I)),
    ("iqra",  re.compile(r'2\s*BED\s*ROOM\s*IQRA', re.I)),
    ("1bed",  re.compile(r'1\s*BED\s*ROOM', re.I)),
]

# Fallback: identify categories from the plain-text Table of Contents (page 2),
# since the section headers inside the PDF are styled WordArt/images that
# don't appear in the extracted text layer.
TOC_ROW_RE = re.compile(r'^[a-z]\.\s*(.+?)\s+(\d+)-(\d+)\s*$', re.I)
TOC_LABEL_MAP = [
    ("3bed",  re.compile(r'^3\s*Bed$', re.I)),
    ("25bed", re.compile(r'^2\.5\s*Bed$', re.I)),
    ("kkll",  re.compile(r'KK\s*&?\s*LL', re.I)),
    ("klmn",  re.compile(r'K\s*,?\s*L\s*,?\s*M\s*,?\s*N', re.I)),
    ("iqra",  re.compile(r'Iqra', re.I)),
    ("1bed",  re.compile(r'^1\s*Bed$', re.I)),
]

def find_toc_page_ranges(pdf):
    """Look at the first few pages for a Table of Contents and return
    {category_key: (first_page, last_page)} using 1-indexed printed page numbers."""
    for page in pdf.pages[:4]:
        text = page.extract_text() or ""
        rows = {}
        for ln in text.split('\n'):
            m = TOC_ROW_RE.match(ln.strip())
            if not m:
                continue
            label, p1, p2 = m.groups()
            for key, pat in TOC_LABEL_MAP:
                if pat.search(label.strip()):
                    rows[key] = (int(p1), int(p2))
                    break
        if rows:
            return rows
    return None

def parse_date(s):
    m = DATE_RE.search(s)
    if not m: return None
    d, mon, y = m.groups()
    if len(y) == 2: y = '20'+y
    if mon not in MONTHS: return None
    return f"{y}-{MONTHS[mon]}-{int(d):02d}"

def split_desig(text):
    for k in DESIG_KEYS:
        if text == k or text.startswith(k + ' '):
            return DESIG_MAP[k], text[len(k):].strip()
    return None, None

def is_header_or_junk(line):
    l = line.strip()
    if not l: return True
    if re.match(r'^\d+$', l): return True  # bare page number
    if re.match(r'^(Ser|S\.?No)\s+Designation\s+Name', l, re.I): return True
    return False

def extract_and_assign(pdf_path):
    """Return list of (category_key, line) tuples. Primary strategy: read the
    Table of Contents page range per category (the in-body section headers are
    styled WordArt/images and usually aren't in the text layer). Falls back to
    text-based header detection if no TOC is found."""
    tagged = []
    with pdfplumber.open(pdf_path) as pdf:
        page_texts = [(p.extract_text() or "") for p in pdf.pages]
        toc = find_toc_page_ranges(pdf)

        if toc:
            for key, (p1, p2) in toc.items():
                for pnum in range(p1, p2 + 1):
                    if pnum - 1 >= len(page_texts):
                        continue
                    for raw in page_texts[pnum - 1].split('\n'):
                        ln = fix_word_splits(raw.strip())
                        if not ln or is_header_or_junk(ln):
                            continue
                        for _, pat in CATEGORY_HEADERS:
                            if pat.search(ln):
                                ln = None
                                break
                        if ln:
                            tagged.append((key, ln))
        else:
            current = None
            for text in page_texts:
                for raw in text.split('\n'):
                    ln = fix_word_splits(raw.strip())
                    if not ln:
                        continue
                    is_hdr = False
                    for key, pat in CATEGORY_HEADERS:
                        if pat.search(ln):
                            current = key
                            is_hdr = True
                            break
                    if is_hdr or is_header_or_junk(ln):
                        continue
                    if current:
                        tagged.append((current, ln))
    return tagged

BARE_NUM_RE = re.compile(r'^\d+\.\s*$')

def parse_category_lines(lines):
    """lines: list of raw text lines (already filtered) for ONE category, in
    the order they appear in the PDF. Queue order = list order, so the
    printed Ser number is not needed for ranking — we just drop those
    standalone-number artifacts and read rows off the stream in order.
    A row's name occasionally wraps onto a fragment line before and/or after
    its desig+dept+date line; those are stitched back on."""
    lines = [ln for ln in lines if not BARE_NUM_RE.match(ln)]
    records = []
    pending_prefix = None   # bare fragment seen before a row missing its name
    awaiting_suffix = None  # index into records[] still missing part of its name

    for raw in lines:
        ln = NUM_RE.match(raw)
        body = ln.group(1).strip() if ln else raw.strip()
        date = parse_date(body)

        if date is not None:
            # this line is a content row: [name] desig-and-or-name dept date
            awaiting_suffix = None
            rest = DATE_RE.sub('', body).strip()
            parts = rest.rsplit(None, 1)
            if len(parts) == 2 and DEPT_RE.match(parts[1]):
                dept, namepart = parts[1], parts[0]
            else:
                dept, namepart = (parts[0] if parts else ''), ''
            desig, name = split_desig(namepart) if namepart else (None, '')
            if desig is None:
                desig, _ = split_desig(namepart)
                name = ''
            name_was_empty = not (name or '').strip()
            if pending_prefix:
                name = (pending_prefix + ' ' + (name or '')).strip()
                pending_prefix = None
            rec = {"desig": desig or "Unknown", "name": (name or '').strip(), "dept": dept, "date": date}
            records.append(rec)
            if name_was_empty:
                awaiting_suffix = len(records) - 1
        else:
            # bare fragment line (no date) — part of a wrapped name
            if awaiting_suffix is not None:
                records[awaiting_suffix]["name"] = (records[awaiting_suffix]["name"] + ' ' + body).strip()
                awaiting_suffix = None
            else:
                pending_prefix = (pending_prefix + ' ' + body).strip() if pending_prefix else body
    return records

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('date', help='YYYY-MM-DD for the register date')
    ap.add_argument('--label', default=None)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    tagged = extract_and_assign(args.pdf)

    by_cat = {}
    for key, _ in CATEGORY_HEADERS:
        by_cat[key] = []
    for key, ln in tagged:
        by_cat[key].append(ln)

    categories = {}
    for key, _ in CATEGORY_HEADERS:
        recs = parse_category_lines(by_cat[key])
        categories[key] = [[r["name"], r["desig"], r["dept"], r["date"]] for r in recs]

    out = {
        "date": args.date,
        "label": args.label or args.date,
        "categories": categories
    }
    out_path = args.out or f"data/{args.date}.json"
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)

    print(f"Wrote {out_path}")
    for key, _ in CATEGORY_HEADERS:
        print(f"  {key}: {len(categories[key])} rows")
    print("\nCheck these counts against the PDF's own table of contents, then spot-check")
    print("a few names (long names that wrap to two lines are the most error-prone).")

if __name__ == "__main__":
    main()
