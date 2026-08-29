from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.docker import setup
from src.docker.extension import Docker


class TestDockerExtension:
    def test_extension_setup(self, app_instance) -> None:
        setup(app_instance.api)
        ext = Docker(app_instance.api)
        containers = ext.list_containers()
        assert len(containers) == 2
        assert containers[0]["names"] == ["web_server"]
        assert ext.start_container("c1a2b3c4d5e6") is True
        assert ext.stop_container("c1a2b3c4d5e6") is True
        compose = """services:\n  api:\n    image: node:18\n  cache:\n    image: redis:alpine"""
        services = ext.parse_compose_file(compose)
        assert services == ["api", "cache"]
