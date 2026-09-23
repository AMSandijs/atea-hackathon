# Architecture — Local Attachment Clerk

## Module map

```
clerk/
  cli.py                 Typer app: pull, plan, file, review
  config.py              Loads config.yaml
  models.py              MailItem, DocFacts, Mapping, Plan dataclasses
  mailbox/
    outlook.py           Outlook COM: read queue folder, save attachments, move on done
    folder.py            --from-folder fallback: .msg / .eml on disk
    attachments.py       Signature filtering, size and type rules
  read/
    mail_body.py         Invoice numbers out of the body (regex, then model)
    document.py          Text layer, OCR fallback, schema extraction
    llm.py               Local model client, JSON schema output, retry ladder
  match.py               Attachment -> invoice mapping ladder
  describe.py            Description text + amount cross-check
  basware/
    session.py           CDP attach to an authenticated browser
    selectors.py         EVERY selector lives here, with observation notes
    lookup.py            Read-only: open invoice, read vendor and total
    filer.py             The attach loop plus post-upload verification
  mock/                  Static page mimicking the Add attachment modal
  review.py              Batch approval view
samples/
tests/
config.yaml
```

## Data shapes (`models.py`)

```python
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date, datetime

@dataclass
class MailItem:
    entry_id: str
    subject: str
    body: str
    received: datetime
    attachments: list[Path]
    invoice_numbers: list[str] = field(default_factory=list)   # filled by read/mail_body

@dataclass
class DocFacts:
    path: Path
    vendor_name: str | None
    invoice_number: str | None
    po_reference: str | None
    doc_date: date | None
    currency: str | None
    total: float | None
    doc_type: str          # invoice | credit_note | freight | delivery | timesheet | other
    confidence: float
    ocr_used: bool

@dataclass
class Mapping:
    attachment: Path
    invoice_number: str
    description: str
    confidence: float
    source: str            # email_ref | doc_ref | po_ref | lookup | model
    flags: list[str] = field(default_factory=list)   # amount_mismatch, low_confidence, ...

@dataclass
class Plan:
    mail: MailItem
    shape: str             # "A" | "B"
    items: list[Mapping]
    unmatched: list[Path]
    approved: bool = False
```

A `Plan` serializes to JSON so `plan` and `file` can be separate commands and the plan
can be inspected between them.

## Mailbox (`mailbox/outlook.py`)

```python
def read_queue(folder_path: str) -> list[MailItem]: ...
def mark_done(item: MailItem, done_folder: str) -> None: ...
```

```python
import win32com.client as com

ol    = com.Dispatch("Outlook.Application").GetNamespace("MAPI")
queue = ol.Folders[mailbox].Folders["Inbox"].Folders["Basware queue"]

for mail in list(queue.Items):     # list() — the collection mutates as you move items
    ...
    mail.Move(done_folder)         # reversible. never .Delete()
```

### Attachment filtering (`mailbox/attachments.py`)

Reject an attachment if any of:

- extension not in `{.pdf, .tif, .tiff, .jpg, .jpeg, .png}`
- size below `min_attachment_bytes` (default 20 KB) — catches signature logos
- the attachment's `PR_ATTACH_CONTENT_ID` appears in a `cid:` reference in the HTML body
- filename matches a configurable signature blocklist (`image00*.png`, `logo*`, ...)

Every rejection is logged with its reason. A wrongly rejected attachment must be visible,
not silent.

## Reading (`read/`)

### `mail_body.py`

```python
def invoice_numbers(body: str, cfg: Config) -> list[str]: ...
```

Regex first against the configured invoice-number patterns. Then, if the body contains
prose the regex did not cover, one model call returning a JSON list with surrounding
context. Preserve order of appearance — it correlates with attachment order more often
than not, and is a useful tie-breaker in matching.

### `document.py`

```python
def extract(path: Path, cfg: Config) -> DocFacts: ...
```

