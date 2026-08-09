from pathlib import Path

from rebel_dot.ops.faq_fixture import load_faq_fixture

FIXTURE_PATH = Path(__file__).parents[2] / "data" / "faq.json"


def test_fixture_contains_exact_source_records_without_provider_key() -> None:
    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")
    fixture = load_faq_fixture(FIXTURE_PATH)

    assert len(fixture.knowledge_base_items) == 33
    assert fixture.knowledge_base_items[0].question == "How do I change my profile information?"
    assert fixture.knowledge_base_items[-1].question == "x"
    assert "OPENAI_API_KEY" not in fixture_text
    assert "sk-proj-" not in fixture_text


def test_fixture_preserves_messy_unicode_content() -> None:
    fixture = load_faq_fixture(FIXTURE_PATH)

    assert fixture.knowledge_base_items[12].answer == (
        "Settings -> Security -> Two‑Factor -> Authenticator App -> scan the QR and enter "
        "the 6‑digit code."
    )
    assert fixture.knowledge_base_items[31].question == "help!!! 😭😭😭 my account is locked"
