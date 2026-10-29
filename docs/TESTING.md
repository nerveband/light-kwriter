# Checks on real hardware

Checked on October 29, 2026, using a silver Kindle 4 Non-Touch (firmware 4.1.4) and a Mac. The physical screen was inspected through an iPhone Continuity Camera preview. Clean Kindle images in this folder come from the device framebuffer, not an emulator or generated mockup.

| Check | Result |
| --- | --- |
| USB connection | Passed |
| Wi-Fi connection | Passed |
| One-click pairing over trusted USB | Passed without typing on the Kindle |
| Find a device after a stale Wi-Fi address | Passed; the saved host key was checked |
| Browser helper tests | 3 passed |
| Wake from screensaver | Wake command and Active power state checked; writer verified through camera |
| JavaScript and Python syntax | Passed |

| Writer check | Result |
| --- | --- |
| Type and send text | Text inspected on the real screen |
| Select text | Browser selected the full sample with its normal keyboard shortcut |
| Undo | Typed a character, then restored the sample with the normal undo shortcut |
| Save while disconnected | Saved locally and survived a page reload |
| Reconnect | Latest draft sent to the Kindle |
| Preview toggle | Opened and closed correctly |
| Landscape and portrait | Layout reflowed; cable-right landscape was restored |

Observed command/transfer times for sample writing were roughly 0.4–0.7 seconds before the final transfer batching change. These are not optical keystroke-to-screen measurements. The full document stays on the computer; the e-reader shows the latest lines that fit.

## Limits

Other e-reader models, Windows helpers, physical cable removal during a session, and long battery-life runs were not tested. Browser screenshots show sample text. No personal draft, serial number, connection key, or known-host file is included.
