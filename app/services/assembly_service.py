import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import AITask
from app.repositories.asset_repo import AssetRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.shot_repo import ShotRepository
from app.repositories.storyboard_repo import StoryboardRepository
from app.repositories.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class AssemblyService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.storyboard_repo = StoryboardRepository(session)
        self.shot_repo = ShotRepository(session)
        self.asset_repo = AssetRepository(session)
        self.task_repo = TaskRepository(session)

    async def check_readiness(self, project_id: UUID) -> dict:
        """Check if project is ready for assembly.

        All shots must have both video_status=completed and tts_status=completed.
        Returns: {ready: bool, shots_ready: int, shots_total: int, missing: [...]}
        """
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        if storyboard is None:
            return {
                "ready": False,
                "shots_ready": 0,
                "shots_total": 0,
                "missing": [],
            }

        shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)
        total = len(shots)
        ready_count = 0
        missing = []

        for shot in shots:
            video_done = shot.video_status == "completed"
            tts_done = shot.tts_status == "completed"

            if video_done and tts_done:
                ready_count += 1
            else:
                reasons = []
                if not video_done:
                    reasons.append(f"video_status={shot.video_status}")
                if not tts_done:
                    reasons.append(f"tts_status={shot.tts_status}")
                missing.append({
                    "shot_id": str(shot.id),
                    "sequence_number": shot.sequence_number,
                    "reasons": reasons,
                })

        return {
            "ready": ready_count == total and total > 0,
            "shots_ready": ready_count,
            "shots_total": total,
            "missing": missing,
        }

    async def trigger_assembly(self, project_id: UUID, arq_pool=None) -> AITask:
        """Trigger the assembly process.

        1. Verify readiness (all shots have video + TTS)
        2. Create AITask with type=assembly
        3. Collect all shot asset paths in input_params:
           {shots: [{shot_id, video_path, audio_path, sequence_number}, ...]}
        4. Enqueue to arq
        5. Update project.current_step = "assembly"
        """
        # 1. Check readiness
        readiness = await self.check_readiness(project_id)
        if not readiness["ready"]:
            raise ValueError(
                f"Project is not ready for assembly. "
                f"{readiness['shots_ready']}/{readiness['shots_total']} shots ready."
            )

        # 2. Gather shot data with asset paths
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)

        shot_data = []
        for shot in shots:
            video_path = ""
            audio_path = ""

            if shot.generated_video_id:
                video_asset = await self.asset_repo.get_by_id(shot.generated_video_id)
                if video_asset:
                    video_path = video_asset.storage_path

            if shot.tts_audio_id:
                audio_asset = await self.asset_repo.get_by_id(shot.tts_audio_id)
                if audio_asset:
                    audio_path = audio_asset.storage_path

            shot_data.append({
                "shot_id": str(shot.id),
                "video_path": video_path,
                "audio_path": audio_path,
                "sequence_number": shot.sequence_number,
            })

        # 3. Create task
        task = await self.task_repo.create({
            "project_id": project_id,
            "task_type": "assembly",
            "status": "pending",
            "provider_name": "internal",
            "input_params": {
                "project_id": str(project_id),
                "shots": shot_data,
            },
        })

        # 4. Update project step
        project = await self.project_repo.get_by_id(project_id)
        if project:
            project.current_step = "assembly"
            await self.session.flush()

        # 5. Enqueue to arq
        if arq_pool is not None:
            await arq_pool.enqueue_job("process_ai_task", str(task.id))

        await self.session.commit()
        return task

    async def get_status(self, project_id: UUID) -> dict:
        """Get assembly status.

        Checks for assembly task, returns progress info.
        """
        # Check readiness first for shot counts
        readiness = await self.check_readiness(project_id)

        # Find the latest assembly task for this project
        tasks = await self.task_repo.get_pending_tasks(limit=1000)
        # We need to look at all tasks, not just pending ones — query directly
        from sqlalchemy import select
        from app.models.task import AITask

        query = (
            select(AITask)
            .where(AITask.project_id == project_id)
            .where(AITask.task_type == "assembly")
            .order_by(AITask.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        task = result.scalar_one_or_none()

        if task is None:
            return {
                "status": "pending",
                "progress": 0.0,
                "final_video_url": None,
                "asset_package_url": None,
                "error": None,
                "shots_ready": readiness["shots_ready"],
                "shots_total": readiness["shots_total"],
            }

        final_video_url = None
        asset_package_url = None

        if task.status == "completed" and task.output_result:
            final_video_url = task.output_result.get("final_video_url")
            asset_package_url = task.output_result.get("asset_package_url")

        return {
            "status": task.status,
            "progress": task.progress,
            "final_video_url": final_video_url,
            "asset_package_url": asset_package_url,
            "error": task.error_message,
            "shots_ready": readiness["shots_ready"],
            "shots_total": readiness["shots_total"],
        }

    async def get_output(self, project_id: UUID) -> dict:
        """Get project output (final video + asset package).

        Looks for assets with category=final_video and asset_package.
        """
        project = await self.project_repo.get_by_id(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        # Get all assets for this project
        assets = await self.asset_repo.get_by_project_id(project_id)

        final_video = None
        asset_package = None

        for asset in assets:
            if asset.asset_category == "final_video":
                final_video = {
                    "asset_id": str(asset.id),
                    "storage_path": asset.storage_path,
                    "file_size": asset.file_size_bytes,
                }
            elif asset.asset_category == "asset_package":
                asset_package = {
                    "asset_id": str(asset.id),
                    "storage_path": asset.storage_path,
                    "file_size": asset.file_size_bytes,
                }

        # Get per-shot output info
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        shots_output = []
        if storyboard:
            shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)
            for shot in shots:
                shot_info = {
                    "shot_id": str(shot.id),
                    "sequence_number": shot.sequence_number,
                    "video_status": shot.video_status,
                    "tts_status": shot.tts_status,
                    "generated_video_id": str(shot.generated_video_id) if shot.generated_video_id else None,
                    "tts_audio_id": str(shot.tts_audio_id) if shot.tts_audio_id else None,
                }
                shots_output.append(shot_info)

        return {
            "project_id": project.id,
            "project_name": project.name,
            "status": project.status,
            "final_video": final_video,
            "asset_package": asset_package,
            "shots": shots_output,
        }
