"""
Voice lock for Jarvis: learns YOUR voice and ignores everyone else.

voice.py imports VoiceRecognitionAgent from this file and uses:
    available, has_voice, lock_active, set_lock(on), enroll(clips), check(audio, sr), forget_voice()

Needs:  pip install resemblyzer --no-deps   and   pip install torch
(see the notes Jarvis gave you; webrtcvad-wheels, librosa, numpy and scipy are already in requirements.txt)

The heavy libraries (torch, the speaker model) are only loaded the first time they are needed, so
Jarvis starts as fast as before when no voice is registered.
"""
import importlib
import importlib.util
import os
import threading

from safe_pickle import load_numpy_pickle

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
VOICE_PROFILE_FILE = os.path.join(BASE, "known_voice.pkl")
SIMILARITY_THRESHOLD = 0.75   # cosine similarity needed to count as you. Lower = more forgiving.
MIN_SECONDS = 0.8             # clips shorter than this can't be judged reliably, so they are let through


class VoiceRecognitionAgent:
    def __init__(self):
        self.known_features = None
        self.threshold = SIMILARITY_THRESHOLD
        self._lock_on = False
        self._encoder = None
        self._preprocess = None
        self._mutex = threading.Lock()
        # checked once, without importing torch: just "is it installed?"
        self._avail = all(importlib.util.find_spec(n) is not None for n in ("resemblyzer", "torch"))
        self._load()

    # ------------------------------------------------------------------ state
    @property
    def available(self):
        return self._avail

    @property
    def has_voice(self):
        return self.known_features is not None

    @property
    def lock_active(self):
        # If the user enabled the lock, missing dependencies/profile must not silently disable it.
        return self._lock_on

    def set_lock(self, on):
        self._lock_on = bool(on)
        if self.has_voice:
            self._save()

    # ------------------------------------------------------------ persistence
    def _load(self):
        if not os.path.exists(VOICE_PROFILE_FILE):
            return
        try:
            data = load_numpy_pickle(VOICE_PROFILE_FILE, max_bytes=1_000_000)
            if not isinstance(data, dict):
                raise ValueError("voice profile must be a dictionary")
            self._lock_on = bool(data.get("lock", False))
            feats = data.get("features")
            if feats is not None:
                feats = np.asarray(feats, dtype=np.float32).reshape(-1)
                if feats.size != 256 or not np.isfinite(feats).all():
                    raise ValueError("voice profile has invalid embedding data")
                n = float(np.linalg.norm(feats))
                self.known_features = feats / n if n > 0 else None
        except Exception as e:
            # A present but unreadable profile must not silently turn off an enabled lock.
            self._lock_on = True
            print(f"Error loading voice profile: {e}")

    def _save(self):
        tmp = VOICE_PROFILE_FILE + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump({"features": self.known_features, "lock": self._lock_on}, f)
        os.replace(tmp, VOICE_PROFILE_FILE)

    def forget_voice(self):
        self.known_features = None
        self._lock_on = False
        try:
            if os.path.exists(VOICE_PROFILE_FILE):
                os.remove(VOICE_PROFILE_FILE)
        except Exception as e:
            print(f"Couldn't delete the voice profile: {e}")

    # -------------------------------------------------------------- embedding
    def _ensure_models(self):
        if self._encoder is None:
            r = importlib.import_module("resemblyzer")
            self._preprocess = r.preprocess_wav
            self._encoder = r.VoiceEncoder(device="cpu", verbose=False)

    def _embed(self, audio, sr=16000):
        """Unit-length 256-number voice print of one clip (float audio, -1..1), or None if too short."""
        with self._mutex:
            self._ensure_models()
            wav = self._preprocess(np.asarray(audio, dtype=np.float32).reshape(-1), source_sr=sr)
            if len(wav) < int(16000 * MIN_SECONDS):
                return None
            emb = self._encoder.embed_utterance(wav)
        n = float(np.linalg.norm(emb))
        return (emb / n).astype(np.float32) if n > 0 else None

    # ------------------------------------------------------------- the API
    def enroll(self, clips):
        """Averages several spoken clips into one voice print and turns the lock on. -> (ok, message)"""
        if not self._avail:
            return False, "resemblyzer and torch are not installed."
        embs = []
        for clip in clips:
            try:
                e = self._embed(clip, 16000)
            except Exception as ex:
                return False, f"The voice model failed to load: {ex}"
            if e is not None:
                embs.append(e)
        if len(embs) < 2:
            return False, "I couldn't pick up enough clear speech. Try again somewhere quieter."
        mean = np.mean(embs, axis=0)
        n = float(np.linalg.norm(mean))
        if n <= 0:
            return False, "I couldn't build a voice print from those clips."
        self.known_features = (mean / n).astype(np.float32)
        self._lock_on = True
        self._save()
        return True, f"Voice print saved from {len(embs)} clips."

    def check(self, audio, sr=16000):
        """Is this clip you? -> (accepted, score or None, note).

        Once the user enables the lock, unavailable models, inference errors and clips
        too short to classify are rejected rather than silently accepted.
        """
        if not self._lock_on:
            return True, None, "lock off"
        if not self._avail:
            return False, None, "voice model unavailable; rejected"
        if not self.has_voice:
            return False, None, "voice profile unavailable; rejected"
        try:
            emb = self._embed(audio, sr)
        except Exception as e:
            return False, None, f"check failed ({e}); rejected"
        if emb is None:
            return False, None, "too short to judge; rejected"
        score = float(np.dot(emb, self.known_features))
        ok = score >= self.threshold
        return ok, score, "your voice" if ok else "different voice"