import os
from dataclasses import dataclass


@dataclass(frozen=True)
class JianYingConfig:
    save_path: str
    output_path: str
    media_cache_dir: str = ""

    @classmethod
    def from_env(cls) -> "JianYingConfig":
        save_path = os.getenv("SAVE_PATH", "")
        output_path = os.getenv("OUTPUT_PATH", "")
        media_cache_dir = os.getenv("MEDIA_CACHE_DIR", "")
        return cls(save_path=save_path, output_path=output_path, media_cache_dir=media_cache_dir)

    def validate(self) -> None:
        if not self.save_path:
            raise ValueError("SAVE_PATH is not set")
        if not os.path.exists(self.save_path):
            raise ValueError(f"SAVE_PATH not found: {self.save_path}")
        if self.output_path and not os.path.exists(self.output_path):
            raise ValueError(f"OUTPUT_PATH not found: {self.output_path}")
