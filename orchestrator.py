from retriever import retriever_instance
from schemas import InterpolationRequest, InterpolationResponse, Citation
from rag_chain import build_context, generate_interpolation

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

        # 2. RAG Chainでプロンプトを組み立て、LLMで生成
        context = build_context(passages)
        text = generate_interpolation(req.date, context, req.hint)

        # 3. レスポンスを構築
        citations = []
        for passage in passages:
            metadata = passage.get("metadata", {}) if isinstance(passage, dict) else {}
            snippet = passage.get("text", "")[:100] + "..." if isinstance(passage, dict) else ""
            citation_date = metadata.get("date", req.date)
            citations.append(Citation(snippet=snippet, date=citation_date))

        return InterpolationResponse(
            date=req.date,
            text=text,
            citations=citations,
        )

orchestrator_instance = Orchestrator()

