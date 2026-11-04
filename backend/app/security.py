import hashlib
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

# Argon2id hashes: no plaintext passwords are written to the new database.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def hash_password(password: str) -> str:
    return _hasher.hash(str(password))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, str(password))
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def make_session_token():
    token = secrets.token_urlsafe(48)
    return token, hashlib.sha256(token.encode()).hexdigest()


def session_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()
