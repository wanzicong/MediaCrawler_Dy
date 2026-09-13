"""数据库与对象存储连接字段（口令/密钥走环境变量）。"""

from pydantic import BaseModel, Field, PostgresDsn, SecretStr, computed_field


class InfraFields(BaseModel):
    """PostgreSQL 与 MinIO 连接配置。"""

    POSTGRES_SERVER: str  # PostgreSQL 主机地址（必填）
    POSTGRES_PORT: int = 5432  # PostgreSQL 端口
    POSTGRES_USER: str  # PostgreSQL 用户名（必填）
    POSTGRES_PASSWORD: str = ""  # PostgreSQL 密码
    POSTGRES_DB: str = ""  # PostgreSQL 数据库名
    POSTGRES_CONNECT_TIMEOUT: int = Field(
        default=5, ge=1, le=60
    )  # 建连超时（秒）；数据库不可达时快速失败，而非长时间挂起请求

    MINIO_ENDPOINT: str = "127.0.0.1:9000"  # MinIO 服务地址（host:port）
    MINIO_ACCESS_KEY: SecretStr = SecretStr("mediacrawler")  # MinIO 访问密钥
    MINIO_SECRET_KEY: SecretStr = SecretStr("mediacrawler-secret")  # MinIO 秘密密钥
    MINIO_SECURE: bool = False  # 是否通过 HTTPS 连接 MinIO
    MINIO_BUCKET: str = "douyin-media"  # MinIO 存储桶名称
    MINIO_REGION: str = ""  # MinIO 区域，可选

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        """由 PostgreSQL 各项配置拼接出的 SQLAlchemy 数据库连接 URI。"""
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )
