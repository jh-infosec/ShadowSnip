"""Encrypted labs (0.16.0): every file in the lab folder encrypted at rest.

## What it protects

A lab folder holds screenshots of hashes, passwords, keys and client data.
Encrypted, the folder is unreadable without the lab's password: on a laptop
that is lost or stolen, in a folder a sync client uploads, or in a backup.
Nothing is decrypted to the lab folder, ever; ShadowSnip decrypts into memory
as it reads. It does not protect against someone who can run code as you
while the lab is unlocked (they can read ShadowSnip's memory, or your
screen), and the clipboard is plain as always.

## Keys

    password  --scrypt-->  password key  --AES-GCM unwraps-->  data key
    recovery key  --HKDF-->  recovery key'  --AES-GCM unwraps-->  data key

Each lab has its own random 256-bit **data key**, which encrypts the files.
It is stored twice in `lab.key`, wrapped (encrypted) once with a key derived
from the password (scrypt, N=2^17, r=8, p=1: about 128 MB and a fraction of a
second, so guessing is slow) and once with the **recovery key**, 160 random
bits shown once as 8 groups of 4 letters and digits. Either one opens the
lab. Changing the password re-wraps the data key; the files are untouched.

`lab.key` itself holds no secret that works without the password or the
recovery key. It stays plain text, as does the labs folder's `.gitignore`.

## Files

Each file is `MAGIC + nonce (12) + AES-256-GCM ciphertext and tag`, with the
lab's id as associated data, so a file copied in from another lab fails
to open rather than opening wrongly. A damaged or altered file fails
the tag check and is reported, never shown half-read. Names stay as they
are: the folder still shows `004_2026-11-18_10-23-00.png`, which keeps every
part of ShadowSnip that finds files by name working unchanged. That leaks
how many snips there are and when they were taken, not what is in them.

Files are told apart by content (the magic), not by name, so a lab half way
through being encrypted (power cut, say) still opens: plain files read as
they are, and running Encrypt this lab again finishes the job.

## Reading and writing

`storage.write_atomic` asks `guard()` about every path: inside an unlocked
lab, the bytes are encrypted before they are written; inside a locked one,
the write is refused (`Locked`), so a plain file can never be written over
an encrypted lab by a code path that forgot to ask. Readers use `read()`,
`load_image()`, `image_size()` and `media_source()` here instead of opening
files themselves.

## Handing a file to another program

Another program cannot read an encrypted file. When you ask for exactly that
(Copy clip as a file, Open, Play in video player), a decrypted copy is made
in a private temporary folder (`handoff()`), which is wiped when the lab is
locked, stopped, or ShadowSnip quits. The lab folder itself is never touched.
A recording is written by Qt to that folder too, then encrypted into the lab.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import tempfile
import uuid
from pathlib import Path

MAGIC = b"SSVAULT1"
KEY_NAME = "lab.key"
# Never encrypted: the key file and git's ignore list.
PLAIN_NAMES = frozenset({KEY_NAME, ".gitignore"})
FORMAT = 1
NONCE = 12
# scrypt cost. The tests lower SCRYPT_N; real labs use 2^17.
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
RECOVERY_GROUPS = 8
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I, O, 0, 1
MIN_PASSWORD = 8


class VaultError(OSError):
    """Something about an encrypted lab, with what to do about it."""


class Locked(VaultError):
    """An encrypted lab that has not been unlocked."""


class WrongKey(VaultError):
    """The password or recovery key does not open this lab."""


class Damaged(VaultError):
    """A file that fails its integrity check."""


def _aes():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:   # pragma: no cover - requirements.txt has it
        raise VaultError("Encrypted labs need the cryptography package: pip install cryptography") from exc
    return AESGCM


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(str(text).encode("ascii"), validate=True)


def available() -> bool:
    try:
        _aes()
    except VaultError:
        return False
    return True


# -- deriving keys ------------------------------------------------------------------------------
def _password_key(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    import hashlib

    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          maxmem=256 * 1024 * 1024, dklen=32)


def normalise_recovery(text: str) -> str:
    """A recovery key as typed (any case, spaces or dashes) to its canonical form."""
    # The alphabet has no I, O, 0 or 1, so look-alikes cannot be mistyped.
    return "".join(ch for ch in str(text or "").upper() if ch.isalnum())


def _recovery_key(recovery: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=b"ShadowSnip lab recovery").derive(normalise_recovery(recovery).encode("ascii"))


def new_recovery_key() -> str:
    """Eight groups of four from a 32-letter alphabet: 160 bits, easy to copy by hand."""
    letters = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(4 * RECOVERY_GROUPS))
    return "-".join(letters[i:i + 4] for i in range(0, len(letters), 4))


def _wrap(key: bytes, secret: bytes, aad: bytes) -> dict:
    nonce = os.urandom(NONCE)
    return {"nonce": _b64(nonce), "data": _b64(_aes()(key).encrypt(nonce, secret, aad))}


def _unwrap(key: bytes, wrapped: dict, aad: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag

    try:
        return _aes()(key).decrypt(_unb64(wrapped["nonce"]), _unb64(wrapped["data"]), aad)
    except (InvalidTag, KeyError, ValueError, TypeError) as exc:
        raise WrongKey("That does not open this lab.") from exc


# -- the open labs --------------------------------------------------------------------------------
class Vault:
    """An unlocked lab: its folder, id and data key, held in memory only."""

    def __init__(self, folder: Path, lab_id: str, key: bytes):
        self.folder = Path(folder).resolve()
        self.lab_id = lab_id
        self._key = key
        self._aad = lab_id.encode("utf-8")
        self._handoff: Path | None = None

    def encrypt(self, data: bytes) -> bytes:
        nonce = os.urandom(NONCE)
        return MAGIC + nonce + _aes()(self._key).encrypt(nonce, bytes(data), self._aad)

    def decrypt(self, blob: bytes, name: str = "") -> bytes:
        from cryptography.exceptions import InvalidTag

        if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + NONCE + 16:
            raise Damaged(f"{name or 'A file'} is not a complete encrypted file.")
        body = blob[len(MAGIC):]
        try:
            return _aes()(self._key).decrypt(body[:NONCE], body[NONCE:], self._aad)
        except InvalidTag as exc:
            raise Damaged(f"{name or 'A file'} is damaged or belongs to another lab, so it was not opened.") from exc

    def handoff_dir(self) -> Path:
        if self._handoff is None or not self._handoff.is_dir():
            self._handoff = Path(tempfile.mkdtemp(prefix="shadowsnip-"))
        return self._handoff

    def wipe_handoff(self) -> None:
        if self._handoff is not None:
            shutil.rmtree(self._handoff, ignore_errors=True)
            self._handoff = None

    def forget(self) -> None:
        self.wipe_handoff()
        self._key = b""


_open: dict[Path, Vault] = {}


def _key_path(folder: Path) -> Path:
    return Path(folder) / KEY_NAME


def is_encrypted_lab(folder) -> bool:
    return folder is not None and _key_path(folder).is_file()


def is_unlocked(folder) -> bool:
    return folder is not None and Path(folder).resolve() in _open


def vault_for(path) -> Vault | None:
    """The unlocked lab a path lies in, if any."""
    if not _open or path is None:
        return None
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    for parent in (resolved, *resolved.parents):
        found = _open.get(parent)
        if found is not None:
            return found
    return None


def _encrypted_root(path: Path, depth: int = 3) -> Path | None:
    """The encrypted lab folder a path lies in (looking up to `depth` levels), unlocked or not."""
    try:
        parent = Path(path).resolve().parent
    except OSError:
        return None
    for _ in range(depth):
        if _key_path(parent).is_file():
            return parent
        if parent.parent == parent:
            break
        parent = parent.parent
    return None


def guard(path, data: bytes) -> bytes:
    """What to write at `path`: encrypted inside an unlocked lab, as given elsewhere.

    Raises Locked for a path inside an encrypted lab that is not unlocked, so
    nothing can write a plain file over it.
    """
    path = Path(path)
    if path.name in PLAIN_NAMES or path.name.endswith(".tmp"):
        return data
    found = vault_for(path)
    if found is not None:
        return found.encrypt(data)
    if _encrypted_root(path) is not None:
        raise Locked(f"{path.parent.name} is an encrypted lab and is locked.")
    return data


def is_encrypted_file(path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def decode(path, blob: bytes) -> bytes:
    """`blob`, read from `path`, as plain bytes."""
    if not blob.startswith(MAGIC):
        return blob
    found = vault_for(path)
    if found is None:
        raise Locked(f"{Path(path).name} is in an encrypted lab that is locked.")
    return found.decrypt(blob, Path(path).name)


def read(path) -> bytes:
    """A file's contents, decrypted if it is encrypted. Raises OSError (Locked, Damaged)."""
    path = Path(path)
    return decode(path, path.read_bytes())


