# Barcode → function key: how it works

Specification for driving the barcode scanner as a mode-switch input device.
Everything here was measured on the actual hardware, not taken from a datasheet.

Companion material: [`test-barcodes/`](test-barcodes/) holds the experiment that
produced this — the test sheet, the capture harness, and the raw logs.

---

## The mechanism

The scanner is a **USB HID keyboard wedge**. To the OS it is an ordinary
keyboard; there is no driver, no serial port, and no vendor SDK involved.

```
Bus 007 Device 023: ID 34eb:1502 MINJCODE MINJCODE MJ2818A
  bInterfaceClass    3  Human Interface Device
  bInterfaceProtocol 1  Keyboard
```

Sold as a **WoneNice WN3300 V3.1**; it is an OEM rebrand of HuiZhou Minjie
hardware. Treat the MINJCODE identity as authoritative — a WN3300 manual
describes a different badge and may not match this firmware.

When it reads a barcode it "types" the decoded data. Printable characters
arrive as the obvious keystrokes. The useful part:

> **ASCII control characters (0x01–0x1F) in the barcode data are translated by
> the scanner firmware into non-character keystrokes — including F1–F12.**

So a barcode whose *data* is the single byte `0x16` causes the scanner to press
**F1**. No prefix, no suffix, no configuration barcodes, no vendor setup mode.
Encode the control byte and the key comes out.

This is what makes mode-switch barcodes possible: the application listens for
ordinary `keydown` events and never has to parse a magic text string.

---

## The mapping

### F1–F10 — contiguous, use these

| Barcode data | ASCII | Key emitted |
|---|---|---|
| `0x16` | SYN | **F1** |
| `0x17` | ETB | **F2** |
| `0x18` | CAN | **F3** |
| `0x19` | EM | **F4** |
| `0x1A` | SUB | **F5** |
| `0x1B` | ESC | **F6** |
| `0x1C` | FS | **F7** |
| `0x1D` | GS | **F8** |
| `0x1E` | RS | **F9** |
| `0x1F` | US | **F10** |

**F1–F10 are exactly control codes 0x16–0x1F, in order.** That is the whole
rule; `F_n = 0x15 + n` for n in 1..10.

### F11 and F12 — not contiguous

| Barcode data | ASCII | Key emitted |
|---|---|---|
| `0x10` | DLE | **F11** |
| `0x15` | NAK | **F12** |

These sit outside the F1–F10 block. If a design needs twelve modes, do not
assume `0x20` continues the run — it does not (0x20 is a printable space).

### Other keys in the map

Confirmed, and worth knowing so they are not chosen by accident:

| Data | Key | | Data | Key |
|---|---|---|---|---|
| `0x03` | CapsLock | | `0x0E` | Insert |
| `0x07` | Enter | | `0x0F` | Esc |
| `0x08` | Left | | `0x11` | Home |
| `0x09` | Tab | | `0x12` | SysRq |
| `0x0A` | Down | | `0x13` | Backspace |
| `0x0C` | Delete | | `0x14` | Shift+Tab |
| `0x0D` | Enter | | | |

Several of these are actively hostile in an application — `CapsLock` toggles
global keyboard state, `SysRq` is a kernel magic key, `Backspace` and `Delete`
mutate focused fields. **Never encode 0x03, 0x12, 0x13 or 0x0C in a production
barcode.**

### Codes 0x01–0x06 and 0x0B: undetermined

The two capture runs disagreed for these (they map to `LeftAlt`, `KpEnter`,
`LeftCtrl`, `Tab` and similar bare modifiers, but which is which is unresolved).
They are unusable regardless — a lone `LeftAlt` or `LeftCtrl` keypress is a
modifier with no key, which desktop environments may intercept. Avoid the whole
range.

---

## Generating a barcode

**Code 128 only.** Verified with `zint`:

```bash
# F1 (0x16). For F_n, use hex of 0x15 + n.
zint --barcode=20 --esc -d '\x16' \
     --scale=2 --height=18 --quietzones --notext -o F1.svg
```

`--barcode=20` is Code 128, `--esc` enables `\xNN` escapes, `--quietzones` adds
the compliant white margin.

### Code 39 does NOT work

Extended/Full-ASCII Code 39 encodes control characters as two-character escape
pairs (`$A` = 0x01, `%A` = 0x1B). **This firmware does not translate them** — it
types the pair literally. A Code 39 barcode for 0x1B produced the keystrokes
`Shift+5`, `Shift+A` — i.e. the text `%A` — instead of F6. Verified directly.

