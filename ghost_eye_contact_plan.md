# Ghost Eye-Contact Layer — Build Plan

**Goal:** While you read the Ghost panel, your eyes should look like they're on the camera.
Ghost hides the *text*; this hides the *reading*.

**Status:** Planned 2026-07-01, revised same day after soundness review. Not yet built.

**v2 revisions (soundness review):** (1) pyvirtualcam↔OBS path CONFIRMED viable, no longer an
unknown; (2) warp magnitude quantified at 1–2 px → stabilizer is a prerequisite, not polish;
(3) the dominant tell at this geometry is horizontal READING SACCADES, not the static angle →
new Phase 0: teleprompter layout. Details inline below.

---

## Core architecture (settled)

We do **not** touch Zoom/Meet/Teams. We present a **virtual camera** the call app selects
once and never changes. We own what flows into it frame by frame.

```
Real FaceTime camera ──▶ capture (AVFoundation) ──▶ engine loop ──┬─▶ toggle OFF: raw frame
                                                                   └─▶ toggle ON : gaze-corrected frame
                                                        └────────────────────▶ pyvirtualcam ──▶ "OBS Virtual Camera" ──▶ Zoom
```

### Why this is feasible on THIS machine
- macOS 26.2 killed CoreMediaIO **DAL** plugins (the old virtual-cam mechanism). The only
  native path is a signed **CoreMediaIO Camera Extension** — normally a Swift/ObjC system
  extension needing Developer ID + entitlements + notarization.
- **We don't build one.** OBS's Camera Extension is ALREADY installed and activated on this
  machine (`com.obsproject.obs-studio.mac-camera-extension`, v32.1.2). We drive it from
  Python via `pyvirtualcam`, whose macOS backend writes frames into that exact extension.
- Everything stays in the existing Python stack. `AVFoundation`, `Quartz`, `numpy`, `Vision`
  are already in the venv.

### The one invariant that must never break
**One camera, two modes.** The call app sees a single, unbroken 30fps device the entire call.
The toggle is an `if` in our loop — no device swap, no reconnect, no flicker. When OFF we send
the **raw captured frame verbatim** (same resolution/format/orientation, zero processing) so
passthrough and corrected mode are byte-for-byte identical except the eyes. If passthrough were
"the pipeline with correction disabled," subtle latency/sharpness differences would themselves
become a tell.

---

## The gaze problem is TINY here (decides the model)

Reading panel sits ~1 inch (2.54 cm) below the lens. At a 40–60 cm viewing distance:

- correction angle = arctan(2.54 / 50) ≈ **~3°** (range ~2.4°–3.6°).
- in pixels: 3° rotates the iris ~0.6 mm ≈ **1–2 px at 720p** (face ~400 px wide). The warp is
  trivially artifact-free at this size — but the pupil-position *signal* is the same 1–2 px,
  i.e. at Vision's landmark noise floor. **The stabilizer is a prerequisite, not polish.**

**Consequence:** ~3° is the trivial end of gaze redirection — a few pixels of iris shift.
- **No learned model.** A geometric iris warp (Vision landmarks → warp iris up ~3° → feather)
  is enough, runs sub-millisecond, costs ~0 extra memory. The DeepWarp/Core ML path only earns
  its keep at 12–20°, which we designed away by pinning the panel under the lens.
- At this magnitude the raw redirection is the *easy* part. The tells shift to **secondary
  artifacts** (temporal shimmer, blinks, catchlights) — so that's where the engineering care goes.
- **Correction target for v1: lock to the lens** (reads as confident eye contact). Revisit
  "match natural talking gaze" only if lens-lock looks too intense in real footage.
- Overshoot note: a fixed calibrated delta means genuinely looking at the lens renders as ~3°
  *above* it — imperceptible for the same reason the original 3° drift nearly is. Accept it;
  gaze-zone gating isn't feasible at a 1–2 px signal anyway.

## THE DOMINANT TELL: reading saccades, not the angle (v2 finding)

