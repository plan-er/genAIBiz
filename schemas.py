from pydantic import BaseModel, Field
from typing import List, Optional

class DiaryEntry(BaseModel):
    """
    データベースに保存される日記の基本構造
    """
    date: str
    body: str
    location: Optional[str] = None
    tags: Optional[List[str]] = None

class InterpolationRequest(BaseModel):
    """
    /interpolate APIへのリクエストボディの型定義
    """
    date: str = Field(..., description="補間対象の日付 (YYYY-MM-DD)", examples=["2025-09-23"])
    hint: Optional[str] = Field(None, description="ユーザーからの補足情報やヒント", examples=["雨だった日"])

class Citation(BaseModel):
    """
    補間の根拠として参照された過去の日記の情報
    """
    snippet: str = Field(..., description="参照した日記の抜粋")
    date: str = Field(..., description="参照した日記の日付")

class InterpolationResponse(BaseModel):
    """
    /interpolate APIからのレスポンスボディの型定義
    """
    date: str
    text: str
    citations: List[Citation]

class IngestRequest(BaseModel):
    """
    /ingest APIへのリクエストボディの型定義
    """
    diaries: List[DiaryEntry]

class IngestResponse(BaseModel):
    """
    /ingest APIからのレスポンスボディの型定義
    """
    status: str
    ingested_count: int

class DiaryResponse(BaseModel):
    """
    /diary/{date} APIからのレスポンスボディの型定義
    """
    date: str
    body: str
    location: Optional[str] = None
    tags: Optional[List[str]] = None
    