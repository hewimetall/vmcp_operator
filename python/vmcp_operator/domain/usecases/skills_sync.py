"""Compute skills directory sync plan for one Gateway PVC."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SkillFile:
    name: str
    content: str
    managed: bool


@dataclass(frozen=True, slots=True)
class SkillsSyncPlan:
    write: tuple[SkillFile, ...]
    delete: tuple[str, ...]
    keep: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanSkillsSync:
    """Profile-managed names win; unrelated admin-created skills persist."""

    def execute(
        self,
        *,
        desired_managed: tuple[SkillFile, ...],
        existing_names: tuple[str, ...],
        previously_managed_names: tuple[str, ...],
    ) -> SkillsSyncPlan:
        desired_by_name = {skill.name: skill for skill in desired_managed}
        if len(desired_by_name) != len(desired_managed):
            raise ValueError("duplicate managed skill names")
        for skill in desired_managed:
            if not skill.managed:
                raise ValueError(f"skill `{skill.name}` must be marked managed")

        existing = set(existing_names)
        previous = set(previously_managed_names)
        desired = set(desired_by_name)

        delete = tuple(
            sorted(
                name for name in previous if name not in desired and name in existing
            )
        )
        keep = tuple(
            sorted(name for name in existing if name not in desired and name not in previous)
        )
        write = tuple(desired_by_name[name] for name in sorted(desired))
        return SkillsSyncPlan(write=write, delete=delete, keep=keep)
