# Adapt to another e-reader

This is a device adapter, not a universal Kindle driver. Start with a working USBNetwork or SSH connection and FBInk build for your device.

1. Check its display width, height, and rotation values. The current canvas sizes are 800 × 600 and 600 × 800.
2. Update `dimensions()` in `web/common.js` and the image-size check in `server.py`.
3. Check the FBInk path and refresh behavior in `server.py`.
4. For FirePace, also update display sizes, tool paths, and event-device mappings in `device/timer.sh`.
5. Test a short sample. Check wrapping, margins, timer alignment, all rotations, and a full refresh on the real screen.

The default USBNetwork address is specific to this setup. A private `device.json` can set `ssh_config` to an SSH config file and `hosts` to an object with `usb` and `wifi` alias names. Keep that file out of Git.

Wi-Fi discovery searches the last paired IPv4 /24 subnet. It is not mDNS or internet discovery. Password entry is not supported by the app. Pairing uses the trusted USB connection and a generated local key.
