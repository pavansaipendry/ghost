"""AES-256-GCM encryption using a room code as passphrase."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

_SALT = b"ghost-chat-v1"
_ITERATIONS = 100_000
_KEY_LENGTH = 32  # 256 bits
_IV_LENGTH = 12   # 96 bits, recommended for GCM
_TAG_LENGTH = 16  # 128 bits, appended by AESGCM


def derive_key(room_code: str) -> bytes:
    """Derive a 256-bit key from a room code using PBKDF2-HMAC-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=_SALT,
        iterations=_ITERATIONS,
    )
    return kdf.derive(room_code.encode("utf-8"))


def encrypt(plaintext: str, room_code: str) -> str:
    """Encrypt plaintext with AES-256-GCM using the room code.

    Returns a base64-encoded string containing iv + ciphertext + tag.
    Thread-safe: all state is local.
    """
    key = derive_key(room_code)
    iv = os.urandom(_IV_LENGTH)
    aesgcm = AESGCM(key)
    # AESGCM.encrypt returns ciphertext + tag (16 bytes) concatenated
    ct_with_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(iv + ct_with_tag).decode("ascii")


def decrypt(payload: str, room_code: str) -> str:
    """Decrypt a base64 payload produced by encrypt().

    Splits the decoded bytes into iv (12) | ciphertext | tag (16) and
    decrypts with AES-256-GCM.  Thread-safe: all state is local.
    """
    raw = base64.b64decode(payload)
    iv = raw[:_IV_LENGTH]
    ct_with_tag = raw[_IV_LENGTH:]
    key = derive_key(room_code)
    aesgcm = AESGCM(key)
    plaintext_bytes = aesgcm.decrypt(iv, ct_with_tag, None)
    return plaintext_bytes.decode("utf-8")
