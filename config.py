"""Central configuration loaded from environment variables."""

import os
from pathlib import Path


class Settings:
    """Application settings with defaults."""

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Storage paths
    BASE_DIR: Path = Path(__file__).parent
    STORAGE_BASE_DIR: Path = Path(os.getenv("STORAGE_BASE_DIR", str(BASE_DIR / "storage_data")))
    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(STORAGE_BASE_DIR / "uploads")))
    RESULT_DIR: Path = Path(os.getenv("RESULT_DIR", str(STORAGE_BASE_DIR / "results")))

    # File retention
    FILE_RETENTION_HOURS: int = int(os.getenv("FILE_RETENTION_HOURS", "24"))

    # API
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # OCR
    OCR_LANG: str = os.getenv("OCR_LANG", "ch")
    OCR_USE_GPU: bool = os.getenv("OCR_USE_GPU", "false").lower() == "true"
    FONT_SIZE_SCALE: float = float(os.getenv("FONT_SIZE_SCALE", "0.9"))
    SPACE_GAP_RATIO: float = float(os.getenv("SPACE_GAP_RATIO", "0.35"))
    SPACE_MIN_GAP_RATIO: float = float(os.getenv("SPACE_MIN_GAP_RATIO", "0.2"))

    # Processing
    RENDER_DPI: int = int(os.getenv("RENDER_DPI", "200"))
    TEXT_CHAR_THRESHOLD: int = int(os.getenv("TEXT_CHAR_THRESHOLD", "50"))
    IMAGE_COVERAGE_THRESHOLD: float = float(os.getenv("IMAGE_COVERAGE_THRESHOLD", "0.5"))
    INPAINT_DOWNSCALE: float = float(os.getenv("INPAINT_DOWNSCALE", "1.0"))
    INPAINT_RADIUS: int = int(os.getenv("INPAINT_RADIUS", "4"))
    INPAINT_DILATE: int = int(os.getenv("INPAINT_DILATE", "2"))
    INPAINT_KERNEL: int = int(os.getenv("INPAINT_KERNEL", "5"))
    INPAINT_EDGE_PROTECT: bool = os.getenv("INPAINT_EDGE_PROTECT", "true").lower() == "true"
    INPAINT_EDGE_THICKNESS: int = int(os.getenv("INPAINT_EDGE_THICKNESS", "3"))

    def __init__(self):
        # Ensure directories exist
        self.STORAGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.RESULT_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
