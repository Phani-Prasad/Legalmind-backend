"""
Legaify - Auth Module
JWT-based authentication: User model, password hashing, token creation/verification.
"""

import os
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from sqlmodel import SQLModel, Field, Session, select
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import engine

# ── Config ─────────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "legalmind-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

bearer_scheme = HTTPBearer(auto_error=False)

# ── User Model ─────────────────────────────────────────────────────────────────

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# ── Password Helpers ───────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash password using bcrypt directly, isolating 72-byte safe strings."""
    password_bytes = plain.encode('utf-8')[:70]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')

def verify_password(plain: str, hashed: str) -> bool:
    password_bytes = plain.encode('utf-8')[:70]
    hashed_bytes = hashed.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)

# ── JWT Helpers ────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, email: str, name: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

# ── FastAPI Dependency ─────────────────────────────────────────────────────────

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> User:
    """
    Dependency that extracts and validates the Bearer JWT token.
    Raises 401 if token is missing, invalid, or user not found.
    """
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = int(payload["sub"])
    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user

# ── DB Helpers ─────────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[User]:
    with Session(engine) as session:
        return session.exec(select(User).where(User.email == email)).first()

def create_user(name: str, email: str, password: str) -> User:
    user = User(name=name, email=email, hashed_password=hash_password(password))
    with Session(engine) as session:
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
