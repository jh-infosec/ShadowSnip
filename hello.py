"""Unlocking an encrypted lab with Windows Hello (0.18.0).

Opt-in, per lab and per PC: **Unlock with Windows Hello on this PC** in the
tray menu while the lab is unlocked. After that, the unlock window asks
Windows Hello (face, fingerprint or PIN) first, and the password is still
there underneath.

## How the key is kept

Windows Hello can hold a private key that never leaves the TPM and is only
usable after Hello verifies you (`KeyCredentialManager`). ShadowSnip asks it
to sign a random challenge kept for the lab. An RSA signature of the same
data with the same key is always the same, so that signature, through HKDF,
gives the same 256-bit key every time, and only after Hello: that key wraps
the lab's data key, and the wrapped copy is stored in
`%LOCALAPPDATA%\\ShadowSnip\\hello\\<lab id>.json`. Nothing in that file opens
the lab without this PC's TPM and your Hello sign-in, and copying the lab
folder elsewhere takes none of it along. The same approach is used by
password managers' Hello plug-ins.

If Hello is reset, the TPM cleared, or the PC changed, the stored copy simply
stops working and the password (or recovery key) opens the lab as before.
Changing the lab's password does not affect it, since the data key does not
change. Decrypting the lab, or turning Hello off for it, deletes the file.

## Testing

Everything but the signing is ordinary Python, so the tests swap `signer`
for a stand-in that signs deterministically with HMAC. The real signer only
exists on Windows 10 and later with the winrt packages.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

CREDENTIAL_NAME = "ShadowSnip lab keys"
FORMAT = 1
_INFO = b"ShadowSnip Windows Hello lab key"


class HelloError(OSError):
    pass


class HelloCancelled(HelloError):
    pass


def store_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ShadowSnip" / "hello"


def _record_path(lab_id: str) -> Path:
    safe = "".join(ch for ch in str(lab_id) if ch.isalnum() or ch == "-")[:64]
    return store_dir() / f"{safe}.json"


# -- the signer -----------------------------------------------------------------------------------
def _run(coroutine_factory, timeout: float = 120.0, pump: bool = True):
    """Run a WinRT async call to completion on a worker thread, keeping the Qt UI
    responsive (`pump`) while Hello's own window is up."""
    import asyncio

    box: dict = {}

    def work():
        try:
            box["value"] = asyncio.run(coroutine_factory())
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller
            box["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop

        app = QCoreApplication.instance() if pump else None
    except ImportError:
        app = None
    waited = 0.0
    while thread.is_alive() and waited < timeout:
        if app is not None:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        thread.join(0.05)
        waited += 0.1
    if thread.is_alive():
        raise HelloError("Windows Hello did not answer.")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _winrt():
    try:
        from winrt.windows.security.credentials import (
            KeyCredentialCreationOption,
            KeyCredentialManager,
            KeyCredentialStatus,
        )
        from winrt.windows.security.cryptography import CryptographicBuffer
    except ImportError as exc:
        raise HelloError("Windows Hello needs the winrt-Windows.Security.Credentials package.") from exc
    return KeyCredentialManager, KeyCredentialCreationOption, KeyCredentialStatus, CryptographicBuffer


def _bytes(buffer) -> bytes:
    """An IBuffer's bytes, across pywinrt versions."""
    try:
        return bytes(memoryview(buffer))
    except TypeError:
        _m, _o, _s, crypto = _winrt()
        return bytes(crypto.copy_to_byte_array(buffer))


def windows_sign(challenge: bytes) -> bytes:
    """Sign with this user's Windows Hello key, making it the first time. Shows Hello's prompt."""
    manager, option, status, crypto = _winrt()

    async def sign():
        if not await manager.is_supported_async():
            raise HelloError("Windows Hello is not set up on this PC.")
        opened = await manager.open_async(CREDENTIAL_NAME)
        if opened.status != status.SUCCESS:
            opened = await manager.request_create_async(CREDENTIAL_NAME, option.FAIL_IF_EXISTS)
            if opened.status == status.CREDENTIAL_ALREADY_EXISTS:
                opened = await manager.open_async(CREDENTIAL_NAME)
        if opened.status == status.USER_CANCELED:
            raise HelloCancelled("Windows Hello was cancelled.")
        if opened.status != status.SUCCESS:
            raise HelloError(f"Windows Hello could not be used ({opened.status}).")
        signed = await opened.credential.request_sign_async(bytes(challenge))   # a ReadableBuffer
        if signed.status == status.USER_CANCELED:
            raise HelloCancelled("Windows Hello was cancelled.")
        if signed.status != status.SUCCESS:
            raise HelloError(f"Windows Hello did not sign ({signed.status}).")
        return _bytes(signed.result)

    return _run(sign)


def windows_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        manager, _option, _status, _crypto = _winrt()
    except HelloError:
        return False

    async def check():
        return bool(await manager.is_supported_async())

    try:
        return bool(_run(check, timeout=10, pump=False))
    except Exception:  # noqa: BLE001 - not available, whatever the reason
        return False


# The function that signs: Windows Hello, or a stand-in in the tests.
signer = windows_sign
_available = None


def available() -> bool:
    """Whether Windows Hello can be offered here (asked once)."""
    global _available
    if signer is not windows_sign:
        return True
    if _available is None:
        _available = windows_available()
    return _available


# -- keeping a lab's key ----------------------------------------------------------------------------
def _wrap_key(signature: bytes, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    if len(signature) < 32:
        raise HelloError("Windows Hello gave back too short a signature.")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=_INFO).derive(signature)


def is_enrolled(lab_id: str) -> bool:
    return bool(lab_id) and _record_path(lab_id).is_file()


def enroll(lab_id: str, data_key: bytes) -> None:
    """Keep a copy of the lab's data key that Windows Hello opens. Shows Hello's prompt."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    challenge, salt, nonce = os.urandom(32), os.urandom(16), os.urandom(12)
    key = _wrap_key(signer(challenge), salt)
    # A second signature must match the first, or this signer cannot be used.
    if _wrap_key(signer(challenge), salt) != key:
        raise HelloError("Windows Hello's key does not sign the same way twice, so it cannot hold the lab key.")
    record = {
        "format": FORMAT, "lab": lab_id,
        "challenge": base64.b64encode(challenge).decode(), "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "data": base64.b64encode(AESGCM(key).encrypt(nonce, data_key, lab_id.encode())).decode(),
    }
    path = _record_path(lab_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(temp, path)


def data_key(lab_id: str) -> bytes:
    """The lab's data key, after Windows Hello. Raises HelloError (HelloCancelled)."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        record = json.loads(_record_path(lab_id).read_text(encoding="utf-8"))
        challenge = base64.b64decode(record["challenge"])
        salt = base64.b64decode(record["salt"])
        nonce = base64.b64decode(record["nonce"])
        blob = base64.b64decode(record["data"])
    except (OSError, ValueError, KeyError) as exc:
        raise HelloError("Windows Hello is not set up for this lab on this PC.") from exc
    key = _wrap_key(signer(challenge), salt)
    try:
        return AESGCM(key).decrypt(nonce, blob, lab_id.encode())
    except InvalidTag as exc:
        raise HelloError("Windows Hello's key has changed since this lab was set up for it. "
                         "Use the password, then turn Windows Hello on again.") from exc


def forget(lab_id: str) -> None:
    try:
        _record_path(lab_id).unlink()
    except OSError:
        pass