def read_text(path, encoding: str = "utf-8") -> str:
    return read(path).decode(encoding)


def load_image(path):
    """A QImage from a file, encrypted or not. A null QImage when unreadable."""
    from PySide6.QtGui import QImage

    if not path:
        return QImage()
    path = Path(path)
    if not is_encrypted_file(path):
        return QImage(str(path))
    try:
        data = read(path)
    except OSError:
        return QImage()
    image = QImage()
    image.loadFromData(data)
    return image


def image_reader(path):
    """A QImageReader for a file, encrypted or not, and the buffer it reads from (keep it alive)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageReader

    path = Path(path)
    if not is_encrypted_file(path):
        return QImageReader(str(path)), None
    try:
        data = read(path)
    except OSError:
        data = b""
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    return reader, buffer


def image_size(path):
    """A picture's size without decoding it all (a QSize; invalid when unreadable)."""
    reader, _buffer = image_reader(path)
    return reader.size()


def media_source(player, path) -> None:
    """Point a QMediaPlayer at a file, decrypting into memory when it is encrypted.

    The buffer is kept on the player, so it lives as long as the player reads it.
    """
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl

    path = Path(path)
    if not is_encrypted_file(path):
        player._vault_buffer = None
        player.setSource(QUrl.fromLocalFile(str(path)))
        return
    buffer = QBuffer(player)
    buffer.setData(QByteArray(read(path)))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    player._vault_buffer = buffer
    player.setSourceDevice(buffer, QUrl.fromLocalFile(str(path)))


