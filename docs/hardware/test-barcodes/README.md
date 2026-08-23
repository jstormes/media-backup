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
| `scanner-test-sheet.pdf` | **Print this.** 37 barcodes, 4 pages, US Letter. |
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
