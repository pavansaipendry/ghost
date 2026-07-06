"""Audio Capture Engine for Ghost AI.

Captures system audio from a target application (Zoom, Meet, Teams, Chrome, etc.)
using ProcTap (ScreenCaptureKit wrapper). Delivers 16kHz mono float32 audio
chunks suitable for Whisper.

Usage:
    capture = AudioCapture(target_app="zoom.us")
    capture.start(on_audio_chunk=my_callback)
    # callback receives numpy float32 array at 16kHz mono
    capture.stop()
"""

import subprocess
import threading
import time
import numpy as np


# Target sample rate for Whisper
WHISPER_SAMPLE_RATE = 16000


def find_pid_by_app(app_name: str) -> int | None:
    """Find the PID of a running application by name or bundle ID.

    Searches both process names and bundle identifiers.
    Examples: "zoom.us", "Google Chrome", "com.microsoft.teams"
    """
    try:
        # Search by process name
        result = subprocess.run(
            ["pgrep", "-i", "-f", app_name],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            return int(pids[0])
    except Exception:
        pass

    # Fallback: use lsappinfo to find by bundle ID
    try:
        result = subprocess.run(
            ["lsappinfo", "list"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            if app_name.lower() in line.lower():
                # Extract PID from the line
                for part in line.split():
                    if part.startswith("pid="):
                        return int(part.split("=")[1])
    except Exception:
        pass

    return None


def find_all_pids_by_app(app_name: str) -> list[int]:
    """Find ALL PIDs for an application (main process + helpers/renderers).

    Chrome, for example, spawns many renderer subprocesses. Google Meet audio
    comes from a renderer PID, not the main browser PID. We need all of them.
    """
    pids = []
    try:
        result = subprocess.run(
            ["pgrep", "-i", "-f", app_name],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                try:
                    pids.append(int(line.strip()))
                except ValueError:
                    pass
    except Exception:
        pass
    return pids


def list_audio_apps() -> list[dict]:
    """List running apps that commonly produce audio (meeting apps, browsers)."""
    common_apps = [
        ("zoom.us", "Zoom"),
        ("Google Chrome", "Chrome"),
        ("Safari", "Safari"),
        ("Microsoft Teams", "Teams"),
        ("Slack", "Slack"),
        ("Discord", "Discord"),
        ("Firefox", "Firefox"),
        ("Brave Browser", "Brave"),
        ("Arc", "Arc"),
    ]
    found = []
    for search, display_name in common_apps:
        pid = find_pid_by_app(search)
        if pid:
            found.append({"name": display_name, "search": search, "pid": pid})
    return found


class AudioCapture:
    """Captures audio from a specific application and delivers 16kHz mono chunks."""

    # ProcTap delivers 48kHz stereo float32
    _SOURCE_RATE = 48000
    _SOURCE_CHANNELS = 2

    # Don't bother flushing trailing fragments shorter than this on stop
    # (raw interleaved stereo samples; 4800 = 50ms of audio).
    _MIN_FLUSH_RAW_SAMPLES = 4800

    # Safety valve: if the chunk worker ever stalls or dies, cap the raw buffer
    # at ~30s of audio (~11.5 MB) and drop the oldest data instead of growing
    # until OOM. Under normal operation the buffer never gets near this.
    _MAX_BUFFER_RAW_SAMPLES = 48000 * 2 * 30

    def __init__(self, target_pid: int = None, target_app: str = None, chunk_duration: float = 0.5):
        """
        Args:
            target_pid: PID of the app to capture audio from.
            target_app: App name to search for (used if target_pid is None).
            chunk_duration: Duration of each audio chunk in seconds (default 0.5s).
        """
        self._target_pid = target_pid
        self._target_app = target_app
        self._chunk_duration = chunk_duration
        self._on_audio_chunk = None
        self._capture = None
        self._running = False

        # Raw 48kHz stereo audio. Stored as a LIST of arrays, not one big array:
        # the old np.concatenate-per-callback copied the entire buffer on every
        # ProcTap callback while holding the lock (O(n) per append). list.append
        # is O(1); the worker concatenates once per tick.
        self._raw_chunks: list[np.ndarray] = []
        self._raw_len = 0
        self._buffer_lock = threading.Lock()
        self._drop_warned = False

        self._chunk_thread = None
        self._debug_thread = None

        # Anti-alias filter state for stateful 48k -> 16k resampling.
        # Built in start(), carried across chunks by _resample_48k_to_16k.
        self._aa_taps = None
        self._aa_zi = None
        self._decim_phase = 0

    def start(self, on_audio_chunk=None):
        """Start capturing audio.

        Args:
            on_audio_chunk: Callback receiving numpy float32 array at 16kHz mono.
                           Called every chunk_duration seconds.
        """
        self._on_audio_chunk = on_audio_chunk

        # Resolve PID if needed
        if self._target_pid is None and self._target_app:
            self._target_pid = find_pid_by_app(self._target_app)
            if self._target_pid is None:
                raise RuntimeError(f"Could not find running app: {self._target_app}")

        if self._target_pid is None:
            raise RuntimeError("No target PID or app name specified")

        print(f"[AudioCapture] Starting capture for PID {self._target_pid}")

        # Build the anti-alias filter once. Matches what scipy.signal.decimate
        # would design for q=3 (FIR, 20*q+1 taps, cutoff 1/q), but we run it
        # ourselves with lfilter + carried state instead of per-chunk filtering.
        from scipy.signal import firwin
        self._aa_taps = firwin(61, 1.0 / 3, window="hamming")
        self._aa_zi = np.zeros(len(self._aa_taps) - 1)
        self._decim_phase = 0

        with self._buffer_lock:
            self._raw_chunks = []
            self._raw_len = 0
        self._drop_warned = False

        try:
            from proctap import ProcessAudioCapture
            self._capture = ProcessAudioCapture(
                pid=self._target_pid,
                on_data=self._on_raw_audio,
            )
            self._capture.start()
            self._running = True

            # Start chunk delivery thread
            self._chunk_thread = threading.Thread(target=self._chunk_worker, daemon=True)
            self._chunk_thread.start()

            # Debug: monitor audio flow
            self._debug_thread = threading.Thread(target=self._debug_monitor, daemon=True)
            self._debug_thread.start()

            print("[AudioCapture] Capture started successfully")
        except Exception as e:
            print(f"[AudioCapture] Failed to start: {e}")
            raise

    def stop(self):
        """Stop capturing audio."""
        self._running = False
        if self._capture:
            try:
                self._capture.stop()
            except Exception:
                pass
            self._capture = None

        # Join the worker so no chunk callback fires after stop() returns.
        # (Guard against being called FROM the callback, i.e. on the worker
        # thread itself, where joining would deadlock.)
        t = self._chunk_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=self._chunk_duration * 4)
        self._chunk_thread = None
        print("[AudioCapture] Capture stopped")

    def _on_raw_audio(self, data, frame_count):
        """Callback from ProcTap - MUST BE ULTRA-FAST.

        Just stores raw 48kHz stereo data. All conversion happens in _chunk_worker.
        """
        try:
            if isinstance(data, (bytes, bytearray)):
                if len(data) == 0:
                    return
                audio_data = np.frombuffer(data, dtype=np.float32)
            elif isinstance(data, np.ndarray):
                audio_data = data if data.dtype == np.float32 else data.astype(np.float32)
            else:
                return

            if len(audio_data) == 0:
                return

            with self._buffer_lock:
                self._raw_chunks.append(audio_data)
                self._raw_len += len(audio_data)
                # Safety valve: drop oldest data if the worker isn't draining.
                # ProcTap delivers whole stereo frames (even lengths), so
                # dropping whole entries preserves channel alignment.
                while self._raw_len > self._MAX_BUFFER_RAW_SAMPLES:
                    old = self._raw_chunks.pop(0)
                    self._raw_len -= len(old)
                    if not self._drop_warned:
                        self._drop_warned = True
                        print("[AudioCapture] ⚠️  Raw buffer hit cap - worker not "
                              "draining? Dropping oldest audio.")

        except Exception as e:
            print(f"[AudioCapture] Error in callback: {e}")

    def _resample_48k_to_16k(self, mono_48k: np.ndarray) -> np.ndarray:
        """48kHz mono -> 16kHz mono. Stateful, safe on any input length.

        Single-pass FIR lowpass via lfilter with carried filter state (zi),
        then keep every 3rd sample with the decimation phase carried across
        chunks. Two bugs in the old per-chunk decimate(zero_phase=True) die here:

        1. On scipy versions where the FIR zero-phase path goes through filtfilt,
           inputs shorter than ~183 samples raise ValueError - which escaped
           _chunk_worker's loop, silently killed the worker thread, and left the
           raw buffer growing forever. lfilter has no minimum length; a 1-sample
           chunk is fine, on every scipy version.
        2. Filtering each 0.5s chunk independently left edge transients at every
           chunk boundary (a discontinuity every 0.5s in what the recognizer
           hears). Carrying zi makes the filter behave as if it ran over one
           continuous stream - no boundary artifacts at all.
        """
        from scipy.signal import lfilter
        filtered, self._aa_zi = lfilter(self._aa_taps, 1.0, mono_48k, zi=self._aa_zi)
        out = filtered[self._decim_phase::3]
        # Next chunk starts len(mono_48k) samples later in the global stream;
        # keep picking samples at the same global stride-3 positions.
        self._decim_phase = (self._decim_phase - len(mono_48k)) % 3
        return out.astype(np.float32)

    def _process_and_deliver(self, raw_chunk: np.ndarray):
        """Deinterleave -> resample -> deliver. NEVER lets an exception escape
        into _chunk_worker's loop (that's what killed the worker before)."""
        try:
            # Interleaved stereo -> mono. Caller guarantees even length.
            mono = raw_chunk.reshape(-1, 2).mean(axis=1)
            chunk = self._resample_48k_to_16k(mono)
        except Exception as e:
            print(f"[AudioCapture] Resample error (chunk dropped): {e}")
            return

        if self._on_audio_chunk is None or len(chunk) == 0:
            return
        try:
            self._on_audio_chunk(chunk)
        except Exception as e:
            print(f"[AudioCapture] Chunk callback error: {e}")

    def _debug_monitor(self):
        """Periodically log buffer status for debugging."""
        count = 0
        while self._running and count < 20:
            time.sleep(0.5)
            with self._buffer_lock:
                buf_len = self._raw_len
            if buf_len > 0:
                # Raw buffer is 48kHz stereo, so divide by 2*48000 for seconds
                secs = buf_len / (self._SOURCE_RATE * self._SOURCE_CHANNELS)
                print(f"[AudioCapture] Buffer: {buf_len} raw samples ({secs:.1f}s)")
            else:
                print(f"[AudioCapture] Buffer: empty (no audio received)")
            count += 1

    def _chunk_worker(self):
        """Periodically takes raw 48kHz stereo, resamples to 16kHz mono, delivers.

        Only full chunks are delivered mid-stream; anything shorter stays in
        `carry` and merges with the next tick's data (the old code delivered
        partial fragments every tick, which fragmented the audio AND fed the
        resampler the short inputs that could crash it). The final remainder is
        flushed once on stop so trailing words aren't lost.
        """
        raw_chunk_samples = int(self._SOURCE_RATE * self._SOURCE_CHANNELS * self._chunk_duration)
        if raw_chunk_samples % 2:
            raw_chunk_samples += 1  # keep stereo frame alignment

        carry = np.empty(0, dtype=np.float32)

        while self._running:
            time.sleep(self._chunk_duration)

            # Swap the list out under the lock; concatenate OUTSIDE the lock so
            # the ProcTap callback never waits on a big memcpy.
            with self._buffer_lock:
                grabbed, self._raw_chunks = self._raw_chunks, []
                self._raw_len = 0

            if grabbed:
                parts = ([carry] if len(carry) else []) + grabbed
                carry = parts[0] if len(parts) == 1 else np.concatenate(parts)

            while self._running and len(carry) >= raw_chunk_samples:
                raw_chunk = carry[:raw_chunk_samples]
                carry = carry[raw_chunk_samples:]
                self._process_and_deliver(raw_chunk)

        # Stopping: flush the remainder (at most ~one chunk). Trim to an even
        # length in case the source ever split a stereo frame across callbacks.
        usable = (len(carry) // 2) * 2
        if usable >= self._MIN_FLUSH_RAW_SAMPLES:
            self._process_and_deliver(carry[:usable])


class MicCapture:
    """Captures microphone audio for voice sample recording and speaker diarization.

    start_continuous has a stall watchdog for the same reason BlackHoleCapture
    does, plus one more: BlackHoleCapture's recovery path can call
    refresh_audio_device_list(), which tears down EVERY PortAudio stream in the
    process, including this one. Without a watchdog here, the user-voice mic
    stream would die silently the moment that refresh fires and stay dead for
    the rest of the session. With it, the mic notices its callbacks stopped and
    reopens itself within a few seconds. The two watchdogs are deliberately
    complementary: BlackHole owns the aggressive recovery (including the
    refresh), the mic just self-heals from whatever fallout reaches it.
    """

    _STALL_SECONDS = 3.0

    def __init__(self, sample_rate: int = WHISPER_SAMPLE_RATE, channels: int = 1):
        self._sample_rate = sample_rate
        self._channels = channels
        self._recording = False
        self._stream = None
        self._on_audio_chunk = None
        self._chunk_duration = 0.5
        self._last_callback = 0.0
        self._watchdog = None
        # Same open/teardown serialization as BlackHoleCapture: without it,
        # stop_continuous() racing a watchdog reopen can leak a live stream.
        self._stream_lock = threading.Lock()

    def record_voice_sample(self, duration: float = 5.0) -> np.ndarray:
        """Record a voice sample from the microphone for speaker diarization.

        Args:
            duration: Duration in seconds to record.

        Returns:
            numpy float32 array of the recorded audio at 16kHz mono.
        """
        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError("sounddevice not installed. Run: pip install sounddevice")

        print(f"[MicCapture] Recording voice sample for {duration}s... Speak now!")
        audio = sd.rec(
            int(duration * self._sample_rate),
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
        )
        sd.wait()
        print("[MicCapture] Voice sample recorded")
        return audio.flatten()

    def _callback(self, indata, frames, time_info, status):
        # Any callback, even a silent buffer, proves the stream is alive.
        self._last_callback = time.time()
        if self._recording and self._on_audio_chunk:
            self._on_audio_chunk(indata[:, 0].copy().astype(np.float32))

    def _open_stream(self) -> bool:
        """(Re)open the mic input stream on the default input device.

        Returns True if a stream is now running, False if it aborted because
        recording was stopped. Raises on genuine open failures.
        """
        import sounddevice as sd

        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            if not self._recording:
                return False

            chunk_samples = int(self._sample_rate * self._chunk_duration)
            stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="float32",
                blocksize=chunk_samples,
                callback=self._callback,
            )
            stream.start()

            if not self._recording:
                # stop_continuous() ran while we were opening; don't leak.
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                return False

            self._stream = stream
            self._last_callback = time.time()
            return True

    def start_continuous(self, on_audio_chunk=None, chunk_duration: float = 0.5):
        """Start continuous mic recording (for tracking what the user says)."""
        try:
            import sounddevice as sd  # noqa: F401 - surface a clear error if missing
        except ImportError:
            raise RuntimeError("sounddevice not installed. Run: pip install sounddevice")

        self._on_audio_chunk = on_audio_chunk
        self._chunk_duration = chunk_duration
        self._recording = True
        try:
            self._open_stream()
        except Exception:
            self._recording = False
            raise

        self._watchdog = threading.Thread(target=self._watch_stall, daemon=True)
        self._watchdog.start()
        print("[MicCapture] Continuous recording started")

    def _watch_stall(self):
        """Reopen the mic stream if callbacks stop (device switch, PortAudio
        refresh triggered by BlackHoleCapture's recovery, CoreAudio glitch)."""
        while self._recording:
            time.sleep(1.0)
            if not self._recording:
                break
            gap = time.time() - self._last_callback
            if gap < self._STALL_SECONDS:
                continue
            print(f"[MicCapture] ⚠️  No mic callback for {gap:.1f}s - stream stalled. Reopening…")
            try:
                if self._open_stream():
                    print("[MicCapture] ✅ Mic stream reopened.")
                # False means stop won the race; loop condition exits us.
            except Exception as e:
                # No device-list refresh here on purpose: BlackHoleCapture owns
                # that hammer. If it fires one, our next reopen attempt sees the
                # fresh list. Two components both calling _terminate/_initialize
                # would just knock each other's streams over in a loop.
                print(f"[MicCapture] Mic reopen failed ({e}); retrying…")

    def stop_continuous(self):
        """Stop continuous mic recording."""
        # Flag first (watchdog exits, in-flight reopen aborts), then teardown.
        self._recording = False
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
        print("[MicCapture] Continuous recording stopped")


class BlackHoleCapture:
    """Captures audio from BlackHole 2ch virtual device.

    BlackHole receives a copy of all system audio via the Multi-Output Device.
    This stream contains ONLY the interviewer's voice (your voice never enters it).
    No filtering, no classification, no errors.
    """

    # If the sounddevice callback stops firing for this long while we're supposed to
    # be recording, CoreAudio has dropped/reconfigured the device (AirPods reconnect,
    # the aggregate got rebuilt, a glitch). The stream is dead and never recovers on
    # its own - so a watchdog reopens it. Callbacks normally arrive every
    # chunk_duration (~0.5s), so a few seconds of silence from the callback is a
    # reliable stall signal.
    _STALL_SECONDS = 3.0

    # After this many consecutive failed reopens, assume PortAudio's cached device
    # list is stale (it snapshots devices once at init and never refreshes) and
    # force-refresh it before the next attempt.
    _REFRESH_AFTER_FAILURES = 2

    def __init__(self, sample_rate: int = WHISPER_SAMPLE_RATE, channels: int = 2):
        self._sample_rate = sample_rate
        self._channels = channels
        self._recording = False
        self._stream = None
        self._device_index = None
        self._on_audio_chunk = None
        self._chunk_duration = 0.5
        self._last_callback = 0.0
        self._watchdog = None
        # Serializes stream open/teardown between the watchdog thread and stop().
        # Without it: stop() closes the stream while the watchdog is mid-reopen,
        # the watchdog then starts a NEW stream after _recording=False, and that
        # zombie stream fires callbacks forever with nothing to ever stop it.
        self._stream_lock = threading.Lock()

    def _find_device(self):
        """Find BlackHole 2ch device index."""
        from ghost.ai.blackhole_setup import find_blackhole_device_index
        idx = find_blackhole_device_index()
        if idx is None:
            raise RuntimeError(
                "BlackHole 2ch not found. Install with: brew install blackhole-2ch"
            )
        return idx

    def _callback(self, indata, frames, time_info, status):
        # Any callback - even a silent buffer - proves the stream is alive.
        self._last_callback = time.time()
        if status:
            print(f"[BlackHoleCapture] Status: {status}")
        if self._recording and self._on_audio_chunk:
            # Convert stereo to mono if needed, deliver as float32
            if indata.shape[1] > 1:
                mono = indata.mean(axis=1).astype(np.float32)
            else:
                mono = indata[:, 0].copy().astype(np.float32)
            self._on_audio_chunk(mono)

    def _open_stream(self) -> bool:
        """(Re)open the BlackHole input stream. Safe to call for restart.

        Returns True if a stream is now running, False if it aborted because
        recording was stopped. Raises on genuine open failures (device missing,
        PortAudio errors) so start() surfaces a clear error and the watchdog
        can count failures.
        """
        import sounddevice as sd

        with self._stream_lock:
            # Tear down any prior stream first.
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            # stop() may have run while we were waiting on the lock.
            if not self._recording:
                return False

            self._device_index = self._find_device()
            chunk_samples = int(self._sample_rate * self._chunk_duration)
            stream = sd.InputStream(
                device=self._device_index,
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="float32",
                blocksize=chunk_samples,
                callback=self._callback,
            )
            stream.start()

            # Re-check: if stop() set the flag while we were opening, don't
            # leave a live stream behind that nothing will ever close.
            if not self._recording:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                return False

            self._stream = stream
            self._last_callback = time.time()
            return True

    def start(self, on_audio_chunk=None, chunk_duration: float = 0.5):
        """Start capturing from BlackHole.

        Args:
            on_audio_chunk: Callback receiving numpy float32 array at 16kHz mono.
            chunk_duration: Duration per chunk in seconds.
        """
        try:
            import sounddevice as sd  # noqa: F401 - surface a clear error if missing
        except ImportError:
            raise RuntimeError("sounddevice not installed. Run: pip install sounddevice")

        self._on_audio_chunk = on_audio_chunk
        self._chunk_duration = chunk_duration
        self._recording = True
        try:
            self._open_stream()
        except Exception:
            self._recording = False
            raise
        print(f"[BlackHoleCapture] Capturing from BlackHole 2ch (device {self._device_index})")

        # Stall watchdog: reopen the stream if the callback stops firing.
        self._watchdog = threading.Thread(target=self._watch_stall, daemon=True)
        self._watchdog.start()

    def _watch_stall(self):
        """Reopen the stream if the callback goes quiet - CoreAudio dropped it."""
        failures = 0
        while self._recording:
            time.sleep(1.0)
            if not self._recording:
                break
            gap = time.time() - self._last_callback
            if gap < self._STALL_SECONDS:
                failures = 0
                continue

            print(f"[BlackHoleCapture] ⚠️  No audio callback for {gap:.1f}s - the BlackHole "
                  f"stream stalled (device drop/reconfig). Reopening…")
            try:
                if self._open_stream():
                    print("[BlackHoleCapture] ✅ Stream reopened - interviewer capture restored.")
                    failures = 0
                # False means stop() won the race; the loop condition exits us.
            except Exception as e:
                failures += 1
                print(f"[BlackHoleCapture] Reopen failed ({e}); retrying…")

                if failures >= self._REFRESH_AFTER_FAILURES:
                    # PortAudio snapshots the device list at init and never
                    # refreshes it, so after a replug the "BlackHole" index we
                    # find can be stale/wrong - precisely the moment the
                    # watchdog fires. Force a rescan.
                    #
                    # WARNING: refresh_audio_device_list() tears down every
                    # active sounddevice stream in the process. MicCapture's
                    # continuous stream dies too - its own watchdog reopens it
                    # within a few seconds. Our own dead stream is torn down as
                    # well; _open_stream's guarded teardown handles that.
                    try:
                        from ghost.ai.blackhole_setup import refresh_audio_device_list
                        print("[BlackHoleCapture] Refreshing PortAudio device list…")
                        refresh_audio_device_list()
                        failures = 0
                    except Exception as re:
                        print(f"[BlackHoleCapture] Device list refresh failed: {re}")

    def stop(self):
        """Stop capturing."""
        # Order matters: flag first (so the watchdog exits and any in-flight
        # _open_stream aborts), THEN take the lock and tear down. If a reopen is
        # mid-flight we block here until it finishes; its post-start check sees
        # _recording=False and closes its own stream, so nothing leaks.
        self._recording = False
        with self._stream_lock:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
        print("[BlackHoleCapture] Stopped")