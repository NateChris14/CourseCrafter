## Pydantic Schemas for Structured Output
from pydantic import BaseModel, Field, conint
from typing import List

class WeekPlan(BaseModel):
    week: conint(ge=1, le=52)
    title: str = Field(min_length=3, max_length=100)
    outcomes: List[str] = Field(min_length=2, max_length=8)

class RoadmapOutline(BaseModel):
    weeks: List[WeekPlan] = Field(min_length=4, max_length=52)
