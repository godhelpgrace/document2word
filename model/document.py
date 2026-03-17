"""
Unified document structure model.

All pipelines output this common structure:
Document → Page[] → Block[]
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time
import uuid


class PageType(str, Enum):
    """Classification of a PDF page."""
    NATIVE = "native"
    SCANNED = "scanned"
    HYBRID = "hybrid"


class BlockType(str, Enum):
    """Type of content block."""
    TEXT = "text"
    IMAGE = "image"


class TaskStatus(str, Enum):
    """Status of a conversion task."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BBox:
    """Bounding box in page coordinates (points)."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    def overlaps(self, other: "BBox", threshold: float = 0.5) -> bool:
        """Check if this bbox significantly overlaps with another."""
        ix0 = max(self.x0, other.x0)
        iy0 = max(self.y0, other.y0)
        ix1 = min(self.x1, other.x1)
        iy1 = min(self.y1, other.y1)

        if ix0 >= ix1 or iy0 >= iy1:
            return False

        intersection = (ix1 - ix0) * (iy1 - iy0)
        min_area = min(self.area, other.area)
        if min_area == 0:
            return False

        return (intersection / min_area) > threshold


@dataclass
class Block:
    """A content block on a page."""
    type: BlockType
    bbox: BBox
    content: str  # Text content or base64-encoded image data
    font_size: Optional[float] = None
    font_name: Optional[str] = None
    font_color: Optional[tuple[int, int, int]] = None  # RGB
    align: Optional[str] = None  # "left", "center", "right"
    confidence: Optional[float] = None  # OCR confidence score
    image_bytes: Optional[bytes] = None  # Raw image bytes for ImageBlock


@dataclass
class Page:
    """A single page in the document."""
    page_number: int  # 0-indexed
    width: float  # in points
    height: float  # in points
    page_type: PageType
    blocks: list[Block] = field(default_factory=list)
    background_image: Optional[bytes] = None  # Full page rendered as image
    errors: list[str] = field(default_factory=list)


@dataclass
class Document:
    """The unified document model."""
    pages: list[Page] = field(default_factory=list)
    source_path: Optional[str] = None
    total_pages: int = 0


@dataclass
class TaskRecord:
    """Tracks conversion task state."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.QUEUED
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    total_pages: int = 0
    processed_pages: int = 0
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "total_pages": self.total_pages,
            "processed_pages": self.processed_pages,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskRecord":
        data["status"] = TaskStatus(data["status"])
        return cls(**data)
