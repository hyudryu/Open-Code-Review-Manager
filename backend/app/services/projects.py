"""Project management: add/edit/remove, branch cache, fetch (SPEC §5-6)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from app.db import models
from app.git.service import GitError, RepoValidationError
from app.services.deps import ServiceBase
from app.services.errors import (
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)


class ProjectService(ServiceBase):
    async def list(self, *, query: str | None = None, include_unavailable: bool = True) -> list[models.Project]:
        stmt = select(models.Project).order_by(models.Project.display_name)
        if query:
            stmt = stmt.where(models.Project.display_name.ilike(f"%{query}%"))
        if not include_unavailable:
            stmt = stmt.where(models.Project.is_available.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get(self, project_id: str) -> models.Project:
        project = await self.session.get(models.Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)
        return project

    async def _existing_paths(self) -> set[str]:
        result = await self.session.execute(select(models.Project.absolute_path))
        return set(result.scalars())

    async def create(
        self,
        *,
        absolute_path: str,
        folder_id: str | None = None,
        display_name: str | None = None,
    ) -> models.Project:
        try:
            info = await self.git.validate_repo(
                absolute_path, existing_paths=await self._existing_paths()
            )
        except RepoValidationError as exc:
            raise ValidationFailedError(
                "The path is not a usable git repository.",
                detail=exc.stderr or str(exc),
                next_action="Pick a folder that contains a non-bare git work tree.",
                extra={"reason": exc.reason},
            ) from exc
        except GitError as exc:
            raise ValidationFailedError(
                "Git could not inspect the repository.",
                detail=exc.stderr or str(exc),
                next_action="Check that Git is installed and the path is readable.",
            ) from exc
        project = models.Project(
            folder_id=folder_id,
            display_name=(display_name or info.path.name).strip(),
            absolute_path=str(info.path),
            git_common_dir=str(info.git_common_dir),
            default_branch=info.default_branch,
            remote_name=info.remote_name,
            remote_url=info.remote_url,
            current_branch=info.current_branch,
            is_dirty=info.is_dirty,
            is_available=True,
        )
        self.session.add(project)
        await self.session.flush()
        await self.refresh_branches(project.id, fetch=False)
        return project

    async def update(
        self,
        project_id: str,
        *,
        display_name: str | None = None,
        default_branch: str | None = None,
        remote_name: str | None = None,
        is_available: bool | None = None,
    ) -> models.Project:
        project = await self.get(project_id)
        if display_name is not None:
            project.display_name = display_name.strip() or project.display_name
        if default_branch is not None:
            project.default_branch = default_branch or None
        if remote_name is not None:
            project.remote_name = remote_name or None
        if is_available is not None:
            project.is_available = is_available
        await self.session.flush()
        return project

    async def delete(self, project_id: str) -> None:
        project = await self.get(project_id)
        count = await self.session.execute(
            select(func.count(models.ReviewJob.id)).where(
                models.ReviewJob.project_id == project_id
            )
        )
        if count.scalar_one() > 0:
            raise ConflictError(
                "This project has review jobs and cannot be removed.",
                next_action="Delete the project's review jobs first.",
            )
        await self.session.delete(project)
        await self.session.flush()

    async def refresh_branches(
        self, project_id: str, *, fetch: bool = False, prune: bool = False
    ) -> tuple[list[models.BranchCache], str | None]:
        """Refresh the branch cache (SPEC §6).

        Returns ``(branches, fetch_error)``; a failed fetch never erases the
        existing cache.
        """

        project = await self.get(project_id)
        try:
            entries, fetch_error = await self.git.refresh_branches(
                project.absolute_path, fetch=fetch, prune=prune
            )
        except GitError as exc:
            if fetch:
                return await self.list_branches(project_id), (exc.stderr or str(exc))
            raise ValidationFailedError(
                "Branches could not be listed for this project.",
                detail=exc.stderr or str(exc),
                next_action="Check the repository still exists and is readable.",
            ) from exc

        now = datetime.now(timezone.utc)
        await self.session.execute(
            delete(models.BranchCache).where(models.BranchCache.project_id == project.id)
        )
        rows = [
            models.BranchCache(
                project_id=project.id,
                name=e.name,
                full_ref=e.full_ref,
                kind=e.kind,
                remote_name=e.remote_name,
                commit_sha=e.commit_sha,
                commit_subject=e.commit_subject,
                commit_timestamp=e.commit_timestamp,
                is_default=e.is_default,
                is_current=e.is_current,
                last_seen_at=now,
            )
            for e in entries
        ]
        self.session.add_all(rows)
        project.last_branch_refresh_at = now
        project.current_branch = next(
            (e.name for e in entries if e.is_current), project.current_branch
        )
        await self.session.flush()
        return rows, fetch_error

    async def list_branches(
        self, project_id: str, *, kind: str | None = None
    ) -> list[models.BranchCache]:
        await self.get(project_id)
        stmt = (
            select(models.BranchCache)
            .where(models.BranchCache.project_id == project_id)
            .order_by(models.BranchCache.kind, models.BranchCache.name)
        )
        if kind:
            stmt = stmt.where(models.BranchCache.kind == kind)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def fetch(self, project_id: str, *, prune: bool = True) -> str | None:
        """Fetch remotes and refresh the cache; returns the fetch error if any."""

        _rows, fetch_error = await self.refresh_branches(project_id, fetch=True, prune=prune)
        return fetch_error

    async def jobs(self, project_id: str) -> list[models.ReviewJob]:
        await self.get(project_id)
        result = await self.session.execute(
            select(models.ReviewJob)
            .where(models.ReviewJob.project_id == project_id)
            .order_by(models.ReviewJob.queued_at.desc())
        )
        return list(result.scalars())
