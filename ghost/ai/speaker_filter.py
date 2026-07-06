"""Speaker Filter for Ghost AI.

Simple voice fingerprinting to distinguish the user's voice from the interviewer's.
Uses spectral features (MFCCs) to create a voice profile, then filters out
audio chunks that match the user's voice.

Usage:
    # Record voice sample
    filter = SpeakerFilter()
    filter.enroll_user(voice_sample)  # numpy float32, 16kHz mono

    # Check if a chunk is the user speaking
    is_user = filter.is_user_speaking(audio_chunk)
"""

import numpy as np
import threading


WHISPER_SAMPLE_RATE = 16000


def compute_mfcc(audio: np.ndarray, sample_rate: int = WHISPER_SAMPLE_RATE, n_mfcc: int = 13, n_fft: int = 512, hop_length: int = 160) -> np.ndarray:
    """Compute MFCC features from audio using numpy only (no librosa dependency).

    Args:
        audio: float32 audio array
        sample_rate: sample rate in Hz
        n_mfcc: number of MFCC coefficients to return
        n_fft: FFT window size
        hop_length: hop length between frames

    Returns:
        MFCCs as numpy array of shape (n_mfcc, n_frames)
    """
    # Pre-emphasis
    emphasized = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])

    # Frame the signal
    num_frames = 1 + (len(emphasized) - n_fft) // hop_length
    if num_frames <= 0:
        return np.zeros((n_mfcc, 1))

    frames = np.zeros((num_frames, n_fft))
    for i in range(num_frames):
        start = i * hop_length
        frames[i] = emphasized[start:start + n_fft]

    # Apply Hamming window
    window = np.hamming(n_fft)
    frames *= window

    # FFT and power spectrum
    fft_result = np.fft.rfft(frames, n=n_fft)
    power_spectrum = np.abs(fft_result) ** 2 / n_fft

    # Mel filterbank
    n_filters = 26
    low_freq = 0
    high_freq = sample_rate / 2
    low_mel = 2595 * np.log10(1 + low_freq / 700)
    high_mel = 2595 * np.log10(1 + high_freq / 700)
    mel_points = np.linspace(low_mel, high_mel, n_filters + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

    filterbank = np.zeros((n_filters, n_fft // 2 + 1))
    for i in range(n_filters):
        for j in range(bin_points[i], bin_points[i + 1]):
            if bin_points[i + 1] != bin_points[i]:
                filterbank[i, j] = (j - bin_points[i]) / (bin_points[i + 1] - bin_points[i])
        for j in range(bin_points[i + 1], bin_points[i + 2]):
            if bin_points[i + 2] != bin_points[i + 1]:
                filterbank[i, j] = (bin_points[i + 2] - j) / (bin_points[i + 2] - bin_points[i + 1])

    # Apply filterbank
    mel_spectrum = np.dot(power_spectrum, filterbank.T)
    mel_spectrum = np.where(mel_spectrum == 0, np.finfo(float).eps, mel_spectrum)
    log_mel = np.log(mel_spectrum)

    # DCT to get MFCCs
    n_mel = log_mel.shape[1]
    dct_matrix = np.zeros((n_mfcc, n_mel))
    for k in range(n_mfcc):
        for n in range(n_mel):
            dct_matrix[k, n] = np.cos(np.pi * k * (2 * n + 1) / (2 * n_mel))
    dct_matrix *= np.sqrt(2.0 / n_mel)

    mfccs = np.dot(log_mel, dct_matrix.T).T  # shape: (n_mfcc, n_frames)
    return mfccs


class SpeakerFilter:
    """Filters audio to distinguish between user and interviewer voices."""

    def __init__(self, threshold: float = 0.65):
        """
        Args:
            threshold: Similarity threshold (0-1). Above this = user speaking.
                      Default 0.65 balances false positives/negatives.
        """
        self._threshold = threshold
        self._user_profile = None  # Mean MFCC vector
        self._user_std = None      # Std of MFCC for adaptive thresholding
        self._enrolled = False
        self._lock = threading.Lock()

    @property
    def is_enrolled(self) -> bool:
        return self._enrolled

    def enroll_user(self, voice_sample: np.ndarray):
        """Create a voice profile from a voice sample.

        Args:
            voice_sample: numpy float32 array at 16kHz mono, 3-10 seconds of the user speaking.
        """
        if len(voice_sample) < WHISPER_SAMPLE_RATE:
            raise ValueError("Voice sample too short. Need at least 1 second.")

        mfccs = compute_mfcc(voice_sample)

        with self._lock:
            self._user_profile = np.mean(mfccs, axis=1)  # Average across frames
            self._user_std = np.std(mfccs, axis=1)
            self._enrolled = True

        print(f"[SpeakerFilter] User enrolled. Profile shape: {self._user_profile.shape}")

    def is_user_speaking(self, audio_chunk: np.ndarray) -> bool:
        """Check if the audio chunk sounds like the enrolled user.

        Args:
            audio_chunk: numpy float32 array at 16kHz mono

        Returns:
            True if the user is likely speaking, False if it's someone else.
        """
        if not self._enrolled:
            return False

        # Skip very short or silent chunks
        if len(audio_chunk) < 1600:  # < 0.1s
            return False

        energy = np.sqrt(np.mean(audio_chunk ** 2))
        if energy < 0.005:
            return False  # Silence

        mfccs = compute_mfcc(audio_chunk)
        chunk_profile = np.mean(mfccs, axis=1)

        with self._lock:
            similarity = self._cosine_similarity(self._user_profile, chunk_profile)

        return similarity > self._threshold

    def get_similarity(self, audio_chunk: np.ndarray) -> float:
        """Get the similarity score between the chunk and the user's voice profile.

        Returns:
            Similarity score 0-1. Higher = more similar to user.
        """
        if not self._enrolled:
            return 0.0

        energy = np.sqrt(np.mean(audio_chunk ** 2))
        if energy < 0.005:
            return 0.0

        mfccs = compute_mfcc(audio_chunk)
        chunk_profile = np.mean(mfccs, axis=1)

        with self._lock:
            return self._cosine_similarity(self._user_profile, chunk_profile)

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    def save_profile(self, path: str):
        """Save the voice profile to disk."""
        if not self._enrolled:
            raise RuntimeError("No profile to save. Enroll first.")
        with self._lock:
            np.savez(path, profile=self._user_profile, std=self._user_std)
        print(f"[SpeakerFilter] Profile saved to {path}")

    def load_profile(self, path: str):
        """Load a voice profile from disk."""
        data = np.load(path)
        with self._lock:
            self._user_profile = data["profile"]
            self._user_std = data["std"]
            self._enrolled = True
        print(f"[SpeakerFilter] Profile loaded from {path}")
