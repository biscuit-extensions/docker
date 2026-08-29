from __future__ import annotations

import typing

from .extension import Docker

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


def setup(api: ExtensionsAPI) -> Docker:
    """Entrypoint for Biscuit to load the extension."""
    ext = Docker(api)
    api.register("docker", ext)
    ext.install()
    return ext
