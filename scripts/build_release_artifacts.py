"""Build the requested source archive and SHA-256 release manifest."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "crc-lnm-medical-agent-hosted"
VERSION = "1.0.19"
ARCHIVE = ROOT / f"{PACKAGE}-{VERSION}-source.zip"
PREFIX = f"{PACKAGE}-{VERSION}-source"
ROOT_FILES = ["README.md", "MANIFEST.in", "modelscope-mcp.json", "pyproject.toml"]
ROOT_FILES += [".gitignore", "CHANGELOG.md", "RELEASE_CHECKSUMS.sha256"]
TREES = ["src/crc_lnm_mcp", "docs", "reports", "scripts", "tests", ".github"]
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "build",
    "dist",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".pt", ".pth", ".ckpt", ".log"}
PORTABLE_TEXT_SUFFIXES = {
    ".cfg",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sha256",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def included_files() -> list[Path]:
    files = [ROOT / name for name in ROOT_FILES]
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(f"required source archive files missing: {missing}")
    for tree in TREES:
        files.extend(path for path in (ROOT / tree).rglob("*") if path.is_file())
    return sorted(
        path
        for path in files
        if not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
        and not any(part.startswith(".venv") for part in path.relative_to(ROOT).parts)
        and path.suffix.lower() not in FORBIDDEN_SUFFIXES
        and path.name not in {".env"}
        and not path.name.startswith(".env.")
        and "release_1.0.12_before_" not in path.as_posix()
        and "release_1.0.12_" not in path.as_posix()
        and "_backup/" not in path.as_posix()
        and "stage_crc_lnm_" not in path.as_posix()
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_archive_bytes(path: Path) -> bytes | None:
    """Return sanitized text for the portable archive, or None for raw copying."""
    relative = path.relative_to(ROOT)
    sanitize_paths = relative.parts[0] in {"docs", "reports"}
    normalize_text = sanitize_paths or relative.as_posix() == "CHANGELOG.md"
    if not normalize_text:
        return None
    if path.suffix.lower() not in PORTABLE_TEXT_SUFFIXES and path.name != ".gitignore":
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None

    if sanitize_paths:
        separator = r"(?P<sep>\\{1,2})"
        component = r'[^\\/\r\n"`]+'
        windows_release_root = re.compile(
            rf"(?i)\b[A-Z]:{separator}Users(?P=sep){component}"
            rf"(?P=sep)Desktop(?P=sep){component}(?P=sep)release_1\.0\.10"
        )
        windows_user_home = re.compile(
            rf"(?i)\b[A-Z]:{separator}Users(?P=sep){component}"
        )
        wsl_release_root = re.compile(
            r"(?i)/mnt/[a-z]/Users/[^/\s\"`]+/Desktop/[^/\s\"`]+/release_1\.0\.10"
        )
        unix_user_home = re.compile(r"(?i)/ho" + r"me/[^/\s\"`]+")

        text = windows_release_root.sub("<RELEASE_ROOT>", text)
        text = wsl_release_root.sub("<RELEASE_ROOT>", text)
        text = windows_user_home.sub("<TEMP_WORKSPACE>", text)
        text = unix_user_home.sub("<TEMP_WORKSPACE>", text)
        text = re.sub(
            r"(?i)\b[A-Z]:(?P<sep>\\{1,2})",
            r"<TEMP_WORKSPACE>\g<sep>",
            text,
        )
    return (text.rstrip() + "\n").encode("utf-8")


def main() -> int:
    binary_artifacts = [
        *sorted((ROOT / "dist").glob("*.whl")),
        *sorted((ROOT / "dist").glob("*.tar.gz")),
    ]
    if len(binary_artifacts) != 2:
        raise RuntimeError("expected exactly one wheel and one sdist")
    preliminary = [
        f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}"
        for path in binary_artifacts
    ]
    (ROOT / "RELEASE_CHECKSUMS.sha256").write_text(
        "\n".join(preliminary) + "\n", encoding="utf-8"
    )
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in included_files():
            archive_name = f"{PREFIX}/{path.relative_to(ROOT).as_posix()}"
            portable_bytes = portable_archive_bytes(path)
            if portable_bytes is None:
                archive.write(path, archive_name)
            else:
                archive.writestr(archive_name, portable_bytes)
    artifacts = [*binary_artifacts, ARCHIVE]
    if len(artifacts) != 3:
        raise RuntimeError(f"expected wheel, sdist, and source zip; got {artifacts}")
    lines = [f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}" for path in artifacts]
    (ROOT / "RELEASE_CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", "utf-8")
    print(f"source_archive={ARCHIVE.name} files={len(included_files())}")
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
