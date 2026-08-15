---
name: edge-device
description: カメラとマイクを使うエッジセッションの手順。音声入力や撮影が必要なときに使う。
---

Edge device (PC or smartphone with camera/mic) must be connected to use these tools.

**Typical flow**:
1. Call `use_edgedevice` to switch to the edge session.
2. Call `get_image` to capture a camera frame (passed to vision model next turn).
3. Call `get_audio` to record mic audio and receive STT text.
4. Call `end_edge_session` when done to return to main session.

If the device is not connected, use_edgedevice will fail — inform the user accordingly.
