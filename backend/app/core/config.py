from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    db_host: str = "192.168.0.106"
    db_port: int = 3306
    db_name: str = "software_spider"
    db_user: str = ""
    db_password: str = ""
    api_cors_origins: str = "http://localhost:5173"
    data_root: str = "data"
    spider_enabled: bool = True
    spider_user_agent: str = "software_spider/0.2 (+local admin; release discovery)"
    spider_timeout: float = 30
    spider_max_retries: int = 3
    spider_max_concurrency: int = 1
    spider_request_delay: float = 0.5
    github_token: str = ""
    google_cse_api_key: str = ""
    google_cse_cx: str = ""
    ai_page_recognition_enabled: bool = False
    openai_api_key: str = ""
    ai_page_model: str = ""
    allow_private_source_urls: bool = False
    download_timeout: float = 120
    download_connect_timeout: float = 15
    download_max_retries: int = 3
    download_chunk_size: int = 262144
    download_max_concurrency: int = 5
    download_user_agent: str = "software_spider/0.3 (+local admin; direct artifact download)"
    download_max_file_size: int = 8589934592
    download_min_free_space: int = 1073741824
    download_allowed_domains: str = ""
    download_allowed_redirect_domains: str = ""
    baidu_app_key: str = ""
    baidu_app_secret: str = ""
    baidu_app_id: str = ""
    baidu_redirect_uri: str = "http://127.0.0.1:8000/api/v1/storage/accounts/baidu/oauth/callback"
    baidu_token_encryption_key: str = ""
    baidu_app_folder: str = "software_spider"
    storage_upload_chunk_size: int = 4 * 1024 * 1024
    self_hosted_base_url: str = "http://192.168.0.100:9000"
    self_hosted_api_key: str = ""
    cloud_integration_api_key: str = ""
    cloud_sharelink_path: str = "/sharelink/create-online"
    self_hosted_username: str = ""
    self_hosted_chunk_size: int = 4 * 1024 * 1024
    self_hosted_timeout: float = 120

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    @property
    def database_url(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    @property
    def data_path(self) -> Path:
        path = Path(self.data_root)
        return path if path.is_absolute() else ROOT / path


settings = Settings()
