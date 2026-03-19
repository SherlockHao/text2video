from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.task import TaskCreate, TaskListResponse, TaskResponse
from app.dependencies import get_arq_pool, get_db
from app.repositories.task_repo import TaskRepository

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201, response_model=TaskResponse)
async def submit_task(
    body: TaskCreate,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> TaskResponse:
    """Submit a new AI task."""
    repo = TaskRepository(db)
    task = await repo.create({
        "project_id": body.project_id,
        "task_type": body.task_type.value,
        "status": "pending",
        "input_params": body.input_params,
    })
    await db.commit()

    if arq_pool is not None:
        await arq_pool.enqueue_job("process_ai_task", str(task.id))

    return TaskResponse.model_validate(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Get task status by ID."""
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> TaskResponse:
    """Retry a specific failed task."""
    repo = TaskRepository(db)
    original = await repo.get_by_id(task_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if original.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried")

    # Create a new retry task based on the original
    new_task = await repo.create({
        "project_id": original.project_id,
        "task_type": original.task_type,
        "status": "pending",
        "provider_name": original.provider_name,
        "input_params": original.input_params,
        "shot_id": original.shot_id,
        "parent_task_id": original.id,
        "retry_count": original.retry_count + 1,
    })
    await db.commit()

    if arq_pool is not None:
        await arq_pool.enqueue_job("process_ai_task", str(new_task.id))

    return TaskResponse.model_validate(new_task)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Cancel a running or queued task."""
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("pending", "queued", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task with status '{task.status}'",
        )

    task = await repo.update(task_id, {"status": "cancelled"})
    await db.commit()
    return TaskResponse.model_validate(task)


@router.get("/projects/{project_id}", response_model=TaskListResponse)
async def list_project_tasks(
    project_id: UUID,
    task_type: str | None = Query(None, description="Filter by task type"),
    status: str | None = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    """List all tasks for a project, with optional filters."""
    repo = TaskRepository(db)
    tasks = await repo.get_by_project_id(project_id, task_type=task_type, status=status)
    return TaskListResponse(
        tasks=[TaskResponse.model_validate(t) for t in tasks],
        total=len(tasks),
    )