def handoff(path) -> Path:
    """A file another program can open: the file itself, or a decrypted copy in a private temp folder."""
    path = Path(path)
    if not is_encrypted_file(path):
        return path
    found = vault_for(path)
    if found is None:
        raise Locked(f"{path.name} is in an encrypted lab that is locked.")
    target = found.handoff_dir() / path.name
    target.write_bytes(found.decrypt(path.read_bytes(), path.name))
    return target


def scratch(path) -> Path | None:
    """For a file Qt must write itself (a recording, a trim): where to write it first.

    Inside an unlocked lab, a path in the private temp folder; the caller
    then encrypts it into place with `seal()`. None outside a lab.
    """
    found = vault_for(path)
    if found is None:
        return None
    return found.handoff_dir() / Path(path).name


def seal(plain: Path, target: Path) -> None:
    """Encrypt a plain file into place in its lab, then delete the plain one."""
    import storage

    storage.write_atomic(Path(target), Path(plain).read_bytes())
    try:
        Path(plain).unlink()
    except OSError:
        pass


# -- setting up, unlocking, changing ----------------------------------------------------------------
def password_problem(password: str, again: str | None = None) -> str:
    """Why a new password will not do, or '' when it will."""
    if len(password or "") < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if again is not None and password != again:
        return "The two passwords are not the same."
    return ""


def create(folder, password: str) -> str:
    """Make `folder` an encrypted lab with this password. Returns the recovery key.

    Only the key file is written here; `encrypt_folder()` then encrypts what
    is already in the folder. The lab is left unlocked.
    """
    folder = Path(folder)
    if is_encrypted_lab(folder):
        raise VaultError("This lab is encrypted already.")
    problem = password_problem(password)
    if problem:
        raise VaultError(problem)
    lab_id = str(uuid.uuid4())
    data_key = _aes().generate_key(bit_length=256)
    recovery = new_recovery_key()
    record = _record(lab_id, data_key, password, recovery)
    _write_key(folder, record)
    _open[folder.resolve()] = Vault(folder, lab_id, data_key)
    return recovery


def _record(lab_id: str, data_key: bytes, password: str, recovery: str) -> dict:
    aad = lab_id.encode("utf-8")
    salt = os.urandom(16)
    recovery_salt = os.urandom(16)
    return {
        "format": FORMAT,
        "id": lab_id,
        "cipher": "AES-256-GCM",
        "password": {"kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": _b64(salt),
                     **_wrap(_password_key(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P), data_key, aad)},
        "recovery": {"kdf": "hkdf-sha256", "salt": _b64(recovery_salt),
                     **_wrap(_recovery_key(recovery, recovery_salt), data_key, aad)},
    }


def _write_key(folder: Path, record: dict) -> None:
    import storage

    storage.write_atomic(_key_path(folder), json.dumps(record, indent=2).encode("utf-8"))


