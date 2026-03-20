import os
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError

JWT_SECRET = os.getenv("JWT_SECRET", "change_me_jwt_secret")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12

_pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_password(password: str) -> str:
    return _pwd.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return _pwd.verify(password, password_hash)

def create_access_token(payload: dict, expires_hours: int = ACCESS_TOKEN_EXPIRE_HOURS) -> str:
    to_encode = payload.copy()
    exp = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    to_encode["exp"] = exp
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
