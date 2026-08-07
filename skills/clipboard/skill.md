# clipboard

Copies given text directly onto Jacob's Windows clipboard (using `pyperclip`), so he can paste
it into any app afterwards. Can also read back whatever is currently sitting on the clipboard.

## Examples
- "copy my email address to the clipboard"
- "copy this to the clipboard: 123 Main Street"
- "what's on my clipboard"

## Notes
- This is different from the `keyboard` skill's "copy" action, which just presses Ctrl+C on
  whatever is currently selected on screen. This skill lets TARS place specific text onto the
  clipboard directly, with nothing needing to be selected first.
- Uses `pyperclip`, already installed in the TARS runtime.
