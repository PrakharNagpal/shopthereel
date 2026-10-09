from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    reap_api_key: str = ""
    reap_base_url: str = "https://sandbox.api.reap.global"
    reap_version: str = ""
    reap_default_country: str = "SG"
    reap_default_currency: str = "SGD"
    reap_simulate_checkout: bool = True
    reap_return_url: str = ""
    demo_email: str = ""
    demo_shipping_json: str = "{}"

    openai_api_key: str = ""
    openai_vision_model: str = ""
    openai_transcribe_model: str = ""

    ig_access_token: str = ""
    ig_business_account_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    graph_api_version: str = ""

    public_base_url: str = ""
    db_path: str = "./shopthereel.db"


settings = Settings()
