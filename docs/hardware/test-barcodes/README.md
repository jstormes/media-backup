# Scanner keycode test sheet

Determines empirically whether the barcode scanner can emit **F1–F10**, and what
it actually sends for every ASCII control character.

## Why this exists rather than a manual

The unit is sold as a **WoneNice WN3300 V3.1**, but it enumerates on USB as:

```
Bus 007 Device 023: ID 34eb:1502 MINJCODE MINJCODE MJ2818A
  bInterfaceClass    3  Human Interface Device
  bInterfaceProtocol 1  Keyboard
```

It is an OEM rebrand — HuiZhou Minjie hardware under a WoneNice label. A WN3300
manual therefore may not describe this firmware's actual programming barcodes,
so measuring the device beats trusting a manual for a different badge.

(The WN3300 manual could not be retrieved anyway: manuals.plus, mans.io,
usermanual.wiki and fcc.report all return 403/404 to automated fetches. If you
download it by hand, add it here — it would still be useful for the vendor
*setup* barcodes, which cannot be synthesised.)

Published WN3300 specs, for reference: 650±20 nm VLD laser, 300 scans/sec,
3 mil resolution, 2–100 mm depth of field, USB and USB-COM, 1D symbologies
(Code 39/93/128/11/32, Codabar, UPC-A/E, EAN-8/13, ITF, MSI/Plessey), and the
vendor claims it *"supports function key and composite key operations"* — which
is precisely the claim this sheet is designed to verify.

## Files

| File | Purpose |
|---|---|
| `scanner-test-sheet.pdf` | **Print this.** 37 barcodes, 2 pages, US Letter (rev 2 — all verified decodable). |
| `scanner-test-sheet.html` | Source of the PDF; regenerate if you change the set. |
| `capture-scan.sh` | Records what the scanner emits, as kernel input events. |
| `analyze-scan.py` | Segments a capture into scans and reports the keys. |

## What is on the sheet

| # | Content | Purpose |
|---|---|---|
| 1 | UPC-A `012345678905` | Baseline. Proves scanning works and reveals the default terminator (CR / LF / Tab / none). |
| 2 | Code 128 `TEST12345` | Baseline for literal ASCII. |
| 3–33 | Code 128, one ASCII control char each, `0x01`–`0x1F` | The actual probe. If this firmware maps control codes to function keys, it shows up here. |
| 34–37 | Extended Code 39, `0x01`/`0x02`/`0x03`/`0x1B` | Cross-check: some scanners only do full-ASCII translation for Code 39, and only when enabled. |

Cells marked ⚠ (`0x08` BS, `0x09` HT, `0x0A` LF, `0x0D` CR, `0x1B` ESC) encode
control codes that already have a keyboard meaning. A Backspace/Tab/Enter/Escape
there is expected and says nothing about F-key support — they are included so
the mapping is complete, not because they are evidence.

## Procedure

**1. Print `scanner-test-sheet.pdf` at 100% scale.** Do not use "fit to page" —
shrinking pushes the bars toward the scanner's 3 mil resolution limit. Plain
white paper, not glossy.

**2. Start the capture** (needs root to read `/dev/input`):

```bash
cd docs/hardware/test-barcodes
sudo ./capture-scan.sh 180        # seconds; default 120
```

The script uses `evtest --grab`, taking **exclusive** access to the scanner.
Scanned data does not reach your desktop — nothing gets typed into whatever
window has focus, and no stray Enter presses fire anything.

**3. Scan every barcode in numbered order, 1 → 37, pausing ~2 s between each.**
The pause is load-bearing: segmentation is by timing gap. If a barcode will not
read, pause and move on — the gap records it as a miss and keeps numbering
aligned.

**4. Analyse:**

```bash
./analyze-scan.py scan-capture.log
```

Output per scan:

```
--- scan  3  (8 ms, 2 events)
    SPECIAL : F1
```

`SPECIAL` is the answer. `F1`–`F12` there means this firmware emits function
keys for that barcode. Only `text` means it sent printable characters. Nothing
at all means the control code was swallowed.

Adjust `--gap` (default 1.0 s) if your scanning rhythm was faster or slower.

## Interpreting the result

**If F-keys appear** — record which control code produces which F-key. That
mapping becomes the `F1`–`F6` contract in `PLAN.md`, and the Tauri frontend can
listen for real `keydown` events with `key: "F1"`.

**If no F-keys appear** — the control codes are being dropped or passed through
as literal characters, and function-key output needs enabling via vendor setup
barcodes we do not have. Options then, in order of preference:

1. Get the real manual (vendor: `minjcode.com/download`, support@minj.cn) for
   the setup barcodes that enable function-key mode.
2. Change the contract in `PLAN.md`: use ordinary text sentinels instead of
   F-keys — e.g. a barcode encoding `##MODE-UPC##` — and match on the string in
   the frontend. This needs no scanner configuration at all and is arguably more
   robust, since it survives a scanner swap.
3. Read the scanner as a raw HID device rather than a keyboard wedge, giving
   full control but losing the plug-and-play property.

Option 2 is worth considering regardless — the F1–F6 design in `PLAN.md`
presumes a scanner capability that is, as of this writing, unverified.

## Regenerating the sheet

