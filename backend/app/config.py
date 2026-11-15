import os, dotenv
dotenv.load_dotenv()
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = os.getenv('DATABASE_URL', '')

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


settings = Settings()