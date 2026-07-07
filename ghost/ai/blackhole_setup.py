"""BlackHole Setup — creates Multi-Output Device for lossless audio capture.

BlackHole is a virtual audio driver. We create a Multi-Output Device that sends
system audio to BOTH the speakers (you hear it) AND BlackHole (Ghost captures it).
Ghost then reads from BlackHole's input — pure interviewer audio, zero filtering needed.

Usage:
    from ghost.ai.blackhole_setup import setup_blackhole, find_blackhole_device_index
    bh_name = setup_blackhole()  # Creates Multi-Output Device
    idx = find_blackhole_device_index()  # For sounddevice capture
"""

import ctypes
import time
import objc
import numpy as np
from Foundation import NSDictionary, NSArray, NSString, NSNumber

# ── CoreAudio Types ──

AudioObjectID = ctypes.c_uint32
OSStatus = ctypes.c_int32
UInt32 = ctypes.c_uint32


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ('mSelector', UInt32),
        ('mScope', UInt32),
        ('mElement', UInt32),
    ]


# ── Four-char codes ──

def _fourcc(s):
    return int.from_bytes(s.encode('ascii'), 'big')


kAudioObjectSystemObject = 1
kAudioHardwarePropertyDevices = _fourcc('dev#')
kAudioObjectPropertyScopeGlobal = _fourcc('glob')
kAudioObjectPropertyElementMain = 0
kAudioDevicePropertyDeviceUID = _fourcc('uid ')
kAudioDevicePropertyDeviceNameCFString = _fourcc('lnam')
kAudioHardwarePropertyDefaultOutputDevice = _fourcc('dOut')
kAudioObjectPropertyScopeOutput = _fourcc('outp')
kAudioObjectPropertyScopeInput = _fourcc('inpt')
kAudioDevicePropertyStreams = _fourcc('stm#')

# ── Load CoreAudio ──

_ca = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreAudio.framework/CoreAudio'
)

_ca.AudioObjectGetPropertyDataSize.restype = OSStatus
_ca.AudioObjectGetPropertyDataSize.argtypes = [
    AudioObjectID, ctypes.POINTER(AudioObjectPropertyAddress),
    UInt32, ctypes.c_void_p, ctypes.POINTER(UInt32),
]

_ca.AudioObjectGetPropertyData.restype = OSStatus
_ca.AudioObjectGetPropertyData.argtypes = [
    AudioObjectID, ctypes.POINTER(AudioObjectPropertyAddress),
    UInt32, ctypes.c_void_p, ctypes.POINTER(UInt32), ctypes.c_void_p,
]

_ca.AudioHardwareCreateAggregateDevice.restype = OSStatus
_ca.AudioHardwareCreateAggregateDevice.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(AudioObjectID),
]

_ca.AudioHardwareDestroyAggregateDevice.restype = OSStatus
_ca.AudioHardwareDestroyAggregateDevice.argtypes = [AudioObjectID]

_ca.AudioObjectSetPropertyData.restype = OSStatus
_ca.AudioObjectSetPropertyData.argtypes = [
    AudioObjectID, ctypes.POINTER(AudioObjectPropertyAddress),
    UInt32, ctypes.c_void_p, UInt32, ctypes.c_void_p,
]


# ── Volume control ──
# macOS disables the system volume slider for a Multi-Output Device ('Ghost Audio'), so
# once Ghost switches output there, volume is frozen. Work around it by setting the volume
# of the underlying REAL output device (speakers/AirPods) directly via CoreAudio.
kAudioDevicePropertyVolumeScalar = _fourcc('volm')

_ca.AudioObjectHasProperty.restype = ctypes.c_bool
_ca.AudioObjectHasProperty.argtypes = [
    AudioObjectID, ctypes.POINTER(AudioObjectPropertyAddress),
]


def _volume_address(element):
    return AudioObjectPropertyAddress(
        kAudioDevicePropertyVolumeScalar, kAudioObjectPropertyScopeOutput, element)


def get_device_volume(device_id):
    """Device output volume 0.0-1.0 (master element, else channel 1), or None."""
    for element in (kAudioObjectPropertyElementMain, 1):
        addr = _volume_address(element)
        if not _ca.AudioObjectHasProperty(device_id, ctypes.byref(addr)):
            continue
        val = ctypes.c_float(0.0)
        size = UInt32(ctypes.sizeof(val))
        st = _ca.AudioObjectGetPropertyData(
            device_id, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(val))
        if st == 0:
            return float(val.value)
    return None


