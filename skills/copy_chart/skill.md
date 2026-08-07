# copy_chart

Copies our most recently created chart/graph image straight onto the Windows clipboard as an
actual picture (not a filename or text), so Jacob can paste it directly into an email, Word doc,
or chat with Ctrl+V.

## How it finds "the most recent chart"
1. Looks first in the TARS working folder (`workshop`, searched recursively) for image files
   whose name hints it's a chart — contains "chart", "graph", "plot", or "dashboard" — and picks
   the newest one by last-modified time.
2. If nothing hinted turns up there, it widens the same name search to Pictures, Desktop,
   Downloads, and Documents (top level only).
3. If still nothing, it falls back to the single newest image file anywhere in the working
   folder, on the assumption that's the chart TARS (or Jacob) most recently produced.

## How the copy works
Loads the image with Pillow, converts it to a Windows DIB bitmap, and puts it on the clipboard
with `pywin32`'s `win32clipboard` (format `CF_DIB`) — the same format Windows' own "Copy Image"
uses, so it pastes correctly into virtually anything.

## Examples
- "copy our most recent chart into the clipboard"
- "copy the latest chart"
- "put that graph on my clipboard"

## Notes
- This is different from the `clipboard` skill, which only copies/reads plain TEXT — it has no
  way to put an actual picture on the clipboard.
- Uses `Pillow` and `pywin32`, both already installed in the TARS runtime.
- Never deletes or moves anything — read-only, just copies pixels into the clipboard.
