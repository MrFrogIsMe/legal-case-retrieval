# 法律判決類案搜尋 API — 生產映像
# 路線 B（docs/roadmap_v1.md 第 4 節）：uv + FastAPI，索引/資料走 volume 掛載不進 image。
#
# 注意：
#   - retrieval extra 含 torch 2.4.1+cu121（BGE-M3/reranker），映像較大。
#     有 NVIDIA GPU 時用 nvidia container runtime 啟動可享 GPU 加速；
#     無 GPU 則 torch 自動 fallback CPU（檢索較慢，但功能完整）。
#   - chromadb 需 PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python（見 ENV）。
#   - 索引（ChromaDB + BM25）與 processed 資料不打進 image，啟動時掛載。

FROM python:3.12-slim AS base

# uv（官方 distroless 複製二進位，免裝 pip）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # chromadb 走純 python protobuf，避免 C 實作的 TypeError
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
    # uv 裝進系統環境，不建虛擬環境層
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 1) 先複製依賴宣告，鎖檔安裝（--frozen 不更新 lock），最大化 layer cache
COPY pyproject.toml uv.lock README.md* ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra api --extra retrieval

# 2) 複製應用程式碼
COPY app ./app

# 索引/資料目錄（compose 掛載到此）
ENV LCR_PROCESSED_DIR=/data/processed \
    LCR_INDEX_DIR=/data/index

EXPOSE 8000

# 健康檢查打 /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0) if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else sys.exit(1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
