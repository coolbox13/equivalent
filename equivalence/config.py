import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DBConfig:
    host: str = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("DB_PORT", "5432")))
    user: str = field(default_factory=lambda: os.getenv("DB_USER", ""))
    password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", ""))
    dbname: str = field(default_factory=lambda: os.getenv("DB_NAME", "dev_omfietser"))

    @property
    def dsn(self) -> str:
        return f"host={self.host} port={self.port} dbname={self.dbname} user={self.user} password={self.password}"


@dataclass
class ApfelConfig:
    base_url: str = field(default_factory=lambda: os.getenv("APFEL_URL", "http://localhost:11435"))
    model: str = "apple-foundationmodel"
    batch_size: int = 10
    request_timeout: int = 120
    max_retries: int = 3
    pause_between_calls: float = 1.0
