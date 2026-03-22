"""
工作流注册表 — 管理所有可用的工作流模板
"""

from .base import BaseWorkflow

_registry: dict[str, type[BaseWorkflow]] = {}


def register_workflow(cls: type[BaseWorkflow]):
    """装饰器：注册工作流模板。"""
    _registry[cls.name] = cls
    return cls


def get_workflow(name: str) -> BaseWorkflow:
    """根据名称获取工作流实例。"""
    cls = _registry.get(name)
    if cls is None:
        available = list(_registry.keys())
        raise ValueError(f"Unknown workflow '{name}'. Available: {available}")
    return cls()


def list_workflows() -> list[dict]:
    """列出所有已注册的工作流模板。"""
    return [
        {"name": cls.name, "display_name": cls.display_name, "stages": cls.stages}
        for cls in _registry.values()
    ]
