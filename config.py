import os
import importlib


def _resolve_load_dotenv():
    dotenv_spec = importlib.util.find_spec("dotenv")
    if dotenv_spec is None:
        return lambda *_args, **_kwargs: False
    dotenv_module = importlib.import_module("dotenv")
    return getattr(dotenv_module, "load_dotenv", lambda *_args, **_kwargs: False)


load_dotenv = _resolve_load_dotenv()

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

# --- LLM (Diary Interpolation) ---
# Hugging Faceのモデル名は環境変数 INTERPOLATION_MODEL_NAME で上書き可能
INTERPOLATION_MODEL_NAME = os.environ.get(
	"INTERPOLATION_MODEL_NAME",
	"rinna/japanese-gpt2-medium",
)
# 生成長や温度は環境変数から調整できるが、デフォルト値を設定
INTERPOLATION_MAX_NEW_TOKENS = int(os.environ.get("INTERPOLATION_MAX_NEW_TOKENS", "320"))
INTERPOLATION_TEMPERATURE = float(os.environ.get("INTERPOLATION_TEMPERATURE", "0.7"))
INTERPOLATION_TOP_P = float(os.environ.get("INTERPOLATION_TOP_P", "0.9"))
INTERPOLATION_TASK = os.environ.get("INTERPOLATION_TASK", "text-generation")
HUGGINGFACEHUB_API_TOKEN = os.environ.get("HUGGINGFACEHUB_API_TOKEN")

