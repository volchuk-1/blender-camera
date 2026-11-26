# Blendcam

Use an iPhone (ARKit world tracking) as a handheld camera for Blender 4.5: walk through your scene with the
phone, record takes as camera keyframes, export them for video generation. Local Wi‑Fi only.

- `addon/blendcam/` — Blender add-on: receives the phone pose, drives the scene camera, records takes
  (one Action `Take_NN` per take, raw samples kept for re-baking with other smoothing), exports a take
  (viewport-render MP4, per-frame camera JSON, camera FBX), streams the camera view back to the phone.
- `ios/` — the iPhone app (SwiftUI + ARKit + Network.framework), built unsigned on GitHub Actions for SideStore.
- `protocol/` — protocol v1 (UDP pose packets + TCP JSON-line control) and golden fixtures both sides test against.
- `tools/fake_phone.py` — a stand-in phone (standard library only) for testing without an iPhone.

## Install

Download `Blendcam.ipa` and `blendcam_addon.zip` from the
[latest release](https://github.com/volchuk-1/blender-camera/releases/tag/latest).

1. iPhone: install `Blendcam.ipa` with SideStore; allow Camera and Local Network.
2. Blender 4.5: Edit → Preferences → Add-ons → Install from Disk → `blendcam_addon.zip`, enable it.
3. 3D View → sidebar (N) → Blendcam → Start, then scan the QR code shown in the viewport with the app.
   Allow Blender through the firewall on private networks.

## Develop

Add-on tests (background Blender):

    blender -b --factory-startup --python addon/tests/run.py

Window-only checks (viewport render / live view): `addon/tests/gui_panel.py`, `gui_export.py`, `gui_stream.py`
(`blender --factory-startup --python <script>`; each quits by itself and prints OK/FAIL).

The iOS project is generated with XcodeGen (`ios/project.yml`); CI runs the unit tests on a simulator and
publishes the `latest` release.

MIT license.
