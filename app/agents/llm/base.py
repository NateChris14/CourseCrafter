## Base LLM Client Interface
from abc import ABC, abstractmethod
from typing import Type
from pydantic import BaseModel

class LLMClient(ABC):
    @abstractmethod
    def generate_text(self, * , system: str, user: str, temperature: float = 0.2) -> str:
        raise NotImplementedError

    def generate_structured(self, schema: Type[BaseModel], * , 
    system: str, user: str, temperature: float = 0.2) -> BaseModel:
        """
        Default strategy: ask model to output JSON only, then validate with 
        Pydantic.
        Concrete client can override if it supports native JSON mode.
        """

        text = self.generate_text(system=system, user=user, 
        temperature=temperature)
        return schema.model_validate_json(text)