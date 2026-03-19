# Development Plan — MVP Phase 1 (Narration × Manga)

> Strategy: Run through one complete pipeline first, then expand horizontally.
> Each phase includes unit tests for all new code.

## Phase Overview

```
Phase 0 (Foundation) → Phase 1 (Sensitive Words) → Phase 2 (Script Breakdown)
                                                          ↓
                                                  ┌─ Phase 3 (Image Gen) ─┐
                                                  │                       │  ← Parallel
                                                  └─ Phase 4 (TTS) ──────┘
                                                          ↓
                                                  Phase 5 (Video Gen)
                                                          ↓
                                                  Phase 6 (Assembly)
                                                          ↓
                                                  Phase 7 (Integration)
                                                          ↓
                                                  Phase 8 (Deploy)
```

---

## Phase 0: Foundation Refactoring

**Goal**: Prepare the codebase for real feature development. No new user-facing features.

### Tasks

- [ ] 0.1 Update `app/core/constants.py` — Add all new enums (ContentType, VisualStyle, AspectRatio, QualityTier, ProjectStep, ShotStatus, AssetCategory, ProviderName)
- [ ] 0.2 Update `app/core/config.py` — Add all external API key fields and feature flags
- [ ] 0.3 Create new DB models — Storyboard, Shot, Character, CharacterImage, TTSConfig, SensitiveWordHit
- [ ] 0.4 Modify existing models — Project (+6 columns), AITask (+8 columns), Asset (+3 columns)
- [ ] 0.5 Generate and apply Alembic migration
- [ ] 0.6 Refactor `app/ai/base.py` — Replace AIProvider with ExternalAIProvider interface (submit_job/poll_job/cancel_job/download_result) + JobStatus dataclass
- [ ] 0.7 Implement ProviderRouter — Replace flat registry with quality-tier-aware routing in `app/ai/providers/__init__.py`
- [ ] 0.8 Implement OSS storage — Fill in `app/storage/oss.py` with Alibaba Cloud oss2 SDK
- [ ] 0.9 Create new repositories — StoryboardRepo, ShotRepo, CharacterRepo, CharacterImageRepo, TTSConfigRepo, SensitiveWordHitRepo
- [ ] 0.10 Add new dependencies to `pyproject.toml` — oss2, ffmpeg-python, dashscope (Qwen), openai, elevenlabs
- [ ] 0.11 Unit tests for all new models, repos, and provider base

### Files Changed
```
app/core/constants.py          (modify)
app/core/config.py             (modify)
app/models/storyboard.py       (new)
app/models/shot.py             (new)
app/models/character.py        (new)
app/models/character_image.py  (new)
app/models/tts_config.py       (new)
app/models/sensitive_word.py   (new)
app/models/project.py          (modify)
app/models/task.py             (modify)
app/models/asset.py            (modify)
app/models/__init__.py          (modify)
app/ai/base.py                 (rewrite)
app/ai/providers/__init__.py   (rewrite)
app/storage/oss.py             (implement)
app/repositories/storyboard_repo.py  (new)
app/repositories/shot_repo.py       (new)
app/repositories/character_repo.py   (new)
app/repositories/character_image_repo.py (new)
app/repositories/tts_config_repo.py  (new)
app/repositories/sensitive_word_repo.py  (new)
alembic/versions/xxx_mvp_schema.py   (new migration)
pyproject.toml                  (modify)
tests/test_models/              (new)
tests/test_repositories/        (new)
```

### Deliverable
- All models can be created in DB via migration
- Provider interface is ready for concrete implementations
- All tests pass

---

## Phase 1: Sensitive Word Filter (Module 8)

**Goal**: Basic keyword detection for script content.

### Tasks
- [ ] 1.1 Create `app/services/script_service.py` — keyword blocklist matching (regex + exact match)
- [ ] 1.2 Create `app/api/v1/scripts.py` — POST `/projects/{id}/script/check`
- [ ] 1.3 Create `app/api/schemas/script.py` — SensitiveCheckRequest, SensitiveCheckResponse
- [ ] 1.4 Create initial blocklist config — load from file or DB
- [ ] 1.5 Unit tests for ScriptService

### Files Changed
```
app/services/script_service.py     (new)
app/api/v1/scripts.py              (new)
app/api/schemas/script.py          (new)
app/api/router.py                  (modify — add scripts router)
data/sensitive_words.txt           (new — default blocklist)
tests/test_services/test_script_service.py (new)
tests/test_api/test_scripts.py     (new)
```

### Deliverable
- API returns list of matched sensitive words for given text
- Tests cover: clean text, single hit, multiple hits, edge cases

---

