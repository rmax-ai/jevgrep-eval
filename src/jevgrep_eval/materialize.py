"""Create .git-free, metadata-free workspaces from local fixture trees.

The source may be a checked-out fixture repository.  When a SHA is supplied,
``git archive`` is used as the materialization primitive, so the agent never
receives repository metadata or evaluator-side files.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import subprocess
import tarfile
from collections.abc import Iterable
from pathlib import Path

from .models import WorkspaceFile, WorkspaceManifest
from .util import digest, normalize_path


class MaterializationError(ValueError):
    """A workspace cannot be safely materialized."""


BENCHMARK_METADATA_NAMES = frozenset(
    {
        ".git",
        ".jevgrep-eval",
        ".benchmark",
        "workspace_manifest.json",
        "run-envelope.json",
    }
)
_CORPUS_ARTIFACT_NAMES = frozenset({"gold", "hidden", "evaluator"})

# Tool-generated artifacts are run infrastructure, not task content. Pre-provisioned
# interpreter environments (.venv) contain benign out-of-tree symlinks (bin/python ->
# managed interpreter); populated tool caches (__pycache__, .pytest_cache, ...) appear
# whenever the agent exercises the project's own tooling. None of them may participate
# in workspace manifests/digests or patch capture: a cache that exists post-run but is
# gitignored (and therefore absent from the captured patch) makes patch replay diverge
# from the post-run tree -- observed live as terminal_status=malformed_patch.
WORKSPACE_EXCLUDED_NAMES = frozenset(
    {
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".hypothesis",
        ".tox",
        ".nox",
        ".coverage",
        "node_modules",
    }
)


def is_benchmark_metadata_path(
    relative: str | Path,
    *,
    excluded_names: frozenset[str] = BENCHMARK_METADATA_NAMES,
) -> bool:
    """Return whether ``relative`` names evaluator-owned metadata.

    Metadata names are matched as path components, not substrings, so a
    legitimate source file such as ``src/gold_parser.py`` remains visible.
    Corpus evaluator outputs are a special case: repositories may contain
    nested ``corpus/gold``, ``corpus/hidden``, or ``corpus/evaluator`` trees
    whose contents must never enter an agent workspace.
    """
    parts = Path(relative).parts
    if any(part in excluded_names for part in parts):
        return True
    lowered = tuple(part.casefold() for part in parts)
    for index, part in enumerate(lowered):
        if part != "corpus":
            continue
        if any(
            candidate in _CORPUS_ARTIFACT_NAMES
            for candidate in lowered[index + 1 :]
        ):
            return True
    return False


def _sha256(path: Path) -> str:
    if path.is_symlink():
        return hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    if path.is_dir():
        return digest("")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk(root: Path) -> list[WorkspaceFile]:
    files: list[WorkspaceFile] = []
    for path in sorted(root.rglob("*")):
        relative = normalize_path(path.relative_to(root).as_posix())
        if any(part in WORKSPACE_EXCLUDED_NAMES for part in relative.split("/")):
            continue
        if is_benchmark_metadata_path(relative):
            continue
        if path.is_symlink():
            target = path.resolve()
            if target != root and root not in target.parents:
                raise MaterializationError(f"escaping symlink: {relative}")
            kind = "symlink"
            size = len(os.readlink(path))
        elif path.is_dir():
            kind = "directory"
            size = 0
        elif path.is_file():
            kind = "file"
            size = path.stat().st_size
        else:
            raise MaterializationError(f"special file: {relative}")
        files.append(
            WorkspaceFile(
                path=relative,
                file_type=kind,
                mode=stat.S_IMODE(path.lstat().st_mode),
                size=size,
                sha256=_sha256(path),
            )
        )
    return files


def snapshot(root: Path) -> WorkspaceManifest:
    """Take a deterministic tree snapshot, rejecting benchmark metadata."""
    files = _walk(root)
    tree = [item.model_dump(mode="json") for item in files]
    return WorkspaceManifest(root=str(root), files=files, workspace_digest=digest(tree))


def _validate_destination(destination: Path) -> None:
    if destination.exists():
        raise MaterializationError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)


def _copy_entry(
    item: Path,
    source: Path,
    target: Path,
    *,
    excluded: frozenset[str],
) -> None:
    relative = item.relative_to(source)
    if is_benchmark_metadata_path(relative, excluded_names=excluded):
        return
    if item.is_symlink():
        resolved = item.resolve()
        if resolved != source and source not in resolved.parents:
            raise MaterializationError(f"escaping symlink: {item}")
        target.symlink_to(os.readlink(item))
    elif item.is_dir():
        def ignore_metadata(path: str, names: list[str]) -> set[str]:
            current = Path(path)
            return {
                name
                for name in names
                if is_benchmark_metadata_path(
                    current.joinpath(name).relative_to(source),
                    excluded_names=excluded,
                )
            }

        shutil.copytree(
            item,
            target,
            symlinks=True,
            ignore=ignore_metadata,
            ignore_dangling_symlinks=False,
        )
    elif item.is_file():
        shutil.copy2(item, target)
    else:
        raise MaterializationError(f"special file: {item}")


def _archive_extract(
    source: Path,
    sha: str,
    destination: Path,
    *,
    excluded: frozenset[str],
) -> None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source), "archive", "--format=tar", sha],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise MaterializationError(f"cannot archive {sha}: {exc}") from exc
    try:
        with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise MaterializationError("git archive contained an escaping path")
                if is_benchmark_metadata_path(member_path, excluded_names=excluded):
                    continue
                target = destination / member_path
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(stat.S_IMODE(member.mode))
                    continue
                if member.islnk():
                    raise MaterializationError(
                        f"archive contains an unsupported hard-link entry: {member.name}"
                    )
                if not (member.isfile() or member.issym()):
                    raise MaterializationError(f"archive contains special entry: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.issym():
                    link = Path(member.linkname)
                    resolved = (target.parent / link).resolve()
                    if resolved != destination and destination not in resolved.parents:
                        raise MaterializationError(f"archive contains escaping symlink: {member.name}")
                    target.symlink_to(member.linkname)
                else:
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise MaterializationError(f"cannot read archive member: {member.name}")
                    target.write_bytes(extracted.read())
                    target.chmod(stat.S_IMODE(member.mode))
    except (tarfile.TarError, OSError) as exc:
        raise MaterializationError(f"cannot extract {sha}: {exc}") from exc


def materialize(
    source: Path,
    destination: Path,
    *,
    sha: str | None = None,
    exclude_names: Iterable[str] = (),
) -> WorkspaceManifest:
    """Materialize a directory or an exact git revision into ``destination``."""
    if not source.is_dir():
        raise MaterializationError(f"source is not a directory: {source}")
    _validate_destination(destination)
    destination.mkdir(parents=True)
    excluded = {*BENCHMARK_METADATA_NAMES, *exclude_names}
    excluded_names = frozenset(str(name) for name in excluded)
    if sha is not None:
        _archive_extract(source, sha, destination, excluded=excluded_names)
    else:
        for item in sorted(source.iterdir(), key=lambda path: path.name):
            if is_benchmark_metadata_path(item.relative_to(source), excluded_names=excluded_names):
                continue
            _copy_entry(item, source, destination / item.name, excluded=excluded_names)
    return snapshot(destination)


def materialize_repo(source: Path, sha: str, destination: Path) -> WorkspaceManifest:
    """Explicit alias used by the CLI and corpus runner."""
    return materialize(source, destination, sha=sha)


def leak_scan(
    root: Path,
    forbidden: tuple[str, ...] = tuple(BENCHMARK_METADATA_NAMES),
) -> list[str]:
    """Return paths matching benchmark metadata names and corpus artifacts."""
    findings: list[str] = []
    for path in root.rglob("*"):
        if is_benchmark_metadata_path(
            path.relative_to(root),
            excluded_names=frozenset(forbidden),
        ):
            findings.append(path.relative_to(root).as_posix())
    return sorted(findings)


def workspace_manifest(root: Path) -> WorkspaceManifest:
    """Public spelling for the runner-side snapshot operation."""
    return snapshot(root)


def workspace_digest(root: Path) -> str:
    return snapshot(root).workspace_digest


materialize_from_git = materialize_repo
