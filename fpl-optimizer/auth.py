"""
Access Code Authentication System

This module provides a simple access code verification system with JWT tokens.
Users enter a secret code (from your resume) to unlock the chatbot feature.
"""

import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

try:
    import jwt
except ImportError:
    # PyJWT not installed - will fail at runtime if auth is used
    jwt = None

from fastapi import HTTPException, Header
from pydantic import BaseModel


# Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
ACCESS_CODE_HASH = os.getenv("ACCESS_CODE_HASH")  # SHA256 hash of your access code
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


class AccessCodeRequest(BaseModel):
    """Request model for access code verification"""
    code: str


class TokenResponse(BaseModel):
    """Response model for successful authentication"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = TOKEN_EXPIRE_HOURS * 3600


def hash_code(code: str) -> str:
    """
    Hash the access code using SHA-256.

    To generate the hash for your access code, run:
    python -c "import hashlib; print(hashlib.sha256(b'YourSecretCode').hexdigest())"
    """
    return hashlib.sha256(code.encode()).hexdigest()


def verify_access_code(code: str) -> bool:
    """
    Verify the provided access code against the stored hash.

    Returns True if the code is valid, False otherwise.
    """
    if not ACCESS_CODE_HASH:
        # If no hash is configured, reject all codes
        # This prevents accidental open access
        return False

    return hash_code(code) == ACCESS_CODE_HASH


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        data: Payload data to encode in the token
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    if jwt is None:
        raise HTTPException(
            status_code=500,
            detail="JWT library not installed. Run: pip install PyJWT"
        )

    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=TOKEN_EXPIRE_HOURS))
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow()
    })

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def verify_token(authorization: Optional[str] = Header(None)) -> bool:
    """
    FastAPI dependency to verify JWT tokens.

    Use this as a dependency in protected endpoints:
        @app.post("/api/chat")
        async def chat(request: ChatRequest, _: bool = Depends(verify_token)):
            ...

    Raises:
        HTTPException: If token is missing, invalid, or expired
    """
    if jwt is None:
        raise HTTPException(
            status_code=500,
            detail="JWT library not installed"
        )

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required. Please enter the access code first."
        )

    # Parse "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization format. Expected: Bearer <token>"
        )

    token = parts[1]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # Verify the token was issued for portfolio access
        if not payload.get("verified"):
            raise HTTPException(status_code=401, detail="Invalid token")

        return True

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired. Please enter the access code again."
        )
    except jwt.JWTError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: {str(e)}"
        )


def check_auth_configured() -> bool:
    """Check if authentication is properly configured."""
    return bool(ACCESS_CODE_HASH)


# Helper function to generate hash for setup
def generate_hash_for_code(code: str) -> str:
    """
    Generate the hash for an access code.

    Use this during setup to create the ACCESS_CODE_HASH env var:

        from auth import generate_hash_for_code
        print(generate_hash_for_code("MySecretCode"))

    Then set ACCESS_CODE_HASH environment variable to the output.
    """
    return hash_code(code)
