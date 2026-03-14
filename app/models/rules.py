from pydantic import BaseModel


class Rule(BaseModel):
    number: str
    text: str


class RuleSection(BaseModel):
    number: str
    title: str
    rules: list[Rule] = []


class KeywordAbility(BaseModel):
    name: str
    rule_number: str
    description: str
    reminder_text: str | None = None
