from fastapi import FastAPI, HTTPException
from schemas import (
    InterpolationRequest,
    InterpolationResponse,
    IngestRequest,
    IngestResponse,
    DiaryResponse
)
from orchestrator import orchestrator_instance
from ingest import ingest_diaries, get_diary_by_date

app = FastAPI(
    title="AI日記補完API",
    description="このAPIは、日記エントリを補間・管理するためのエンドポイントを提供します。",
    version="0.1.0"
)

@app.post("/interpolate", response_model=InterpolationResponse)
def interpolate_diary(req: InterpolationRequest):
    """
    指定された日付とヒントに基づき、日記の補間を行う
    """
    try:
        response = orchestrator_instance.interpolate(req)
        return response
    except Exception as e:
        # 実際の運用では、より詳細なエラーロギングを行う
        print(f"Error during interpolation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/ingest", response_model=IngestResponse)
def add_diary_entries(req: IngestRequest):
    """
    新しい日記エントリをデータベースとVector DBに取り込む
    """
    if not req.diaries:
        raise HTTPException(status_code=400, detail="No diaries provided to ingest.")
    try:
        ingest_diaries(req.diaries)
        return IngestResponse(
            status="success",
            ingested_count=len(req.diaries)
        )
    except Exception as e:
        print(f"Error during ingestion: {e}")
        raise HTTPException(status_code=500, detail="Failed to ingest diaries.")

@app.get("/diary/{date}", response_model=DiaryResponse)
def read_diary(date: str):
    """
    指定された日付の日記エントリをSQLiteから取得する
    """
    try:
        diary = get_diary_by_date(date)
        if diary:
            # tagsがNoneでない場合は文字列からリストに変換する
            if diary.get("tags"):
                diary["tags"] = diary["tags"].split(',')
            return diary
        else:
            raise HTTPException(status_code=404, detail="Diary not found for the specified date.")
    except Exception as e:
        print(f"Error reading diary for date {date}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve diary.")

@app.get("/")
def read_root():
    return {"message": "Welcome to AI Diary Interpolation API"}

