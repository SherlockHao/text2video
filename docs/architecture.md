# Server-Side Architecture Design

> Project: AI Text-to-Video Marketing Production Tool
> Version: v1.0 MVP (Phase 1: Narration × Manga)
> Date: 2026-03-19

## 1. System Overview

### 1.1 Core Pipeline

```
脚本输入 → 敏感词检测 → LLM剧本拆解 → 角色/分镜生图(抽卡) → 视频生成 → TTS配音 → FFmpeg组装 → MP4+ZIP导出
```

### 1.2 Tech Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| Web Framework | FastAPI (async) |
| Database | PostgreSQL 15 (JSONB for storyboard data) |
| Task Queue | Redis 7 + arq |
| Object Storage | Alibaba Cloud OSS (local filesystem for dev) |
| Container | Docker + docker-compose |
| Video Processing | FFmpeg (via ffmpeg-python) |

### 1.3 External AI APIs

| Provider | API | Purpose |
|----------|-----|---------|
| Qwen 3.5-Plus | Alibaba Cloud DashScope | LLM script breakdown (primary) |
| Jimeng (即梦) | Volcengine | Manga-style image generation |
| Kling (可灵) | Kuaishou | Video generation (normal quality) |
| Seedance2 (即梦) | Volcengine | Video generation (high quality) |
| ElevenLabs | ElevenLabs | TTS voiceover |

## 2. Data Model

### 2.1 Entity Relationship

```
User 1---* Project
Project 1---* Storyboard (versioned script breakdowns)
Storyboard 1---* Shot (individual storyboard frames)
Shot *---* Character (character references used in shot)
Character 1---* CharacterImage (gacha candidates)
Project 1---1 TTSConfig (voice settings)
Project 1---* AITask (hierarchical task tree via parent_task_id)
AITask ---* Asset (generated artifacts)
```

### 2.2 New Models

#### Storyboard
- `id` UUID PK
- `project_id` UUID FK → projects
- `version` INT (allows re-breakdown)
- `scene_count` INT
- `shots_per_minute` FLOAT (derived from quality_tier)
- `raw_llm_response` JSONB (full LLM output for debug)
- `status` VARCHAR (pending/completed/failed)

#### Shot (core unit of work)
- `id` UUID PK
- `storyboard_id` UUID FK → storyboards
- `sequence_number` INT (1-based ordering)
- `scene_number` INT
- `image_prompt` TEXT (LLM-generated prompt for image gen)
- `narration_text` TEXT (voiceover text)
- `scene_description` TEXT
- `character_ids` JSONB (array of character UUIDs)
- `selected_image_id` UUID FK → assets (user-picked from gacha)
- `generated_video_id` UUID FK → assets
- `tts_audio_id` UUID FK → assets
- `image_status` VARCHAR (pending/generating/selection/completed/failed)
- `video_status` VARCHAR
- `tts_status` VARCHAR
- `duration_seconds` FLOAT (computed from TTS audio length)

#### Character (global shared library)
- `id` UUID PK
- `user_id` UUID FK → users (owner, NOT project-scoped)
- `name` VARCHAR
- `description` TEXT
- `tags` JSONB (array: genre, gender, style for search)
- `visual_style` VARCHAR (e.g., "manga")
- `reference_image_id` UUID FK → assets (chosen canonical image)
- `seed_value` INT (for image gen reproducibility)

#### CharacterImage (gacha candidates)
- `id` UUID PK
- `character_id` UUID FK → characters
- `asset_id` UUID FK → assets
- `generation_seed` INT
- `generation_params` JSONB
- `is_selected` BOOLEAN
- `attempt_number` INT (1-3)

#### TTSConfig
- `id` UUID PK
- `project_id` UUID FK → projects (unique)
- `voice_id` VARCHAR (ElevenLabs voice identifier)
- `speed` FLOAT (default 1.0)
- `stability` FLOAT (default 0.5)
- `similarity_boost` FLOAT (default 0.75)
- `language` VARCHAR (default "zh")

#### SensitiveWordHit (audit log)
- `id` UUID PK
- `project_id` UUID FK → projects
- `text_segment` TEXT
- `matched_keywords` JSONB
- `action_taken` VARCHAR (blocked/warned)

### 2.3 Modified Models

#### Project (add columns)
- `content_type` VARCHAR (default "narration") — narration/dialogue/promotion
- `visual_style` VARCHAR (default "manga") — manga/realistic/pet/digital_human
- `aspect_ratio` VARCHAR — "16:9" or "9:16"
- `duration_target` INT — 60 or 120 seconds
- `quality_tier` VARCHAR — "normal" or "high"
- `source_text` TEXT — raw novel input (up to 50K chars)
- `current_step` VARCHAR — pipeline checkpoint: draft/script_breakdown/visual_design/video_gen/tts/assembly/completed

