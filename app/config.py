# -----------------------------------------------------------------------------
# Recipe Box configuration.
# This is the single source of truth for runtime settings. Environment
# variables are loaded and validated here so routes, queries, migrations, and
# application setup never read os.environ independently or scatter defaults.
# -----------------------------------------------------------------------------

import os
from dataclasses import dataclass

from dotenv import load_dotenv


# Load a local .env file for direct Python runs. Docker Compose injects the
# same values into the process environment, so the application remains
# portable and does not depend on a platform-specific configuration mechanism.
load_dotenv()


def _required_setting(name: str) -> str:
    """Return a required environment variable or fail with a useful message.

    Args:
        name: The environment variable name to read.

    Returns:
        str: The trimmed, non-empty environment value.

    Raises:
        RuntimeError: If the variable is missing or contains only whitespace.

    Why it exists:
        Configuration errors should be reported during startup, before the app
        accepts requests or attempts to write data with incomplete settings.
    """

    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to .env and provide a value before starting "
            "Recipe Box."
        )
    return value


def _integer_setting(name: str, default: int) -> int:
    """Read an optional integer setting and validate malformed values.

    Args:
        name: The environment variable name to read.
        default: The value to use when the variable is not set.

    Returns:
        int: The configured integer.

    Raises:
        RuntimeError: If the configured value is not a valid integer.

    Why it exists:
        Port and similar numeric settings should fail at startup with a clear
        configuration error instead of failing later inside a server command.
    """

    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError as error:
        raise RuntimeError(
            f"Environment variable {name} must be an integer; received "
            f"{raw_value!r}."
        ) from error


@dataclass(frozen=True)
class Settings:
    """Validated settings shared by every Recipe Box application component."""

    database_url: str
    encryption_key: str
    app_host: str
    app_port: int
    environment: str


# Importing this object validates all required values once at application
# startup. Other modules should import settings from this module rather than
# reading environment variables themselves.
settings = Settings(
    database_url=_required_setting("DATABASE_URL"),
    encryption_key=_required_setting("ENCRYPTION_KEY"),
    app_host=os.getenv("APP_HOST", "0.0.0.0").strip() or "0.0.0.0",
    app_port=_integer_setting("APP_PORT", 8000),
    environment=os.getenv("APP_ENV", "development").strip() or "development",
)