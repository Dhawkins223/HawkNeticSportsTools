from __future__ import annotations

from fastapi import Request

from app.repositories import UserRepository
from app.security import SESSION_COOKIE, session_manager, verify_password


def authenticate(email: str, password: str):
    user = UserRepository.get_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def get_current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = session_manager.loads(token)
    if not payload:
        return None
    user_id = payload.get("user_id")
    if not user_id:
        return None
    return UserRepository.get_by_id(int(user_id))
