"""Folder management: validate, scan, preview, register (SPEC §4-5)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db import models
from app.git.service import GitError
from app.services.deps import ServiceBase
from app.services.errors import (
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)


class FolderService(ServiceBase):
    async def list(self) -> list[models.Folder]:
        result = await self.session.execute(
            select(models.Folder).order_by(models.Folder.display_name)
        )
        return list(result.scalars())

    async def get(self, folder_id: str) -> models.Folder:
        folder = await self.session.get(models.Folder, folder_id)
        if folder is None:
            raise NotFoundError("Folder", folder_id)
        return folder

    async def create(
        self,
        *,
        display_name: str,
        absolute_path: str,
        scan_depth: int = 2,
        auto_discover: bool = True,
    ) -> models.Folder:
        from app.core.security import PathSecurityError, normalize_path

        try:
            resolved = normalize_path(absolute_path, must_exist=True)
        except PathSecurityError as exc:
            raise ValidationFailedError(
                "The folder path could not be used.",
                detail=str(exc),
                next_action="Check the path exists and points to a directory.",
            ) from exc
        if not resolved.is_dir():
            raise ValidationFailedError(
                "The folder path is not a directory.",
                detail=str(resolved),
                next_action="Pick a directory that contains your repositories.",
            )
        existing = await self.session.execute(
            select(models.Folder).where(models.Folder.absolute_path == str(resolved))
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError(
                "This folder is already registered.",
                detail=str(resolved),
                next_action="Open the existing folder instead.",
            )
        folder = models.Folder(
            display_name=display_name.strip() or resolved.name,
            absolute_path=str(resolved),
            scan_depth=max(0, min(scan_depth, 6)),
            auto_discover=auto_discover,
        )
        self.session.add(folder)
        await self.session.flush()
        return folder

    async def update(
        self,
        folder_id: str,
        *,
        display_name: str | None = None,
        scan_depth: int | None = None,
        auto_discover: bool | None = None,
    ) -> models.Folder:
        folder = await self.get(folder_id)
        if display_name is not None:
            folder.display_name = display_name.strip() or folder.display_name
        if scan_depth is not None:
            folder.scan_depth = max(0, min(scan_depth, 6))
        if auto_discover is not None:
            folder.auto_discover = auto_discover
        await self.session.flush()
        return folder

    async def delete(self, folder_id: str) -> None:
        folder = await self.get(folder_id)
        count = await self.session.execute(
            select(func.count(models.Project.id)).where(
                models.Project.folder_id == folder_id
            )
        )
        if count.scalar_one() > 0:
            raise ConflictError(
                "This folder still has registered projects.",
                next_action="Remove the folder's projects first, then delete the folder.",
            )
        await self.session.delete(folder)
        await self.session.flush()

    async def scan(self, folder_id: str) -> dict:
        """Scan the folder for repositories (preview, no writes)."""

        folder = await self.get(folder_id)
        existing = await self.session.execute(
            select(models.Project.absolute_path)
        )
        registered = set(existing.scalars())
        try:
            result = await self.git.scan_folder(
                folder.absolute_path,
                depth=folder.scan_depth,
                existing_paths=registered,
            )
        except GitError as exc:
            raise ValidationFailedError(
                "The folder could not be scanned.",
                detail=exc.stderr or str(exc),
                next_action="Check that Git is installed and the folder is readable.",
            ) from exc
        folder.last_scanned_at = datetime.now(timezone.utc)
        await self.session.flush()
        return {
            "folder_id": folder.id,
            "root": str(result.root),
            "repos": [
                {
                    "path": str(r.path),
                    "name": os.path.basename(str(r.path)),
                    "has_git_file": r.has_git_file,
                    "already_registered": r.already_registered,
                }
                for r in result.repos
            ],
            "errors": result.errors,
        }

    async def register_scanned(
        self, folder_id: str, paths: list[str]
    ) -> list[models.Project]:
        """Register selected scan results as projects under the folder."""

        from app.services.projects import ProjectService

        folder = await self.get(folder_id)
        projects = ProjectService(
            self.session,
            settings=self.settings,
            git=self.git,
            adapter=self.adapter,
            secrets=self.secrets,
        )
        created: list[models.Project] = []
        for path in paths:
            try:
                project = await projects.create(
                    absolute_path=path, folder_id=folder.id
                )
            except ConflictError:
                continue  # already registered — skip, don't fail the batch
            created.append(project)
        return created
