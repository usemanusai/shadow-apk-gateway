"""Session Manager — Auth token and session cookie management.

Manages sessions per (app_id, tenant_id). Stores credentials encrypted
at rest using Fernet symmetric encryption.

Key management:
- If GATEWAY_FERNET_KEY env var is set, uses that key (survives restarts).
- Otherwise generates an ephemeral key (sessions lost on restart).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from cryptography.fernet import Fernet
from pydantic import BaseModel

from packages.core_schema.models.action_catalog import ActionCatalog


class SessionStartRequest(BaseModel):
    """Request to start a new session."""

    tenant_id: str = "default"
    credentials: dict[str, str] = {}


@dataclass
class Session:
    """Active session with auth credentials."""

    session_id: str
    app_id: str
    tenant_id: str
    created_at: float
    expires_at: float
    auth_headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    execution_count: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


def _resolve_fernet_key() -> bytes:
    """Resolve the Fernet encryption key from environment or generate one.

    Supports GATEWAY_FERNET_KEY env var for deterministic key injection,
    which ensures sessions survive gateway restarts.
    """
    env_key = os.environ.get("GATEWAY_FERNET_KEY", "")
    if env_key:
        # Validate the key is a valid Fernet key
        try:
            Fernet(env_key.encode("utf-8"))
            return env_key.encode("utf-8")
        except Exception:
            # Fall through to generate a new key if invalid
            pass
    return Fernet.generate_key()


class SessionManager:
    """Manages auth sessions per (app_id, tenant_id).

    Sessions expire after a configurable TTL (default: 3600s).
    Credentials are stored encrypted using Fernet.

    Features:
    - Fernet key persistence via GATEWAY_FERNET_KEY env var
    - Session credential rotation after execution_count threshold
    - Session expiry and cleanup
    """

    def __init__(
        self,
        ttl_seconds: int = 3600,
        encryption_key: Optional[bytes] = None,
        rotation_threshold: int = 100,
    ):
        self.ttl_seconds = ttl_seconds
        self.rotation_threshold = rotation_threshold
        self._fernet = Fernet(encryption_key or _resolve_fernet_key())
        self._sessions: dict[str, Session] = {}  # key = f"{app_id}:{tenant_id}"
        self._encrypted_credentials: dict[str, bytes] = {}

    async def start_session(
        self,
        app_id: str,
        tenant_id: str,
        credentials: dict[str, str],
        catalog: Optional[ActionCatalog] = None,
        executor: Optional[Any] = None,
    ) -> Session:
        """Start a new session, optionally running a login action.

        If the catalog contains a 'login' risk-tagged action and credentials
        are provided, the session manager will execute the login action
        and store the resulting auth token.
        """
        session_id = str(uuid.uuid4())
        now = time.time()

        session = Session(
            session_id=session_id,
            app_id=app_id,
            tenant_id=tenant_id,
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )

        # Store encrypted credentials
        if credentials:
            cred_json = json.dumps(credentials).encode()
            encrypted = self._fernet.encrypt(cred_json)
            self._encrypted_credentials[f"{app_id}:{tenant_id}"] = encrypted

        # If we have a catalog with login actions, try to authenticate
        if catalog and executor and credentials:
            login_actions = [
                a for a in catalog.actions
                if "login" in a.risk_tags and a.approved
            ]
            if login_actions:
                login_action = login_actions[0]
                try:
                    from apps.gateway.src.executor import ExecutionRequest
                    exec_req = ExecutionRequest(
                        action=login_action,
                        params=credentials,
                        tenant_id=tenant_id,
                    )
                    result = await executor.execute(exec_req)

                    # Extract auth tokens from response
                    if result.status_code == 200:
                        if isinstance(result.body, dict):
                            token = (
                                result.body.get("token")
                                or result.body.get("access_token")
                                or result.body.get("jwt")
                            )
                            if token:
                                session.auth_headers["Authorization"] = f"Bearer {token}"

                        # Extract cookies from response headers
                        set_cookie = result.headers.get("set-cookie", "")
                        if set_cookie:
                            session.cookies["session"] = set_cookie

                except Exception:
                    # Login failed — session is created but unauthenticated
                    pass

        key = f"{app_id}:{tenant_id}"
        self._sessions[key] = session
        return session

    def get_session(self, app_id: str, tenant_id: str) -> Optional[dict]:
        """Retrieve active session auth data.

        Returns a dict with Authorization header and cookies, or None.
        """
        key = f"{app_id}:{tenant_id}"
        session = self._sessions.get(key)

        if not session or session.is_expired:
            if session and session.is_expired:
                del self._sessions[key]
            return None

        result: dict[str, str] = {}
        result.update(session.auth_headers)

        if session.cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
            result["cookies"] = cookie_str

        return result

    def record_execution(self, app_id: str, tenant_id: str) -> None:
        """Record an execution against this session and check rotation threshold."""
        key = f"{app_id}:{tenant_id}"
        session = self._sessions.get(key)
        if not session:
            return

        session.execution_count += 1

        # Rotate credentials encryption key after threshold
        if session.execution_count >= self.rotation_threshold:
            self._rotate_credentials(key)
            session.execution_count = 0

    def _rotate_credentials(self, key: str) -> None:
        """Re-encrypt stored credentials with a fresh Fernet key.

        This limits the blast radius if the encryption key is ever compromised,
        since old ciphertext becomes undecryptable after rotation.
        """
        encrypted = self._encrypted_credentials.get(key)
        if not encrypted:
            return

        try:
            # Decrypt with current key
            decrypted = self._fernet.decrypt(encrypted)
            # Generate new key and re-encrypt
            new_key = Fernet.generate_key()
            new_fernet = Fernet(new_key)
            self._encrypted_credentials[key] = new_fernet.encrypt(decrypted)
            self._fernet = new_fernet
        except Exception:
            # If rotation fails, keep existing encryption
            pass

    def clear_session(self, app_id: str, session_id: str) -> None:
        """Clear a session by session_id."""
        to_delete = []
        for key, session in self._sessions.items():
            if session.app_id == app_id and session.session_id == session_id:
                to_delete.append(key)

        for key in to_delete:
            del self._sessions[key]
            self._encrypted_credentials.pop(key, None)

    def clear_all_sessions(self, app_id: str) -> None:
        """Clear all sessions for an app."""
        to_delete = [
            key for key, session in self._sessions.items()
            if session.app_id == app_id
        ]
        for key in to_delete:
            del self._sessions[key]
            self._encrypted_credentials.pop(key, None)

    def _decrypt_credentials(self, app_id: str, tenant_id: str) -> Optional[dict]:
        """Retrieve and decrypt stored credentials."""
        key = f"{app_id}:{tenant_id}"
        encrypted = self._encrypted_credentials.get(key)
        if not encrypted:
            return None

        decrypted = self._fernet.decrypt(encrypted)
        return json.loads(decrypted)
