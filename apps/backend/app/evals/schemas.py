"""Typed local cases shared by the evaluation harness, not shopper APIs."""

from typing import Generic, TypeVar

from pydantic import Field
from pydantic_evals import Case

from app.schemas.base import CartCartBaseModel, VersionedSchema

InputsT = TypeVar("InputsT")
OutputT = TypeVar("OutputT")


class EvalMetadata(CartCartBaseModel):
    description: str = Field(min_length=1, max_length=1000)
    tags: tuple[str, ...] = Field(default_factory=tuple)


class LocalEvalCase(VersionedSchema, Generic[InputsT, OutputT]):
    name: str = Field(min_length=1, max_length=120)
    inputs: InputsT
    expected_output: OutputT
    metadata: EvalMetadata

    def to_case(self) -> Case[InputsT, OutputT, EvalMetadata]:
        return Case(
            name=self.name,
            inputs=self.inputs,
            expected_output=self.expected_output,
            metadata=self.metadata,
        )
