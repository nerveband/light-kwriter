# Working on this app

Keep the browser UI local and the helper bound to loopback. Do not add a hosted service or send drafts and tasks to a third party.

## File map

- `web/index.html`: page structure and control labels.
- `web/style.css`: layout and appearance.
- `web/common.js`: connection, screen size, image encoding, and orientation controls.
- `web/app.js`: the app's editor or timer flow and canvas preview.
- `server.py`: local storage, USB/Wi-Fi connection, pairing, discovery, and uploads.

## Boundaries

The browser draws the screen. The helper compresses and sends the pixels. Keep the preview and device layout together. Use the configured SSH aliases, not credentials in browser code. Never commit `device.json`, pairing keys, known-host files, or user data.

This adapter is for a Kindle 4. Check real device behavior before claiming support for another model. Do not change global networking, USBNetwork configuration, or stock firmware as part of a UI edit.

## Checks

Run `python3 -m py_compile server.py`. Run `node --check` on each JavaScript file. Inspect the page in a browser after visual edits. Use a temporary `EINK_DATA_DIR` for sample data and screenshots.

For a device change, test USB and Wi-Fi, rotation, disconnect/reconnect, and the actual e-ink screen. A command acknowledgment is not an optical latency measurement. Document unavailable checks.
