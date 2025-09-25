import torch
from pinecone import Pinecone
import datetime  # 'date'クラスとの名前衝突を避けるため、モジュール全体をインポート
from typing import List, Dict
from sentence_transformers import SentenceTransformer

# プロジェクト共通の設定をインポート
import config

class Retriever:
    """
    日記データの埋め込みモデルとVector DBを管理し、検索機能を提供するクラス
    """
    def __init__(self):
        """
        コンストラクタ: モデルのロードとDBへの接続を行う
        """
        self.embedding_model = self._load_embedding_model()
        self.embedding_dim = self._get_embedding_dimension()
        self.pinecone_index = self._connect_to_pinecone()

    def _load_embedding_model(self):
        try:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"Retriever: Using device '{device}' for embedding model.")
            return SentenceTransformer(config.EMBEDDING_MODEL_NAME, device=device)
        except Exception as e:
            print(f"Error loading SentenceTransformer model: {e}")
            return None

    def _get_embedding_dimension(self) -> int:
        """ロードしたモデルから埋め込みベクトルの次元数を取得する"""
        if self.embedding_model:
            return self.embedding_model.get_sentence_embedding_dimension()
        # モデルのロードに失敗した場合のフォールバック
        print("Warning: Embedding model not loaded. Using fallback dimension.")
        return 768

    def _connect_to_pinecone(self):
        try:
            pc = Pinecone()
            return pc.Index(config.PINECONE_INDEX_NAME)
        except Exception as e:
            print(f"Error connecting to Pinecone: {e}")
            return None

    def search(self, date: str, query: str = "", k: int = 6, day_window: int = 3) -> List[Dict]:
        """
        指定された日付の周辺と、クエリに類似する日記をPineconeから検索する
        return: [{'text': str, 'metadata': {'date': str, 'location': str}, 'score': float}]
        """
        if not self.pinecone_index or not self.embedding_model:
            raise ConnectionError("Retriever is not properly initialized.")

        # 1. ターゲット日付の周辺をメタデータフィルタで検索
        target_date = datetime.date.fromisoformat(date)
        start_date_obj = (target_date - datetime.timedelta(days=day_window))
        end_date_obj = (target_date + datetime.timedelta(days=day_window))

        # 日付をUnixタイムスタンプ（整数）に変換する
        start_timestamp = int(datetime.datetime.combine(start_date_obj, datetime.time.min).timestamp())
        end_timestamp = int(datetime.datetime.combine(end_date_obj, datetime.time.min).timestamp())

        filter_dict = {
            "date": {
                "$gte": start_timestamp,
                "$lte": end_timestamp
            }
        }

        # 検索用のベクトルを生成
        if query:
            vector = self.embedding_model.encode(query).tolist()
        else:
            # クエリが空の場合はゼロベクトルを使用（モデルから取得した次元数）
            vector = [0.0] * self.embedding_dim

        try:
            # Pineconeにクエリ実行
            results = self.pinecone_index.query(
                vector=vector,
                filter=filter_dict,
                top_k=k,
                include_metadata=True
            )

            # 2. 結果が不足している場合、日付フィルタなしで全体から類似度が高いものを追加で検索
            found_ids = {match['id'] for match in results['matches']}
            if len(results['matches']) < k:
                broader_results = self.pinecone_index.query(
                    vector=vector,
                    top_k=k * 2, # 多めに取得してフィルタリング
                    include_metadata=True
                )
                
                for match in broader_results['matches']:
                    if match['id'] not in found_ids:
                        results['matches'].append(match)
                        found_ids.add(match['id'])
                        if len(results['matches']) >= k:
                            break

        except Exception as e:
            print(f"ERROR: An exception occurred during Pinecone query: {e}")
            return []

        # 3. 返却形式を整形
        passages = []
        for match in results['matches']:
            ts = match['metadata'].get('date')
            date_str = ''
            # ▼▼▼【修正点】タイムスタンプが文字列で返されることがあるため、数値に変換する▼▼▼
            if ts:
                try:
                    # Pineconeは数値を文字列として返すことがあるため、floatに変換
                    date_str = datetime.datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d')
                except (ValueError, TypeError):
                    # 変換に失敗した場合のフォールバック
                    date_str = match.get('id', '') # ID（日付文字列）をそのまま使う
            # ▲▲▲【修正ここまで】▲▲▲
            
            passages.append({
                "text": match['metadata'].get('text', ''),
                "metadata": {
                    "date": date_str,
                    "location": match['metadata'].get('location', '')
                },
                "score": match['score']
            })
            
        return passages

# 他のモジュールからインポートして使えるように、クラスのインスタンスを作成
retriever_instance = Retriever()
