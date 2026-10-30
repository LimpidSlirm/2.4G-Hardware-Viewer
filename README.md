# 2.4G-Hardware-Viewer

Windows hardware status viewer for connected audio, keyboard, and mouse devices.

## Current scope

The first version reads device information already exposed by Windows. It does
not capture raw 2.4G radio packets from the air.

The target devices are:

- Headset or other audio endpoints
- Keyboard
- Mouse

## Step 1 verification

On the development computer, Windows currently enumerates:

- HUAWEI FreeBuds SE 2 audio endpoints and media devices
- HID and USB keyboard devices
- HID mouse devices

All inspected matching devices reported status `OK`.

## Known limitations

The information available to the application depends on the device and its
Windows driver. Connection state and device identity are expected to be
available; battery, signal quality, latency, and vendor-specific details may
not be exposed.