## Phase 2: Script Input + Storyboard Breakdown (Module 1+2)

**Goal**: User inputs novel text → LLM generates storyboard with shots.

### Tasks
- [ ] 2.1 Implement `app/ai/providers/qwen.py` — QwenProvider using DashScope SDK
- [ ] 2.2 Verify Qwen API call works — integrate vendor/qwen scripts
- [ ] 2.3 Design storyboard prompt template — JSON output schema, shot count formula
- [ ] 2.4 Create `app/services/storyboard_service.py` — generate, parse LLM response, create Shot records
- [ ] 2.5 Create `app/api/v1/storyboards.py` — all storyboard endpoints
- [ ] 2.6 Create `app/api/schemas/storyboard.py` — Pydantic schemas
- [ ] 2.7 Implement worker handler for `script_breakdown` task type
- [ ] 2.8 Update Project CRUD — full params (content_type, visual_style, etc.)
- [ ] 2.9 Unit tests for QwenProvider, StoryboardService, API endpoints

### Files Changed
```
app/ai/providers/qwen.py           (new)
app/services/storyboard_service.py  (new)
app/api/v1/storyboards.py          (new)
app/api/schemas/storyboard.py      (new)
app/api/v1/projects.py             (modify — implement real CRUD)
app/api/schemas/project.py         (modify — add new fields)
app/api/router.py                  (modify)
app/ai/worker.py                   (modify — add script_breakdown handler)
app/ai/prompts/                    (new directory)
app/ai/prompts/narration_manga.py  (new — prompt template)
tests/test_providers/test_qwen.py  (new)
tests/test_services/test_storyboard.py (new)
tests/test_api/test_storyboards.py (new)
```

### Deliverable
- POST text → get structured storyboard with N shots
- Each shot has: image_prompt, narration_text, scene_description
- Shot count respects quality_tier formula

---

## Phase 3: Character Library + Image Generation / Gacha (Module 3)

**Goal**: Character library with cross-project sharing. Gacha system for image generation.

### Tasks
- [ ] 3.1 Implement `app/ai/providers/jimeng.py` — JimengProvider (submit/poll/download)
- [ ] 3.2 Verify Jimeng API call works — integrate vendor/jimeng scripts
- [ ] 3.3 Create `app/services/character_service.py` — CRUD, gacha trigger, image selection
- [ ] 3.4 Create `app/services/image_generation_service.py` — shot image gen with character ref
- [ ] 3.5 Create `app/api/v1/characters.py` — character library endpoints
- [ ] 3.6 Create `app/api/v1/shots.py` — shot image endpoints
- [ ] 3.7 Create `app/api/schemas/character.py`, `app/api/schemas/shot.py`
- [ ] 3.8 Implement worker handler for `image_generation` task type
- [ ] 3.9 Storage integration — upload images to OSS, create Asset records
- [ ] 3.10 Unit tests

### Files Changed
```
app/ai/providers/jimeng.py              (new)
app/services/character_service.py        (new)
app/services/image_generation_service.py (new)
app/api/v1/characters.py                (new)
app/api/v1/shots.py                     (new)
app/api/schemas/character.py            (new)
app/api/schemas/shot.py                 (new)
app/api/router.py                       (modify)
app/ai/worker.py                        (modify)
tests/test_providers/test_jimeng.py     (new)
tests/test_services/test_character.py   (new)
tests/test_services/test_image_gen.py   (new)
tests/test_api/test_characters.py       (new)
tests/test_api/test_shots.py            (new)
```

### Deliverable
- Character CRUD with tags and cross-project sharing
- Gacha: generate 2-3 image candidates, user picks one
- Shot images generated with character reference for consistency

---

## Phase 4: TTS Voiceover (Module 5)

**Goal**: ElevenLabs TTS integration. Can develop in parallel with Phase 3.

### Tasks
- [ ] 4.1 Implement `app/ai/providers/elevenlabs.py` — ElevenLabsProvider
- [ ] 4.2 Create `app/services/tts_service.py` — config, preview, batch generate
- [ ] 4.3 Create `app/api/v1/tts.py` — TTS endpoints
- [ ] 4.4 Create `app/api/schemas/tts.py`
- [ ] 4.5 Implement worker handler for `tts_generation` task type
- [ ] 4.6 Unit tests

### Files Changed
```
app/ai/providers/elevenlabs.py      (new)
app/services/tts_service.py         (new)
app/api/v1/tts.py                   (new)
app/api/schemas/tts.py              (new)
app/api/router.py                   (modify)
app/ai/worker.py                    (modify)
tests/test_providers/test_elevenlabs.py (new)
tests/test_services/test_tts.py     (new)
tests/test_api/test_tts.py          (new)
```