Through a webcam (compression, small tile), the detection threshold for static down-gaze is
~5°+ — so the 3° offset is *close to invisible even uncorrected*. What actually reads as
"he's reading" is the **rhythmic left→right saccade sweep** along text lines: a ~10 cm-wide
panel at 50 cm = **±5.7° horizontal — roughly double the vertical angle we're correcting**.
The iris warp preserves saccades perfectly; alone it would ship eyes that "hold contact"
while visibly scanning text.

**Fix is layout, not ML — Phase 0, highest realism-per-effort in the plan:**
- **Teleprompter mode** in the Ghost web view: narrow column (~5–6 cm visual width), centered
  under the lens, **auto-scrolling the streamed answer through a fixed focal point** so the
  eyes fixate one spot instead of sweeping lines. Real teleprompters use exactly this design
  for exactly this reason. Pure UI change; no new dependencies.
- Optional experiment later: horizontal saccade damping in the warp (pull iris-x toward the
  calibrated lens position while reading). Risky — overdone it reads as dead/frozen eyes.
- Honest limit: blink rate drops while reading — a behavioral tell no warp fixes (user
  awareness, not software).

---

## Hardware budget (hard constraint)

**M1 MacBook Air, 8 GB.** During a real call the machine is also running Zoom's video encode
+ the entire Ghost audio→STT→Claude stack. Memory pressure, not compute, is the ceiling.
- 720p30 pipeline (not 1080p) to keep buffers small.
- No ML model in v1 → no coremltools, no model weights resident.
- Never freeze the virtual cam. If the engine can't keep up → **degrade to passthrough**, never
  drop to a frozen frame (a frozen feed is a giant tell).

---

## Module layout (new package, V1 untouched)

New sibling package `ghost/eyecontact/` (audio AI stays in `ghost/ai/`):

| File | Responsibility |
|------|----------------|
| `camera_source.py` | AVFoundation capture of the real FaceTime camera → latest-frame numpy (BGRA→RGB), 720p30, drop stale frames. |
| `virtual_cam.py`   | `pyvirtualcam` sink wrapper → OBS extension. Matches capture res/fps exactly. Loud error if extension unbound. |
| `landmarks.py`     | Vision `VNDetectFaceLandmarksRequest`: per-eye pupil center, eye region, eye-openness (blink), detection confidence. |
| `iris_warp.py`     | Build a per-eye displacement (flow) field peaking at the pupil (by calibrated delta), decaying to the eye-contour boundary; `cv2.remap`; feather back into frame. |
| `stabilizer.py`    | One-Euro / EMA smoothing of landmarks + applied displacement (kills shimmer); ramp correction 0→full on toggle. |
| `corrector.py`     | Orchestrates `gaze_correct(frame)`: landmarks → gate (blink/low-conf/head-turn → passthrough) → warp → composite. |
| `engine.py`        | Threaded main loop: capture → toggle → corrector/passthrough → send; paces fps; exposes `start/stop/set_enabled/toggle/calibrate` + health callbacks. |
| `calibration.py`   | Capture pupil position looking-at-lens vs looking-at-panel → store per-eye delta to config; recalibrate command. |

**Dependencies to add:** `pyvirtualcam`, `opencv-python-headless` (for `cv2.remap`). Vision /
AVFoundation / Quartz / numpy already present. No coremltools.

---

## The warp, concretely

- **Calibrate, don't compute angles.** Have the user look at the lens (capture pupil `P_cam`)
  and at the panel (`P_read`). The needed correction is exactly the vector `P_cam − P_read`
  per eye. No eyeball model, personalized, robust. Persist it; recalibrate on demand.
- **Warp, don't paste.** Construct a displacement field over each eye's bounding box: a
  Gaussian-weighted shift centered on the pupil (magnitude = calibrated delta, radius ≈ iris
  radius) decaying to zero at the eye contour, masked to the eye opening so eyelids don't drag.
  Apply with `cv2.remap`. At ~3° the revealed sclera stretch is imperceptible — that's the whole
  reason the small angle is a gift.
- **Blink passthrough.** eye-openness < threshold → leave that eye untouched. Warping a closing
  eye looks like a horror film.
- **Fallback.** No face / low confidence / head turned beyond threshold → return the raw frame.
  Briefly looking away naturally beats one glitched frame.

