import os
import yaml
from typing import Dict, Any, Optional


class ConfigManager:
    _instance = None
    _config: Dict[str, Any] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._load_config()
        return cls._instance

    @classmethod
    def _load_config(cls):
        config_path = os.environ.get(
            "DQ_CONFIG_PATH",
            os.path.join(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))
                    )
                ),
                "config",
                "config.yaml",
            ),
        )
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            cls._config = yaml.safe_load(f)

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        if cls._config is None:
            cls._load_config()
        keys = key.split(".")
        value = cls._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    @classmethod
    def get_all(cls) -> Dict[str, Any]:
        if cls._config is None:
            cls._load_config()
        return cls._config

    @classmethod
    def reload(cls):
        cls._load_config()