Requires `zint` and `chromium`:

```bash
# barcodes are generated with:
#   zint --barcode=20 --esc -d '\x01' --scale=2 --height=16 --quietzones --notext
# then inlined into the HTML and rendered:
chromium --headless --no-pdf-header-footer \
         --print-to-pdf=scanner-test-sheet.pdf scanner-test-sheet.html
```

Two things that bite when regenerating: `--quietzones` is required (a barcode
without its quiet zone often will not read), and the inlined SVGs must keep
their `viewBox` with the fixed `width`/`height` attributes stripped, so CSS can
scale them. Fixing the height instead squeezes the modules below render
resolution and the bars disappear.

---

# Results

## Run 1 — 2026-08-23 (sheet rev 1)

Raw capture: `scan-capture-rev1.log`. 33 keydowns, 32 scans, from 37 barcodes.

```
CAPSLOCK KPENTER CAPSLOCK LEFTCTRL ENTER LEFT TAB DOWN INSERT DELETE ENTER
INSERT ESC F11 HOME SYSRQ BACKSPACE ⇧TAB F12 F1 F2 F3 F4 F5 F6 F7 F8 F9 F10
F8 F9 F10
```

### CONFIRMED: this scanner emits F1–F12

The design in `PLAN.md` is viable. Every scan produced **exactly one
keystroke** — inter-key gaps were 400–1500 ms with no sub-200 ms runs, and the
one `⇧TAB` is a single chord. So the firmware maps ASCII control codes in
barcode data to keystrokes, and function keys are in that map, alongside
navigation and editing keys (`INSERT`, `DELETE`, `HOME`, `SYSRQ`, `CAPSLOCK`,
`LEFTCTRL`, `KPENTER`).

No scanner configuration was needed. Control codes in plain **Code 128** data
are sufficient.

### NOT established: which barcode maps to which key

5 of the 37 barcodes failed to read, and their positions in the sequence are
unknown, so the 32 observations cannot be aligned to specific control codes.
The monotonic run `F1 F2 F3 F4 F5 F6 F7 F8 F9 F10` is a strong hint that
consecutive control codes map to consecutive function keys, but the anchor —
which control code is F1 — is not pinned down. **Do not encode a mapping from
run 1 into application code.**

### Root cause of the read failures — fixed in rev 2

zint emits SVG with `width`/`height` attributes and **no `viewBox`**. The sheet
builder stripped those attributes so CSS could size the barcodes, which left the
SVG with no intrinsic dimensions: content then renders at 1:1 user units and is
**clipped** to the cell rather than scaled to it. Barcodes narrower than their
cell were unaffected, which is why the 31 short control-code barcodes read fine
and the two long baselines — UPC-A (452 units) and Code 128 `TEST12345` — were
cut off mid-symbol and could not be read by anything. That matches the capture
exactly: zero text output.

Verified with `zbarimg` on 300 dpi renders of both revisions:

| Cell | rev 1 | rev 2 |
|---|---|---|
| 1 UPC-A baseline | NO DECODE | `EAN-13:0012345678905` |
| 2 Code128 baseline | NO DECODE | `CODE-128:TEST12345` |

rev 2 adds `viewBox="0 0 W H"` before stripping the attributes. All barcodes on
rev 2 are machine-decodable, and the sheet is 2 pages instead of 4.

**Lesson for anything that regenerates this sheet:** verify the output with a
decoder (`zbarimg` on a 300 dpi `pdftoppm` render), not by eye. Rev 1 looked
perfectly fine in a page preview — the clipping is only obvious when you crop a
single cell or try to decode it.

## Run 2 — pending

Re-scan with rev 2, where all 37 barcodes are verified readable. With no
failures the sequence aligns 1:1 with the printed order and the full control
code → keystroke map falls out directly.

## Run 2 — 2026-08-23 (sheet rev 2) — RESOLVED

Raw capture: `scan-capture-rev2.log`. 36 of 37 barcodes read (only cell 2
failed). The rev-2 clipping fix is confirmed by the scanner itself: cell 1
produced `012345678905`, which rev 1 could not read at all.

Cross-referencing both runs settled the mapping. **21 of 31 control codes gave
identical results in both**, including both endpoints of the F-key block. The
outcome is written up as a spec in
[`../barcode-function-keys.md`](../barcode-function-keys.md) — that document, not
this one, is the reference for implementers.

Headline: **F1–F10 are ASCII control codes 0x16–0x1F, contiguous.**

Two incidental findings worth keeping:

- **Code 39 full-ASCII is not translated by this firmware.** The Extended
  Code 39 cells produced the literal escape pairs (`%A`, `$B`) as
  Shift-modified text rather than control codes. Use Code 128.
- **Scanner timing is sharply bimodal** — ~8 ms between characters of one
  barcode, >400 ms between barcodes, with nothing in the 30–400 ms band. That is
  a robust way to distinguish scanner input from human typing, and to end a scan
  on idle timeout given there is no terminator character.

The disagreements between runs fall entirely in `0x17`–`0x1A` and `0x01`–`0x06`,
which is exactly where run 2 was scanned out of order (the 13.7 s gap in the log
marks the page-1/page-2 turn at cell 25). The former is resolved by arithmetic;
the latter is unusable regardless.