#### AITask (add columns)
- `parent_task_id` UUID FK → ai_tasks (hierarchical tasks)
- `shot_id` UUID FK → shots (link task to specific shot)
- `step_name` VARCHAR (human-readable: "script_breakdown", "image_gen_shot_3")
- `retry_count` INT (default 0)
- `max_retries` INT (default 3)
- `provider_name` VARCHAR (qwen/jimeng/kling/seedance2/elevenlabs)
- `external_job_id` VARCHAR (job ID from external API for polling)
- `checkpoint_data` JSONB (arbitrary state for resume)
- `priority` INT (default 0)

#### Asset (add columns)
- `asset_category` VARCHAR — character_ref/shot_image_candidate/shot_image_selected/shot_video/tts_audio/final_video/asset_package
- `source_task_id` UUID FK → ai_tasks
- `oss_url` VARCHAR (CDN/OSS public URL)
- `project_id` — change to NULLABLE (character assets are project-independent)

### 2.4 Enums

```python
ContentType: narration, dialogue, promotion
VisualStyle: manga, realistic, pet, digital_human
AspectRatio: "16:9", "9:16"
QualityTier: normal, high
ProjectStep: draft, script_breakdown, visual_design, video_gen, tts, assembly, completed
TaskType: script_breakdown, image_generation, video_generation, tts_generation, assembly, sensitive_word_check
TaskStatus: pending, queued, running, completed, failed, cancelled
ShotStatus: pending, generating, selection, completed, failed
AssetCategory: character_ref, shot_image_candidate, shot_image_selected, shot_video, tts_audio, final_video, asset_package
```

## 3. Pipeline Orchestration

### 3.1 Task Hierarchy

```
Project Pipeline (root)
  ├── ScriptBreakdown (1 task, sync-ish)
  │     └── Creates: Storyboard + N Shots
  ├── ImageGeneration (N tasks, parallel, one per shot)
  │     └── User confirms selection (pipeline pauses here)
  ├── TTSGeneration (N tasks, parallel, one per shot)
  │     └── Can start after storyboard, parallel with image gen
  ├── VideoGeneration (N tasks, parallel, one per shot)
  │     └── Depends on: selected image for each shot
  └── Assembly (1 task)
        └── Depends on: ALL video + ALL TTS completed
```

### 3.2 Checkpoint/Resume

- Each Shot tracks independent status per phase (image_status, video_status, tts_status)
- AITask.checkpoint_data stores external_job_id after submission — retry skips re-submission
- Project.current_step is coarse checkpoint — resume identifies failed tasks in current step
- If Shot 7/12 fails video gen, Shots 1-6 are already completed and won't re-run

### 3.3 Quality Tier Routing

```
(video_generation, normal)  → Kling API
(video_generation, high)    → Seedance2 API
(image_generation, *)       → Jimeng API
(tts_generation, *)         → ElevenLabs API
(script_breakdown, *)       → Qwen 3.5-Plus API
```

### 3.4 Concurrency Control

- Per-project: max 5 concurrent external API tasks (configurable)
- Global: arq worker max_jobs setting
- Per-provider: Redis-based semaphore for rate limiting

## 4. API Endpoints

All under `/api/v1`.

### 4.1 Projects
| Method | Path | Description |
|--------|------|-------------|
| POST | `/projects` | Create project (content_type, visual_style, aspect_ratio, duration_target, quality_tier, source_text) |
| GET | `/projects` | List projects (paginated) |
| GET | `/projects/{id}` | Get project detail |
| PUT | `/projects/{id}` | Update project |
| DELETE | `/projects/{id}` | Soft-delete |
| GET | `/projects/{id}/status` | Aggregate progress (per-shot, per-phase) |

### 4.2 Script & Storyboard
| Method | Path | Description |
|--------|------|-------------|
| POST | `/projects/{id}/script/check` | Sensitive word detection |
| POST | `/projects/{id}/storyboard/generate` | Trigger LLM breakdown (async) |
| GET | `/projects/{id}/storyboard` | Get storyboard with all shots |
| PUT | `/projects/{id}/storyboard/shots/{shot_id}` | Edit shot prompt/narration |
| POST | `/projects/{id}/storyboard/regenerate` | Re-run LLM (new version) |

