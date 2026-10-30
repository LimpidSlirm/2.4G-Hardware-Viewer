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

## Technical direction

The project will use:

- Python 3.13
- PySide6 for the Windows desktop user interface
- pywin32 for Windows device and system interfaces
- pyserial only if a future supported device exposes a serial interface

The application targets Windows first. The .NET/WPF option was considered, but
the current development environment has a usable Python GUI and Windows API
stack already installed, so Python is the lower-friction choice for the first
working version.

## Step 2 verification

The development environment currently provides:

- Python 3.13.9 through the active `python` command
- PySide6 6.9.2
- pywin32
- pyserial 3.5
- Tkinter as a fallback standard-library GUI toolkit

These components are sufficient to create and run the initial desktop
application without installing additional packages.

## Interface direction

The application uses a transparent overlay window that:

- Has no standard Windows border or title bar
- Stays above other windows
- Can be moved by dragging the visible panel
- Closes with the `Esc` key during the prototype stage

The transparent overlay is the initial shell. Device status cards and controls
will be added without changing this window behavior.

## Project structure

```text
app/
  __init__.py
  main.py
requirements.txt
```

## Step 3 verification

Run the prototype from the project directory:

```powershell
python -m app.main
```

Run the automatic startup smoke test:

```powershell
python -m app.main --smoke-test
```

## Step 4 verification

The prototype now queries Windows Plug and Play devices through
`Get-PnpDevice -PresentOnly` and displays matching audio endpoints, keyboards,
and mice. On the development computer, the query returned 15 devices and all
reported status `OK`.

The current discovery layer only reads device identity and connection status.
It does not capture keyboard input, mouse movement, audio content, or raw
2.4G packets.

The device panel groups results by category, removes repeated display entries
that represent the same category, name, and status, shows normal-status counts,
and refreshes automatically every five seconds. The underlying Windows
instance IDs are retained for future detail views.

The panel also provides an immediate refresh button. Hovering over a device
shows its Windows instance ID without adding the technical identifier to the
main display.

Device discovery runs in a background Qt thread, so the transparent window
remains responsive while an immediate or automatic refresh queries Windows.

Clicking a device row shows its category, status, and Windows instance ID in
the detail area below the device list. Long instance IDs wrap inside the
overlay instead of expanding the window horizontally.

The overlay supports `F5` for an immediate refresh. `Ctrl+Up` and `Ctrl+Down`
increase or decrease opacity between 35% and 100%; `Esc` closes the window.
The panel displays the most recent refresh time and current opacity.

## Battery readings

The discovery query also checks the Windows ACPI battery. Peripheral battery
levels are shown as `未知（Windows 未公开）` unless Windows exposes a
device-specific battery value; the application does not infer a percentage
from connection or power-management data. On the development computer, the
system battery reports 100%, while the connected headset, keyboard, and mouse
do not currently expose a percentage through the tested generic PnP properties.

The reference project
[`2.4G-battery-viewer`](https://github.com/yszyszysz233/2.4G-battery-viewer)
uses device-specific HID protocols for VID:PID `373B:1216` and `3654:6901`.
The development computer currently exposes `3554:FA09` and `24AE:1411` for
its HID keyboard/mouse devices, and the headset appears as a Bluetooth device,
so those reference commands are not applied automatically.

The discovery view excludes the laptop's ACPI/PS/2 keyboard and the built-in
microphone array. Automatic Windows device reading runs every five minutes;
the `立即刷新` button and `F5` still trigger an on-demand read.

The detail view now identifies the device transport and, when present, its
VID:PID. This is a read-only identification step for selecting a safe
device-specific battery protocol; it does not send HID commands.

The device list is scrollable and the overlay height is capped so a larger
number of device entries cannot expand the window beyond the screen.

The application still calculates how many peripheral battery values were read
and how many remain undisclosed by Windows, but this summary is hidden from the
overlay to keep the panel compact. Each row shows the current battery source:
`Win32_Battery` for the system battery, `Windows` for a device-specific value,
or `待探测` when a vendor/HID protocol has not yet been identified.

## HID battery investigation

The project now includes a read-only HID inventory using the Windows HID and
SetupAPI DLLs. It records VID:PID, Usage Page, Usage, and input/output/Feature
Report lengths without sending reports or reading input events.

On the development computer, the inventory found 22 HID interfaces. The
external keyboard/mouse interfaces use VID:PID `3554:FA09` and `24AE:1411`;
17 matching interfaces were found, including 3 with Feature Reports. These
interfaces are the next safe source for device-specific battery investigation.

The first read-only Feature Report probe tried Report IDs `0` through `3`.
Only one report responded: `093A:0255`, Usage `0x0D/0x05`, length 257,
which belongs to the touchpad rather than the target external keyboard or
mouse. The target `3554:FA09` and `24AE:1411` Feature Report interfaces did
not return a report, so no battery value is inferred from this probe.

The current vendor probe can read `3554:FA09` Report 6 through `pywinusb`
without sending a report. On the development computer it returned stable
candidate bytes `(100, 100, 100)` in three consecutive reads. Because this
receiver exposes the keyboard and mouse together, the first value is currently
shown as `键盘电量候选 100%`; it remains explicitly marked as a candidate until
a controlled battery-change test confirms the byte mapping.

## Disconnect test

After the keyboard and headset were disconnected, `3554:FA09` disappeared
from the HID inventory and its vendor battery probe returned no reading. The
`24AE:1411` interfaces remained present, and Windows continued to enumerate
the headset's Bluetooth/audio endpoints. This means the next mapping test must
connect one peripheral at a time; Windows may retain audio endpoints after a
Bluetooth device is disconnected.
