from enum import Enum


class ContentType(str, Enum):
    NARRATION = "narration"
    DIALOGUE = "dialogue"
    PROMOTION = "promotion"


class VisualStyle(str, Enum):
    MANGA = "manga"
    REALISTIC = "realistic"
    PET = "pet"
    DIGITAL_HUMAN = "digital_human"


class AspectRatio(str, Enum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"


class QualityTier(str, Enum):
    NORMAL = "normal"
    HIGH = "high"


class ProjectStep(str, Enum):
    DRAFT = "draft"
    SCRIPT_BREAKDOWN = "script_breakdown"
    VISUAL_DESIGN = "visual_design"
    VIDEO_GEN = "video_gen"
    TTS = "tts"
    ASSEMBLY = "assembly"
    COMPLETED = "completed"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    SCRIPT_BREAKDOWN = "script_breakdown"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    TTS_GENERATION = "tts_generation"
    ASSEMBLY = "assembly"
    SENSITIVE_WORD_CHECK = "sensitive_word_check"


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ShotStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    SELECTION = "selection"
    COMPLETED = "completed"
    FAILED = "failed"


class AssetCategory(str, Enum):
    CHARACTER_REF = "character_ref"
    SHOT_IMAGE_CANDIDATE = "shot_image_candidate"
    SHOT_IMAGE_SELECTED = "shot_image_selected"
    SHOT_VIDEO = "shot_video"
    TTS_AUDIO = "tts_audio"
    FINAL_VIDEO = "final_video"
    ASSET_PACKAGE = "asset_package"


class FileType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    SUBTITLE = "subtitle"


class ProviderName(str, Enum):
    QWEN = "qwen"
    OPENAI = "openai"
    JIMENG = "jimeng"
    KLING = "kling"
    SEEDANCE2 = "seedance2"
    ELEVENLABS = "elevenlabs"