def set_device_volume(device_id, scalar):
    """Set a device's output volume 0.0-1.0 (master + both channels). True if any took."""
    scalar = max(0.0, min(1.0, float(scalar)))
    ok = False
    for element in (kAudioObjectPropertyElementMain, 1, 2):
        addr = _volume_address(element)
        if not _ca.AudioObjectHasProperty(device_id, ctypes.byref(addr)):
            continue
        val = ctypes.c_float(scalar)
        st = _ca.AudioObjectSetPropertyData(
            device_id, ctypes.byref(addr), 0, None,
            UInt32(ctypes.sizeof(val)), ctypes.byref(val))
        if st == 0:
            ok = True
    return ok


def nudge_output_volume(delta):
    """Bump the REAL output device (under 'Ghost Audio') by delta. Returns the new
    volume 0.0-1.0, or None if there's no controllable device."""
    device_id, _, _ = find_output_device()
    if not device_id:
        return None
    cur = get_device_volume(device_id)
    if cur is None:
        return None
    new = max(0.0, min(1.0, cur + delta))
    set_device_volume(device_id, new)
    return new


# ── Helper Functions ──

def _get_property_size(obj_id, selector, scope=kAudioObjectPropertyScopeGlobal):
    addr = AudioObjectPropertyAddress(selector, scope, kAudioObjectPropertyElementMain)
    size = UInt32(0)
    status = _ca.AudioObjectGetPropertyDataSize(
        obj_id, ctypes.byref(addr), 0, None, ctypes.byref(size)
    )
    return size.value if status == 0 else 0


