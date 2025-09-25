import os
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# --- General ---
# NOTE: チームで共有する定数はここに書く
PROJECT_NAME = "AI Diary Interpolation"

# --- Database ---
# ingest.pyやapi_server.pyが参照するDBのパス
SQLITE_DB_PATH = "./data/diary_enriched.sqlite"

# --- Vector DB (Pinecone) ---
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = "diary-rag-index"

# --- Embedding Model ---
# ingest.pyとretriever.pyで同じモデル名を参照する
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-large"
# モデルの出力次元数 (intfloat/multilingual-e5-largeは1024次元)
EMBEDDING_DIMENSION = 1024

# --- Retriever Settings ---
# retriever.pyで使われる検索パラメータ
DEFAULT_TOP_K = 6
DEFAULT_DAY_WINDOW = 3

