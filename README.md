# Blendcam

Use an iPhone (ARKit world tracking) as a handheld camera for Blender 4.5.

- `addon/blendcam/` — Blender add-on: receives the phone pose over the local Wi-Fi, drives the scene camera,
  records takes into keyframes, exports takes (mp4 / JSON / FBX).
- `ios/` — the iPhone app (SwiftUI + ARKit), built on GitHub Actions.
- `protocol/` — protocol v1 description and golden fixtures shared by both sides.
- `tools/fake_phone.py` — a stand-in phone for testing without an iPhone.

Local network only. MIT license.
