from retriever import retriever_instance
from schemas import InterpolationRequest, InterpolationResponse, Citation

class Orchestrator:
    def interpolate(self, req: InterpolationRequest) -> InterpolationResponse:
        # 1. Retrieverで関連ドキュメントを検索
        try:
            # retriever_instance.searchはList[Dict]を返す
            passages = retriever_instance.search(date=req.date, query=req.hint)
        except Exception as e:
            print(f"Error during retrieval: {e}")
            # エラーが発生した場合は、スタブ応答を返しつつエラー情報を付加
            return InterpolationResponse(
                date=req.date,
                text=f"Error during retrieval: {e}",
                citations=[]
            )

        # 2. RAG Chainでプロンプトを組み立て、LLMで生成（現在はスタブ）
        # (担当Aがrag_chain.pyに実装)
        # rag_chain.generate_interpolation(...)

        # ▼▼▼【修正点】辞書のキーアクセスを p.text から p['text'] に変更▼▼▼
        # スタブの応答を作成
        context_for_stub = "\n".join([p['text'] for p in passages])
        text = f"（AIによる生成結果）\n日付: {req.date}\nヒント: {req.hint}\n---\n[参照した過去の記憶]\n{context_for_stub}"

        # 3. レスポンスを構築
        citations = [
            Citation(
                snippet=p['text'][:100] + "...", 
                date=p['metadata']["date"]
            )
            for p in passages
        ]
        # ▲▲▲【修正ここまで】▲▲▲

        return InterpolationResponse(
            date=req.date,
            text=text,
            citations=citations,
        )

orchestrator_instance = Orchestrator()