Use Code 128 and nothing else for control codes.

### Rendering pitfall

If barcodes are laid out in HTML, note that `zint` emits SVG with `width` and
`height` attributes and **no `viewBox`**. Stripping those attributes so CSS can
size the barcode leaves the SVG with no intrinsic dimensions — content then
renders at 1:1 user units and is **clipped** to its container rather than
scaled. Barcodes wider than their container are silently cut mid-symbol and
become unreadable, while looking perfectly plausible in a page preview.

Add `viewBox="0 0 W H"` before removing `width`/`height`.

**Always verify generated sheets with a decoder rather than by eye:**

```bash
pdftoppm -png -r 300 sheet.pdf page && zbarimg --quiet page-1.png
```

This bug cost a full print-and-scan cycle. It is not theoretical.

---

## What the application observes

### One barcode = one keystroke

A control-code barcode produces exactly one keydown/keyup pair. No prefix, no
suffix, **no terminator** — the scanner is not configured to append Enter or
Tab, so a mode barcode will not also submit a focused form.

A data barcode (e.g. a UPC) produces one keystroke per character, also with no
terminator. UPC-A `012345678905` arrived as twelve digit keystrokes and nothing
else.

### Timing — how to tell the scanner from a human

Measured across 89 keystrokes in two runs, the distribution is sharply bimodal
with **nothing between 30 ms and 400 ms**:

| Gap between keydowns | Count | Meaning |
|---|---|---|
| < 30 ms (typically **8 ms**) | 21 | same barcode, next character |
| 400–2000 ms | 34 | next barcode |

So: keystrokes ~8 ms apart are one scan; a gap over ~200 ms ends it. A 12-digit
UPC arrives in about 96 ms total.

This is a reliable discriminator — no human types at 8 ms/key — and it means an
implementation can buffer a scan by timeout without needing a terminator
character. A 200 ms idle threshold sits in the middle of an empty region of the
distribution, so it is not a tuned magic number.

### Exclusivity

The scanner is a normal keyboard, so **its input goes to whatever window has
focus**. Anything that must not leak keystrokes into other applications has to
grab the device (`EVIOCGRAB` on the `/dev/input/event*` node) or filter by
device id. The device is identifiable by a stable path:

```
/dev/input/by-id/usb-MINJCODE_MINJCODE_MJ2818A_00000000011C-event-kbd
```

Reading `/dev/input` requires root or membership in `input`.

---

## Evidence and confidence

Two independent capture runs, `evtest --grab` on `/dev/input/event22`, scanning
a 37-barcode sheet covering all of 0x01–0x1F in Code 128 plus Code 39
cross-checks and UPC-A/Code128 baselines. Raw logs are in
[`test-barcodes/`](test-barcodes/).

**21 of 31 control codes produced identical results in both runs.** That set
includes `0x16 → F1` and `0x1B → F6` through `0x1F → F10`.

`0x17`–`0x1A` (F2–F5) were observed monotonically as F2 F3 F4 F5 in run 1; run 2
scanned that page out of order and saw the same *set* jumbled. The values are
nevertheless forced: both endpoints (`0x16 → F1`, `0x1B → F6`) are
double-confirmed, and there are exactly four codes and four F-keys between them.

Confidence: **high for F1–F10**, high for F11/F12 and the named editing keys,
**none for 0x01–0x06 and 0x0B** — which are unusable anyway.

Worth a single confirming scan before shipping: print the ten F-key barcodes,
scan them in order, and check that F1–F10 come out in sequence. That takes
about twenty seconds and removes the last inference from the chain.

---

## Implications for `PLAN.md`

`PLAN.md` specifies "HID keyboard-wedge barcode scanner (F1–F6 keycodes)" with
hardcoded mapping (F5 = scan UPC, etc.). **That design is viable as written** —
F1–F6 are available as `0x16`–`0x1B` with no scanner configuration.

Two things the implementing agent should know:

1. **Mode barcodes and data barcodes are indistinguishable at the device
   level.** Both are just keystrokes from the same keyboard. The F-key *is* the
   signal; there is no separate channel.

2. **No terminator means the app owns scan-completion.** For UPC data, decide a
   scan is finished on idle timeout (~200 ms per the timing above) rather than
   waiting for an Enter that will never arrive.

If the F-key approach is ever abandoned, the fallback is a text sentinel
(e.g. a barcode encoding `##MODE-UPC##`) matched as a string. That needs no
scanner capability at all and survives a scanner swap — but it is *not*
currently necessary.