---

## Wiring into Ghost (entry.py)

- **Toggle hotkey:** double-tap **Right-Shift** (modifier-only → inserts no character, same
  stealth-keystroke rule as double-tap Right-Option = answer-now and Right-Command = HUD).
  Routed through the existing `AIKeyListener`.
- **Lifecycle:** engine starts at app launch in **passthrough** (toggle off) so the virtual cam
  is already live video when the user picks "OBS Virtual Camera" in Zoom. Toggle only flips
  correction on/off; the device never restarts.
- **Status UI:** small indicator in the Ghost web UI — eye-contact ON/OFF + camera/extension
  health — reusing the audio meters/banner pattern. Loud banner if the extension is unbound or
  camera permission is missing (mirrors the audio routing-banner philosophy).
- **Kill switch:** existing kill path also stops the engine and **releases the real camera** so
  the camera LED goes off (a stuck-on camera light after a call is itself a tell). Only hold the
  camera while the feature is active.

---

## Known gotchas / honesty notes

- **pyvirtualcam ↔ OBS binding: CONFIRMED viable (v2).** pyvirtualcam 0.14+ explicitly supports
  the modern OBS 30+ Camera Extension on macOS 13+ (ours is OBS 32.1.2 ✓; pyvirtualcam actively
  maintained into 2026). OBS does NOT need to be running at send time. One-time setup ritual:
  (a) approve the extension in System Settings → Login Items & Extensions → Camera Extensions
  (currently `activated waiting for user`), (b) open OBS once, Start then Stop Virtual Camera,
  close OBS. The Phase-1 spike remains — macOS 26.2 is newer than anything documented — but
  it's now "confirm," not "discover." Fallback if it breaks: build/sign our own Camera
  Extension (heavy Swift path).
- **Camera permission:** Ghost has never used the camera; first run triggers a Camera permission
  prompt (needs `NSCameraUsageDescription`). Handle + surface it.
- **Don't select the real camera in Zoom** — the user selects "OBS Virtual Camera". We hold the
  real one.
- **Don't mirror.** Send the camera's true orientation (Zoom mirrors your self-view locally but
  sends un-mirrored to others). Passthrough must preserve orientation exactly.
- **Camera LED is on while we capture** — unavoidable (hardwired to camera use) and fine: you're
  on a video call, it's supposed to be on. Just don't capture outside calls.
- **OBS itself and our app can't drive the extension at once** — never run both.

---

## Build order (each phase independently verifiable)

0. **Teleprompter layout (v2 — do first, biggest realism win).** Narrow auto-scrolling answer
   column pinned under the lens in the Ghost web view. Kills the saccade tell before any video
   work exists; useful on its own even if the camera layer slips.
1. **Plumbing spike (confirm pyvirtualcam↔OBS on macOS 26.2).** One-time extension approval +
   OBS start/stop ritual, then `camera_source` + `virtual_cam` + `engine` **passthrough only**,
   no correction. Verify: select "OBS Virtual Camera" in a browser getUserMedia test /
   Photo Booth, see your real video via Ghost at 720p30, low latency.
2. **Detection + calibration.** `landmarks` + blink + `calibration`, with a dev overlay drawing
   pupils. Prove the smoothed pupil signal is stable at the 1–2 px scale and the calibrated
   delta is sane. No warp yet.
3. **Correction.** `iris_warp` + `stabilizer` + `corrector`. Add the real ~3° warp with temporal
   smoothing + blink passthrough + fallback. Tune on recorded reading footage.
4. **App integration.** Toggle hotkey, status UI, lifecycle, kill switch, permission/extension
   banners.
5. **Realism + real-call validation.** Blind A/B (corrected vs passthrough) on recorded reading
   clips; profile the frame budget with Zoom + the AI stack live; harden fallbacks; real dry-run.

---

## How we know it's good enough

Not "looks fine in a screenshot" — **"an attentive interviewer can't tell across a 45-minute
call while the whole stack is running."** Validation is blind A/B on real reading footage plus a
frame-budget profile with Zoom + audio/AI pipeline live, never in isolation.
