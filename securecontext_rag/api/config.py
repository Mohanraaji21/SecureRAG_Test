"""
Application configuration, loaded from environment variables / a .env file.

DATABASE_URL controls the persistence backend:
  - SQL Server (production, matches your SSMS setup):
      mssql+pyodbc://<user>:<password>@<host>:1433/<db>?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
  - SQLite (local dev / tests, zero setup):
      sqlite:///./securecontext_rag.db

API_KEY protects mutating endpoints (POST/PATCH). See api/auth.py.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SCR_", extra="ignore")

    # --- Persistence -------------------------------------------------
    database_url: str = "sqlite:///./securecontext_rag.db"

    # --- Auth ----------------------------------------------------------
    api_key: str = "dev-only-change-me"

    # --- AI core wiring --------------------------------------------------
    ollama_url: str = "http://localhost:11434/api/generate"
    ollama_model: str = "qwen2.5-coder:7b"
    embedding_model: str = "all-MiniLM-L6-v2"
    semgrep_config: str = "auto"
    top_k_evidence: int = 3

    # --- GitHub webhook (stretch goal, section 4.2.5) -------------------
    github_webhook_secret: str = "dev-only-change-me"


settings = Settings()
