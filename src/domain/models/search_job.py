"""一次性后台搜索任务的领域模型。

与 ``tasks`` 表里的定时任务刻意分开：
- 不进调度器、不出现在任务列表；
- 结果只写自己的目录，不写行情快照和结果页。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SearchJobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]


class SearchJobRequest(BaseModel):
    """提交一次搜索时允许的过滤条件。"""

    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(min_length=1, max_length=100, description="闲鱼搜索词")
    max_pages: int = Field(default=1, ge=1, le=10, description="最多翻多少页")
    min_price: Optional[float] = Field(default=None, ge=0)
    max_price: Optional[float] = Field(default=None, ge=0)
    region: Optional[str] = Field(default=None, max_length=20)
    personal_only: bool = False
    free_shipping: bool = False

    @field_validator("keyword", mode="before")
    @classmethod
    def _normalize_keyword(cls, value):
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("keyword 不能为空")
        return text

    @field_validator("region", mode="before")
    @classmethod
    def _normalize_region(cls, value):
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _check_price_range(self):
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price 不能大于 max_price")
        return self


class SearchJob(BaseModel):
    """落库后的搜索任务状态。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    task_name: str
    keyword: str
    max_pages: int = 1
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    region: Optional[str] = None
    personal_only: bool = False
    free_shipping: bool = False
    status: SearchJobStatus = "queued"
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    result_count: int = 0
    job_dir: str

    def request(self) -> SearchJobRequest:
        return SearchJobRequest(
            keyword=self.keyword,
            max_pages=self.max_pages,
            min_price=self.min_price,
            max_price=self.max_price,
            region=self.region,
            personal_only=self.personal_only,
            free_shipping=self.free_shipping,
        )
