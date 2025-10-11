from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=[".env"], extra="ignore")

    tangled_handle: str = Field(default=...)
    tangled_password: str = Field(default=...)

    # optional: specify PDS URL if auto-discovery doesn't work
    # leave empty for auto-discovery from handle
    tangled_pds_url: str | None = None


# tangled service constants
TANGLED_APPVIEW_URL = "https://tangled.org"
TANGLED_DID = "did:web:tangled.org"

settings = Settings()