### Deliverable
- Voice listing, config, preview
- Batch TTS generation for all shots
- Audio duration recorded per shot (used as baseline for assembly)

---

## Phase 5: Video Generation (Module 4)

**Goal**: Generate video clips per shot with quality-tier routing.

### Tasks
- [ ] 5.1 Implement `app/ai/providers/kling.py` — KlingProvider (normal quality)
- [ ] 5.2 Implement `app/ai/providers/seedance2.py` — Seedance2Provider (high quality)
- [ ] 5.3 Create `app/services/video_generation_service.py` — routing, batch, progress
- [ ] 5.4 Create `app/api/v1/videos.py` — video gen endpoints
- [ ] 5.5 Create `app/api/schemas/video.py`
- [ ] 5.6 Implement worker handler for `video_generation` task type — long polling, high retry
- [ ] 5.7 Checkpoint/resume testing — thorough testing of retry + checkpoint
- [ ] 5.8 Unit tests

### Files Changed
```
app/ai/providers/kling.py           (new)
app/ai/providers/seedance2.py       (new → real implementation)
app/services/video_generation_service.py (new)
app/api/v1/videos.py                (new)
app/api/schemas/video.py            (new)
app/api/router.py                   (modify)
app/ai/worker.py                    (modify)
tests/test_providers/test_kling.py  (new)
tests/test_providers/test_seedance2.py (new)
tests/test_services/test_video_gen.py (new)
tests/test_api/test_videos.py       (new)
```

### Deliverable
- Quality routing: normal→Kling, high→Seedance2
- Per-shot video generation with checkpoint/resume
- Failed shot retries without re-running completed shots

---

## Phase 6: Assembly (Module 6)

**Goal**: FFmpeg audio-video alignment, MP4 + ZIP output.

### Tasks
- [ ] 6.1 FFmpeg integration — Python wrapper for: concat clips, overlay TTS, freeze-frame, encode
- [ ] 6.2 Create `app/services/assembly_service.py` — timeline computation, assembly orchestration
- [ ] 6.3 Create `app/api/v1/assembly.py` — assembly trigger and output endpoints
- [ ] 6.4 Create `app/api/schemas/assembly.py`
- [ ] 6.5 Implement worker handler for `assembly` task type
- [ ] 6.6 ZIP packaging — bundle individual shot videos + audio + final MP4
- [ ] 6.7 Unit tests

### Core Logic: Audio-Video Dynamic Alignment
- TTS audio length is the baseline for each shot
- If video is longer: trim to match audio
- If video is shorter: freeze last frame to fill
- Variable speed adjustment (no distortion)
- Dynamic transitions between shots

### Files Changed
```
app/services/assembly_service.py    (new)
app/services/ffmpeg_utils.py        (new — FFmpeg wrapper functions)
app/api/v1/assembly.py              (new)
app/api/schemas/assembly.py         (new)
app/api/router.py                   (modify)
app/ai/worker.py                    (modify)
pyproject.toml                      (add ffmpeg-python dep)
Dockerfile                          (add FFmpeg binary)
tests/test_services/test_assembly.py (new)
tests/test_api/test_assembly.py     (new)
```

### Deliverable
- Full MP4 rough cut with aligned audio-video
- ZIP package with individual assets for CapCut re-editing

---

## Phase 7: Pipeline Orchestration & Integration Testing

**Goal**: Wire everything together, end-to-end test.

### Tasks
- [ ] 7.1 Rewrite `app/ai/pipeline.py` — DAG-aware orchestrator with checkpoint/resume
- [ ] 7.2 Implement `ProjectService.resume_from_checkpoint()`
- [ ] 7.3 Implement `ProjectService.get_project_status()` — aggregate per-shot progress
- [ ] 7.4 Redis-based rate limiting per provider
- [ ] 7.5 End-to-end integration tests — full pipeline: text → MP4
- [ ] 7.6 Error handling hardening — all failure modes, partial retry

### Deliverable
- Complete pipeline runs from text input to MP4 output
- Checkpoint/resume works across all steps
- Rate limiting prevents API throttling

---

## Phase 8: Deployment Optimization

**Goal**: Production-ready Docker setup.

### Tasks
- [ ] 8.1 Update `docker-compose.yml` — dedicated FFmpeg worker, MinIO for local OSS
- [ ] 8.2 Update `Dockerfile` — install FFmpeg binary in image
- [ ] 8.3 Health checks and monitoring — task queue depth, API latency
- [ ] 8.4 Performance tuning — worker concurrency, connection pools

### Deliverable
- `docker compose up` brings up full production-like environment
- Ready for Alibaba Cloud ECS deployment
