from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LayoutSettings(BaseModel):
    template: Literal["gb7713"] = "gb7713"
    columns: Literal[1, 2] = 1
    margin_mm: int = Field(default=25, ge=15, le=40)
    line_spacing: float = Field(default=1.5, ge=1.0, le=2.5)
    body_size_pt: float = Field(default=10.5, ge=9, le=14)
    title_size_pt: float = Field(default=18, ge=12, le=24)
    heading_font: str = "SimHei"
    body_font: str = "SimSun"
    figure_span_default: bool = False
    table_span_default: bool = False
    saved_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())

    @property
    def column_option(self) -> str:
        return "twocolumn" if self.columns == 2 else "onecolumn"

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)