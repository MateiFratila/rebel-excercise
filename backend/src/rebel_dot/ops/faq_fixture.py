from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SourceFAQ(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    category: str = Field(min_length=1)


class FAQFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_items: tuple[SourceFAQ, ...] = Field(min_length=1)


def load_faq_fixture(path: Path) -> FAQFixture:
    return FAQFixture.model_validate_json(path.read_text(encoding="utf-8"))