def _get_all_device_ids():
    """Get all AudioObjectIDs."""
    size = _get_property_size(kAudioObjectSystemObject, kAudioHardwarePropertyDevices)
    if size == 0:
        return []
    count = size // ctypes.sizeof(AudioObjectID)
    ids = (AudioObjectID * count)()
    actual = UInt32(size)
    addr = AudioObjectPropertyAddress(
        kAudioHardwarePropertyDevices,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMain,
    )
    status = _ca.AudioObjectGetPropertyData(
        kAudioObjectSystemObject, ctypes.byref(addr),
        0, None, ctypes.byref(actual), ids,
    )
    if status != 0:
        return []
    return list(ids[:actual.value // ctypes.sizeof(AudioObjectID)])


def _get_device_uid(device_id):
    """Get the UID string of an audio device."""
    addr = AudioObjectPropertyAddress(
        kAudioDevicePropertyDeviceUID,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMain,
    )
    cf_str = ctypes.c_void_p()
    size = UInt32(ctypes.sizeof(ctypes.c_void_p))
    status = _ca.AudioObjectGetPropertyData(
        device_id, ctypes.byref(addr),
        0, None, ctypes.byref(size), ctypes.byref(cf_str),
    )
    if status != 0 or not cf_str.value:
        return None
    ns_str = objc.objc_object(c_void_p=cf_str)
    return str(ns_str)


def _get_device_name(device_id):
    """Get the name of an audio device."""
    addr = AudioObjectPropertyAddress(
        kAudioDevicePropertyDeviceNameCFString,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMain,
    )
    cf_str = ctypes.c_void_p()
    size = UInt32(ctypes.sizeof(ctypes.c_void_p))
    status = _ca.AudioObjectGetPropertyData(
        device_id, ctypes.byref(addr),
        0, None, ctypes.byref(size), ctypes.byref(cf_str),
    )
    if status != 0 or not cf_str.value:
        return None
    ns_str = objc.objc_object(c_void_p=cf_str)
    return str(ns_str)


def _get_default_output_device():
    """Get the default output device ID."""
    addr = AudioObjectPropertyAddress(
        kAudioHardwarePropertyDefaultOutputDevice,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMain,
    )
    device_id = AudioObjectID()
    size = UInt32(ctypes.sizeof(AudioObjectID))
    status = _ca.AudioObjectGetPropertyData(
        kAudioObjectSystemObject, ctypes.byref(addr),
        0, None, ctypes.byref(size), ctypes.byref(device_id),
    )
    return device_id.value if status == 0 else None


# ── Public API ──

def find_blackhole_device():
    """Find the BlackHole 2ch device. Returns (device_id, uid, name) or (None, None, None)."""
    for did in _get_all_device_ids():
        name = _get_device_name(did)
        if name and 'BlackHole' in name and '2ch' in name:
            return did, _get_device_uid(did), name
    return None, None, None


def find_output_device():
    """Find the current output device (AirPods, speakers, headphones, etc.).

    Detects whatever is currently the default output. If the default is already
    Ghost Audio or BlackHole, falls back to searching for a real audio device.
    Returns (device_id, uid, name) or (None, None, None).
    """
    # Try default output first (skip if it's already BlackHole or our aggregate)
    default_id = _get_default_output_device()
    if default_id:
        name = _get_device_name(default_id)
        if name and 'BlackHole' not in name and 'Ghost Audio' not in name:
            return default_id, _get_device_uid(default_id), name

    # Default is Ghost Audio or BlackHole — find a real output device
    # Priority: AirPods/Bluetooth > External headphones > Built-in speakers
    candidates = []
    for did in _get_all_device_ids():
        name = _get_device_name(did)
        uid = _get_device_uid(did)
        if not name or not uid:
            continue
        if 'BlackHole' in name or 'Ghost Audio' in name:
            continue
        # Check it has output streams
        size = _get_property_size(did, kAudioDevicePropertyStreams, kAudioObjectPropertyScopeOutput)
        if size == 0:
            continue
        candidates.append((did, uid, name))

    if not candidates:
        return None, None, None

    # Prefer AirPods/Bluetooth, then external, then built-in
    for did, uid, name in candidates:
        if 'AirPod' in name or 'Bluetooth' in name:
            return did, uid, name
    for did, uid, name in candidates:
        if 'External' in name or 'Headphone' in name or 'USB' in name:
            return did, uid, name
    for did, uid, name in candidates:
        if 'Speaker' in name or 'Built-in' in name or 'MacBook' in name:
            return did, uid, name

    # Return first candidate
    return candidates[0]


def destroy_ghost_audio():
    """Destroy any existing Ghost Audio aggregate device.

    Returns True if a device was destroyed, False otherwise.
    """
    for did in _get_all_device_ids():
        name = _get_device_name(did)
        if name == "Ghost Audio":
            status = _ca.AudioHardwareDestroyAggregateDevice(did)
            if status == 0:
                print(f"[BlackHole] Destroyed old Ghost Audio device (ID: {did})")
                return True
            else:
                print(f"[BlackHole] Warning: could not destroy old Ghost Audio (OSStatus {status})")
    return False


_GHOST_AUDIO_UID_PREFIX = "com.ghost.multioutput"


def ghost_audio_uid_for(output_uid: str) -> str:
    """The aggregate device UID we assign for a given output device.

    Embedding the output UID lets setup_blackhole() detect whether an existing
    'Ghost Audio' was built for the current output and reuse it rather than
    tearing it down (a teardown mid-session drops the call app back to raw
    speakers and BlackHole stops receiving the interviewer)."""
    return f"{_GHOST_AUDIO_UID_PREFIX}.{output_uid}"


def create_multi_output_device(output_uid, blackhole_uid):
    """Create a Multi-Output Device (output device + BlackHole).

    Args:
        output_uid: UID of the output device (speakers, AirPods, headphones, etc.)
        blackhole_uid: UID of the BlackHole 2ch device

    Returns the new device's AudioObjectID.
    """
    # PyObjC auto-bridges Python dict → NSDictionary, str → NSString, int → NSNumber.
    # The aggregate UID embeds the output device's UID so a later launch can tell
    # whether an existing 'Ghost Audio' was built for the CURRENT output device and
    # reuse it — instead of destroying + recreating it (which detaches whatever call
    # app had it selected and kills interviewer capture mid-session).
    desc = NSDictionary.dictionaryWithDictionary_({
        "name": "Ghost Audio",
        "uid": ghost_audio_uid_for(output_uid),
        "private": 0,
        "stacked": 1,  # Multi-output: same audio to all sub-devices
        "master": output_uid,
        "subdevices": [
            {"uid": output_uid},
            {"uid": blackhole_uid},
        ],
    })

    device_id = AudioObjectID()
    status = _ca.AudioHardwareCreateAggregateDevice(
        objc.pyobjc_id(desc), ctypes.byref(device_id),
    )
    if status != 0:
        raise RuntimeError(f"AudioHardwareCreateAggregateDevice failed: OSStatus {status}")

    return device_id.value


def get_default_output_device():
    """Return the current default output device id (to restore later)."""
    return _get_default_output_device()


def set_default_output_device(device_id):
    """Set the system default output device. Returns True on success."""
    addr = AudioObjectPropertyAddress(
        kAudioHardwarePropertyDefaultOutputDevice,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMain,
    )
    dev = AudioObjectID(device_id)
    status = _ca.AudioObjectSetPropertyData(
        kAudioObjectSystemObject, ctypes.byref(addr),
        0, None, ctypes.sizeof(AudioObjectID), ctypes.byref(dev),
    )
    return status == 0


def find_ghost_audio_device_id():
    """Return the AudioObjectID of the 'Ghost Audio' aggregate, or None."""
    for did in _get_all_device_ids():
        if _get_device_name(did) == "Ghost Audio":
            return did
    return None


def get_default_output_name():
    """Return the NAME of the current default output device (or None).

    Used by the mid-session output watchdog: if this stops being 'Ghost Audio'
    (e.g. AirPods reconnect silently switches the default), the interviewer's audio
    is no longer copied into BlackHole and capture goes dead — so we can catch it.
    """
    did = _get_default_output_device()
    if not did:
        return None
    return _get_device_name(did)


def is_output_routed_to_ghost() -> bool:
    """True if the system default output is currently 'Ghost Audio' (so system audio
    is being mirrored into BlackHole and the interviewer WILL be captured)."""
    return get_default_output_name() == "Ghost Audio"


def refresh_audio_device_list() -> bool:
    """Force PortAudio to rebuild its device table.
 
    sounddevice/PortAudio snapshots the device list ONCE at init and never
    refreshes it. After a device replug or reconfig (AirPods reconnect, the
    Ghost Audio aggregate rebuilt), find_blackhole_device_index() re-queries
    sd.query_devices() but gets the same stale snapshot back, so it can return
    a wrong or dead index. And that's exactly the moment the BlackHole stall
    watchdog fires, because the stall and the staleness have the same cause.
 
    WARNING: this tears down EVERY active sounddevice stream in the process,
    including a live MicCapture stream if one is running. Any other stream
    owner must be prepared to reopen itself afterwards. Only call this as a
    fallback after a normal reopen has already failed, never preemptively.
    """
    import sounddevice as sd
    try:
        sd._terminate()
        sd._initialize()
        return True
    except Exception as e:
        print(f"[BlackHole] PortAudio refresh failed: {e}")
        return False

def find_blackhole_device_index():
    """Find BlackHole 2ch device index for sounddevice capture.

    Returns the integer index or None.
    """
    import sounddevice as sd
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if 'BlackHole' in d['name'] and '2ch' in d['name'] and d['max_input_channels'] > 0:
            return i
    return None


def verify_blackhole_routing(test_duration: float = 0.45, freq: float = 660.0,
                             amplitude: float = 0.06):
    """Confirm audio sent to the default output ACTUALLY reaches BlackHole.

    This is the single most important pre-flight check: it plays a short, quiet
    tone to the current default output device while recording BlackHole's input.
    If BlackHole hears the tone, system audio is correctly routed into Ghost and
    the interviewer's voice WILL be captured. If BlackHole stays silent, the call
    audio is NOT reaching Ghost — the session would record pure silence (the exact
    failure that made Ghost "not work at all"). Catching it here, before the
    interview, lets the user fix routing instead of discovering it afterward.

    Returns (ok: bool, captured_rms: float). Never raises — returns (False, 0.0)
    on any error so it can never crash startup.
    """
    try:
        import sounddevice as sd
    except Exception:
        return False, 0.0

    bh_idx = find_blackhole_device_index()
    if bh_idx is None:
        return False, 0.0

    sr = 48000
    n = int(sr * test_duration)
    t = np.linspace(0, test_duration, n, False)
    mono = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    tone = np.column_stack([mono, mono])

    captured = []

    def _cb(indata, frames, time_info, status):
        captured.append(indata.copy())

    try:
        stream = sd.InputStream(device=bh_idx, samplerate=sr, channels=2,
                                dtype="float32", callback=_cb)
        stream.start()
        time.sleep(0.15)              # let the input stream settle
        sd.play(tone, samplerate=sr)  # → default output (= Ghost Audio)
        sd.wait()
        time.sleep(0.15)              # let the tail flush through
        stream.stop()
        stream.close()
    except Exception as e:
        print(f"[BlackHole] Routing self-test could not run: {e}")
        return False, 0.0

    if not captured:
        return False, 0.0
    a = np.concatenate(captured)
    rms = float(np.sqrt(np.mean(a ** 2)))
    return rms > 0.005, rms


def setup_blackhole():
    """Full setup: detect output device, create Multi-Output Device.

    Auto-detects whatever output device is active (AirPods, speakers, headphones).
    If Ghost Audio already exists but for a different output device, it destroys
    the old one and creates a new one with the current device.

    Returns the BlackHole device name for capture.
    Raises RuntimeError if BlackHole is not installed.
    """
    # Find BlackHole
    bh_id, bh_uid, bh_name = find_blackhole_device()
    if not bh_id:
        raise RuntimeError(
            "BlackHole 2ch not found. Install with: brew install blackhole-2ch"
        )
    print(f"[BlackHole] Found: {bh_name} (UID: {bh_uid})")

    # Find current output device (AirPods, speakers, headphones, etc.)
    out_id, out_uid, out_name = find_output_device()
    if not out_id:
        raise RuntimeError("Could not find any output audio device")
    print(f"[BlackHole] Output device: {out_name} (UID: {out_uid})")

    # Remember the current output so we can restore it on quit. Read it BEFORE we
    # touch anything (a reuse path still needs the pre-Ghost output to restore).
    prev_output_id = _get_default_output_device()
    # If the current default is already Ghost Audio (e.g. a prior run left it set),
    # "previous output" should be the real device we mirror to, not Ghost itself —
    # otherwise quit would restore output to a device that's about to be destroyed.
    if prev_output_id is not None and _get_device_name(prev_output_id) == "Ghost Audio":
        prev_output_id = out_id

    # Check whether a 'Ghost Audio' aggregate already exists — and whether it was
    # built for the CURRENT output device (its UID encodes that). If so, REUSE it:
    # rebuilding would detach any call app that has it selected and silently kill
    # interviewer capture — the exact mid-session failure we're fixing.
    expected_uid = ghost_audio_uid_for(out_uid)
    existing_ghost_id = None
    for did in _get_all_device_ids():
        if _get_device_name(did) == "Ghost Audio":
            existing_ghost_id = did
            break

    if existing_ghost_id is not None:
        existing_uid = _get_device_uid(existing_ghost_id)
        if existing_uid == expected_uid:
            # Same output device as before — keep it, just make sure it's the
            # default output so audio mirrors into BlackHole.
            print(f"[BlackHole] Reusing existing 'Ghost Audio' = {out_name} + BlackHole "
                  f"(ID: {existing_ghost_id}) — not rebuilding (keeps call apps attached).")
            if set_default_output_device(existing_ghost_id):
                print(f"[BlackHole] ✅ Output set to 'Ghost Audio' (you still hear via {out_name})")
            else:
                print("[BlackHole] ⚠️  Could not set output to 'Ghost Audio'. Set it manually:")
                print("[BlackHole]   System Settings → Sound → Output → Ghost Audio")
            print()
            return bh_name, prev_output_id
        # Built for a DIFFERENT output device (e.g. switched speakers→AirPods) —
        # it can't mirror the current output, so rebuild it.
        print(f"[BlackHole] Existing 'Ghost Audio' was for a different output; "
              f"rebuilding with {out_name}")
        destroy_ghost_audio()

    # Create Multi-Output Device with current output + BlackHole
    try:
        mo_id = create_multi_output_device(out_uid, bh_uid)
        print(f"[BlackHole] Created 'Ghost Audio' = {out_name} + BlackHole (ID: {mo_id})")
    except Exception as e:
        print(f"[BlackHole] Auto-create failed: {e}")
        print(f"[BlackHole] Create manually in Audio MIDI Setup:")
        print(f"[BlackHole]   1. Open Audio MIDI Setup (Cmd+Space → 'Audio MIDI')")
        print(f"[BlackHole]   2. Click '+' at bottom-left → Create Multi-Output Device")
        print(f"[BlackHole]   3. Check '{out_name}' and '{bh_name}'")
        raise

    # Auto-switch the system output to 'Ghost Audio' so the user doesn't have to
    # touch System Settings. Audio then plays to BOTH their device AND BlackHole.
    if set_default_output_device(mo_id):
        print(f"[BlackHole] ✅ Output auto-switched to 'Ghost Audio' (you still hear via {out_name})")
    else:
        print("[BlackHole] ⚠️  Could not auto-switch output. Set it manually:")
        print("[BlackHole]   System Settings → Sound → Output → Ghost Audio")
    print()

    return bh_name, prev_output_id