1. `pypdf` / `pdfplumber` text layer. If the page yields under `min_text_chars`, treat as
   a scan and OCR that page only with `pytesseract`.
2. First and last page only. Never send the whole document to the model.
3. One model call into the `DocFacts` schema.
4. Cache by file hash so re-runs are free.

### `llm.py`

Foundry Local via `FoundryLocalManager` (OpenAI-compatible), Ollama fallback selected by
config. **Structured JSON output, not tool calling** — small models choose tools badly
and fill schemas well, and Python owns the orchestration here so the model never chooses
anything.

Retry ladder: parse failure -> re-prompt once with the parser error appended -> second
failure marks the document `needs_human` and processing continues. Never crash the run
on one bad document.

## Matching (`match.py`)

```python
def build_plan(mail: MailItem, facts: list[DocFacts], cfg: Config,
               lookup: InvoiceLookup | None) -> Plan: ...
```

The ladder, in order. Stop at the first rung that resolves an attachment:

1. **`doc_ref`** — the document's own `invoice_number` is in `mail.invoice_numbers`. Exact
   match, confidence 1.0, no model involved.
2. **`po_ref`** — the document's `po_reference` matches a PO found in the body.
3. **`email_ref`** — shape A: only one invoice number in the mail, so everything goes there.
4. **`lookup`** — read-only Basware pass: for each candidate invoice read vendor and total,
   then match on vendor equality plus amount proximity within tolerance.
5. **`model`** — ranked-candidates prompt: the document's facts against the remaining
   candidate invoices. Returns a ranked list with scores.

Anything still unresolved goes to `Plan.unmatched`. Anything below
`cfg.min_auto_confidence` is kept in `items` but flagged `low_confidence`.

## Describe and check (`describe.py`)

```python
def describe(facts: DocFacts, invoice: InvoiceFacts | None, cfg: Config) -> tuple[str, list[str]]: ...
```

Description format: `{doc_type}, {vendor}, {date}, {pages}p, ref {reference}` — for
example `Freight note, Meridian Logistics, 14.09.2026, 2p, ref 18411562`. Keep it under
the field's length limit (confirm the real limit).

Cross-check: if both totals are known and differ by more than `cfg.amount_tolerance`,
add the `amount_mismatch` flag. Flagged items are shown but **never filed** without the
human explicitly overriding.

## Basware driver (`basware/`)

### `session.py`

```python
def attach_to_browser(cdp_url: str) -> Page: ...
```

Connects over CDP to a browser the user signed into by hand. Never launches a fresh
context and never fills a login form.

### `selectors.py`

Every selector in the codebase lives here, each with a comment recording when and where
it was observed. They are **guesses until verified against the real page** — budget the
first hour of Saturday for one person with devtools open on the real Add attachment modal.

### `filer.py`

```python
def file_one(page: Page, item: Mapping, cfg: Config) -> FileResult: ...
```

```python
open_invoice(page, item.invoice_number)
page.click(S.ADD_ATTACHMENT)
page.set_input_files(S.FILE_INPUT, str(item.attachment))   # no OS dialog
page.fill(S.DESCRIPTION, item.description)
page.click(S.SAVE)
page.wait_for_selector(f"text={item.attachment.name}")     # confirm, don't assume
```

Pre-flight: reject files above the modal's stated size ceiling before starting, rather
than failing mid-run. Post-flight: confirm the attachment count incremented.

`--target mock` points the same driver at `mock/` and is the default. `--target basware`
requires `CLERK_ALLOW_LIVE=1`.

## Review (`review.py`)

Batch approval across all queued mails. Shows per mail: shape, each attachment with its
invoice, description, confidence and source rung, plus flags. Unmatched files listed
separately. Returns per-item approve/reject; only approved items reach `filer`.

## Logging

Append-only JSONL: mail id, attachment name, invoice, match source, confidence, flags,
outcome. This is the audit trail, and it is as much a presentation asset as the demo —
"an attachment filed against the wrong invoice is an audit problem, not a lost minute."
