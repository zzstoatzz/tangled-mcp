from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BOBBIN_URL = "https://api.tangled.org"
APPVIEW_URL = "https://tangled.org"
PLC_URL = "https://plc.directory"


class Settings(BaseSettings):
    """credentials are only required for write tools (issues, comments, labels).

    all read tools go through bobbin (api.tangled.org), which needs no auth.
    """

    model_config = SettingsConfigDict(env_file=[".env"], extra="ignore")

    tangled_handle: str | None = Field(default=None)
    tangled_password: str | None = Field(default=None)
    tangled_pds_url: str | None = Field(default=None)


settings = Settings()
