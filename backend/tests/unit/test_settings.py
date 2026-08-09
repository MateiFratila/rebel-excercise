import pytest
from pydantic import ValidationError

from rebel_dot.core import Environment, Settings

ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "openai_api_key": "sk-test-only",
        "shared_password_hash": ARGON2_HASH,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_settings_parse_comma_delimited_origins() -> None:
    settings = make_settings(allowed_origins="http://localhost:5173, http://localhost:8000")

    assert settings.allowed_origins == ("http://localhost:5173", "http://localhost:8000")


def test_production_requires_secure_cookie_and_https_origins() -> None:
    with pytest.raises(ValidationError, match="non-local sessions require secure cookies"):
        make_settings(
            environment=Environment.PRODUCTION,
            session_cookie_secure=False,
            allowed_origins=("https://support.example.com",),
        )

    with pytest.raises(ValidationError, match="non-local sessions require secure cookies"):
        make_settings(
            environment=Environment.TEST,
            session_cookie_secure=False,
        )

    with pytest.raises(ValidationError, match="must use HTTPS"):
        make_settings(
            environment=Environment.PRODUCTION,
            allowed_origins=("http://support.example.com",),
        )

    local = make_settings(
        environment=Environment.LOCAL,
        session_cookie_secure=False,
    )
    assert not local.session_cookie_secure


def test_shared_password_must_be_argon2id_hash() -> None:
    with pytest.raises(ValidationError, match="Argon2id"):
        make_settings(shared_password_hash="cleartext-password")

    with pytest.raises(ValidationError, match="valid Argon2id"):
        make_settings(shared_password_hash="$argon2id$invalid")


def test_session_lifetime_accepts_environment_string_and_remains_fixed() -> None:
    assert make_settings(session_lifetime_seconds="604800").session_lifetime_seconds == 604800

    with pytest.raises(ValidationError):
        make_settings(session_lifetime_seconds="86400")


def test_allowed_origins_reject_paths_and_credentials() -> None:
    with pytest.raises(ValidationError, match="absolute HTTP"):
        make_settings(allowed_origins=("https://example.com/path",))

    with pytest.raises(ValidationError, match="absolute HTTP"):
        make_settings(allowed_origins=("https://user@example.com",))


def test_secret_values_are_masked() -> None:
    settings = make_settings()

    assert "sk-test-only" not in repr(settings)
    assert ARGON2_HASH not in repr(settings)


def test_routing_defaults_match_evaluated_operating_point() -> None:
    settings = make_settings()

    assert settings.local_similarity_threshold == 0.84
    assert settings.local_similarity_margin == 0.08
    assert settings.scope_confidence_threshold == 0.75