def _read_key(folder: Path) -> dict:
    try:
        record = json.loads(_key_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VaultError(f"{KEY_NAME} could not be read: {exc}") from exc
    if not isinstance(record, dict) or record.get("format") != FORMAT or "id" not in record:
        raise VaultError(f"{KEY_NAME} is not one this version of ShadowSnip can read.")
    return record


def _data_key(record: dict, password: str | None, recovery: str | None) -> bytes:
    aad = str(record["id"]).encode("utf-8")
    if recovery:
        part = record.get("recovery") or {}
        try:
            salt = _unb64(part["salt"])
        except (KeyError, ValueError) as exc:
            raise VaultError(f"{KEY_NAME} has no usable recovery entry.") from exc
        return _unwrap(_recovery_key(recovery, salt), part, aad)
    part = record.get("password") or {}
    try:
        salt, n, r, p = _unb64(part["salt"]), int(part["n"]), int(part["r"]), int(part["p"])
    except (KeyError, ValueError, TypeError) as exc:
        raise VaultError(f"{KEY_NAME} has no usable password entry.") from exc
    if not (2 ** 10 <= n <= 2 ** 20 and 1 <= r <= 32 and 1 <= p <= 16):
        raise VaultError(f"{KEY_NAME} asks for scrypt settings outside what ShadowSnip uses.")
    return _unwrap(_password_key(password or "", salt, n, r, p), part, aad)


def unlock(folder, password: str | None = None, recovery: str | None = None) -> Vault:
    """Open an encrypted lab with its password or recovery key. Raises WrongKey."""
    folder = Path(folder)
    record = _read_key(folder)
    key = _data_key(record, password, recovery)
    vault = Vault(folder, str(record["id"]), key)
    _open[folder.resolve()] = vault
    return vault


def lock(folder) -> None:
    """Forget the lab's key and wipe its temporary copies."""
    if folder is None:
        return
    found = _open.pop(Path(folder).resolve(), None)
    if found is not None:
        found.forget()


def lock_all() -> None:
    for folder in list(_open):
        lock(folder)


def change_password(folder, new_password: str, old_password: str | None = None,
                    recovery: str | None = None) -> str:
    """Set a new password (with the old one or the recovery key). Returns a new recovery key.

    The data key stays the same, so no file is rewritten; a fresh recovery
    key is made too, since the old one may be what was used to get in.
    """
    folder = Path(folder)
    problem = password_problem(new_password)
    if problem:
        raise VaultError(problem)
    record = _read_key(folder)
    key = _data_key(record, old_password, recovery)
    fresh = new_recovery_key()
    _write_key(folder, _record(str(record["id"]), key, new_password, fresh))
    _open[folder.resolve()] = Vault(folder, str(record["id"]), key)
    return fresh


def rewrap(folder, found: Vault, new_password: str) -> str:
    """A new password for a lab that is already open (say, with its recovery key). Returns a new recovery key."""
    problem = password_problem(new_password)
    if problem:
        raise VaultError(problem)
    fresh = new_recovery_key()
    _write_key(Path(folder), _record(found.lab_id, found._key, new_password, fresh))
    return fresh


def _files(folder: Path):
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file() and path.name not in PLAIN_NAMES and not path.name.endswith(".tmp"):
            yield path


def encrypt_folder(folder, progress=None) -> int:
    """Encrypt every plain file in an unlocked lab, in place. Returns how many.

    Each file is written atomically, so stopping half way leaves every file
    either plain or encrypted, and running it again carries on.
    `progress(done, total, name)` is called before each file; returning False stops.
    """
    import storage

    folder = Path(folder)
    found = _open.get(folder.resolve())
    if found is None:
        raise Locked("Unlock the lab first.")
    todo = [path for path in _files(folder) if not is_encrypted_file(path)]
    for done, path in enumerate(todo):
        if progress is not None and progress(done, len(todo), path.name) is False:
            return done
        storage.write_atomic(path, path.read_bytes())   # guard() encrypts it
    return len(todo)


def decrypt_folder(folder, progress=None) -> int:
    """Turn an unlocked encrypted lab back into a plain one. Returns how many files.

    Every file is decrypted first; only then is the key file removed and the
    lab locked, so a stop half way leaves a lab that still opens.
    """
    import storage

    folder = Path(folder)
    found = _open.get(folder.resolve())
    if found is None:
        raise Locked("Unlock the lab first.")
    todo = [path for path in _files(folder) if is_encrypted_file(path)]
    for done, path in enumerate(todo):
        if progress is not None and progress(done, len(todo), path.name) is False:
            return done
        plain = found.decrypt(path.read_bytes(), path.name)
        temp = path.with_name(path.name + ".plain.tmp")
        temp.write_bytes(plain)
        storage.replace_with_retry(temp, path)
    lock(folder)
    _key_path(folder).unlink()
    return len(todo)
