"""Installed distribution metadata for the deployment canary."""

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "crc-lnm-medical-agent"


def package_version() -> str:
    """Return the installed wheel version without maintaining a second version."""

    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0+unknown"


__all__ = ["PACKAGE_NAME", "package_version"]
