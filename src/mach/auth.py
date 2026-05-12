from __future__ import annotations

import os
import json
from pathlib import Path

def get_credentials_path() -> Path:
    """Returns the path to the global credentials file."""
    return Path.home() / ".mach" / "credentials.json"

def save_token(token: str) -> None:
    """Saves the auth token globally."""
    creds_path = get_credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    
    creds = {}
    if creds_path.exists():
        try:
            with open(creds_path, "r", encoding="utf-8") as f:
                creds = json.load(f)
        except json.JSONDecodeError:
            pass
            
    creds["token"] = token
    with open(creds_path, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2)
    
    # Secure the file
    creds_path.chmod(0o600)

def get_token() -> str | None:
    """Gets the auth token from environment or global credentials."""
    # 1. Environment Variable
    token = os.environ.get("MACH_TOKEN")
    if token:
        return token
        
    # 2. Global Credentials File
    creds_path = get_credentials_path()
    if creds_path.exists():
        try:
            with open(creds_path, "r", encoding="utf-8") as f:
                creds = json.load(f)
                return creds.get("token")
        except json.JSONDecodeError:
            return None
    return None

def logout() -> None:
    """Removes the globally saved token."""
    creds_path = get_credentials_path()
    if creds_path.exists():
        creds_path.unlink()