### 4.3 Characters
| Method | Path | Description |
|--------|------|-------------|
| GET | `/characters` | List character library (filter by tags, style) |
| POST | `/characters` | Create character |
| GET | `/characters/{id}` | Get character with images |
| PUT | `/characters/{id}` | Update character |
| DELETE | `/characters/{id}` | Soft-delete |
| POST | `/characters/{id}/generate-image` | Trigger gacha (Jimeng) |
| GET | `/characters/{id}/images` | List gacha candidates |
| POST | `/characters/{id}/images/{img_id}/select` | Pick canonical image |

### 4.4 Shot Images
| Method | Path | Description |
|--------|------|-------------|
| POST | `/projects/{id}/shots/{shot_id}/generate-image` | Generate shot image |
| GET | `/projects/{id}/shots/{shot_id}/images` | List image candidates |
| POST | `/projects/{id}/shots/{shot_id}/images/{img_id}/select` | Pick image |
| POST | `/projects/{id}/shots/generate-images-batch` | Batch image gen for all pending shots |

### 4.5 Video Generation
| Method | Path | Description |
|--------|------|-------------|
| POST | `/projects/{id}/shots/{shot_id}/generate-video` | Trigger video gen (auto-routes by quality) |
| POST | `/projects/{id}/video/generate-batch` | Batch video gen for all shots |
| GET | `/projects/{id}/video/progress` | Aggregate video gen progress |

### 4.6 TTS
| Method | Path | Description |
|--------|------|-------------|
| GET | `/tts/voices` | List available voices |
| PUT | `/projects/{id}/tts/config` | Set TTS config |
| POST | `/projects/{id}/tts/preview` | Preview TTS for short text |
| POST | `/projects/{id}/tts/generate-batch` | Generate TTS for all shots |

### 4.7 Assembly
| Method | Path | Description |
|--------|------|-------------|
| POST | `/projects/{id}/assembly/generate` | Trigger FFmpeg assembly (async) |
| GET | `/projects/{id}/assembly/status` | Assembly progress |
| GET | `/projects/{id}/output` | Get MP4 + ZIP download URLs |

### 4.8 Tasks
| Method | Path | Description |
|--------|------|-------------|
| GET | `/tasks/{task_id}` | Get task status/progress/error |
| POST | `/tasks/{task_id}/retry` | Retry failed task (checkpoint resume) |
| POST | `/tasks/{task_id}/cancel` | Cancel task |
| GET | `/projects/{id}/tasks` | List project tasks (filter by type, status) |

## 5. Service Layer

| Service | Responsibilities |
|---------|-----------------|
| **ScriptService** | Sensitive word detection, input validation |
| **StoryboardService** | Trigger LLM breakdown, parse response, manage shots |
| **CharacterService** | Character CRUD, gacha trigger, image selection |
| **ImageGenerationService** | Shot image gen, batch dispatch, selection |
| **VideoGenerationService** | Quality routing, batch dispatch, progress tracking |
| **TTSService** | Config, preview, batch generate |
| **AssemblyService** | Timeline computation, FFmpeg assembly, ZIP packaging |
| **ProjectService** | Status aggregation, step advancement, checkpoint resume |
| **TaskService** | Task lifecycle, retry, cancel, hierarchy management |
| **StorageService** | OSS upload/download, path conventions, CDN URL |

## 6. External API Provider Abstraction

```python
class ExternalAIProvider(ABC):
    provider_name: str

    async def submit_job(self, params: dict) -> str:
        """Submit job, return external_job_id."""

    async def poll_job(self, external_job_id: str) -> JobStatus:
        """Poll status. Returns state + result_url."""

    async def cancel_job(self, external_job_id: str) -> bool:
        """Best-effort cancel."""

    async def download_result(self, result_url: str) -> bytes:
        """Download generated artifact."""
```

Concrete implementations:
- `QwenProvider` — LLM script breakdown
- `JimengProvider` — Image generation (manga)
- `KlingProvider` — Video generation (normal quality)
- `Seedance2Provider` — Video generation (high quality)
- `ElevenLabsProvider` — TTS voiceover

## 7. Config Extensions

```
# LLM
QWEN_API_KEY, QWEN_MODEL (default "qwen-plus")

# Image/Video
JIMENG_API_KEY, JIMENG_BASE_URL
KLING_API_KEY, KLING_BASE_URL
SEEDANCE2_API_KEY, SEEDANCE2_BASE_URL

# TTS
ELEVENLABS_API_KEY, ELEVENLABS_BASE_URL

# Storage
OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET, OSS_BUCKET, OSS_ENDPOINT, OSS_CDN_DOMAIN

# Feature Flags
MULTIMODAL_MODE=false (reserved for future)
LLM_PROVIDER=qwen (switchable)
```
