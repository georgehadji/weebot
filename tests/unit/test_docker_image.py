"""Unit tests for Docker sandbox image resolution (Enhancement 5).

Covers:
- _resolve_image() returns CUSTOM_IMAGE when it exists
- _resolve_image() falls back to DEFAULT_IMAGE when custom is missing
- _resolve_image() falls back when Docker is unavailable
- Dockerfile exists at the expected path
"""
import pytest


class TestDockerImageResolution:
    """Validates DockerLinuxSandbox._resolve_image() fallback logic."""

    @pytest.mark.asyncio
    async def test_uses_custom_image_when_available(self, mocker):
        """When the custom image exists, _resolve_image returns it."""
        from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox

        sandbox = DockerLinuxSandbox()

        # Mock create_subprocess_exec so docker inspect succeeds
        mock_proc = mocker.AsyncMock()
        mock_proc.returncode = 0
        mocker.patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_proc,
        )

        image = await sandbox._resolve_image()
        assert image == DockerLinuxSandbox.CUSTOM_IMAGE

    @pytest.mark.asyncio
    async def test_falls_back_when_custom_image_missing(self, mocker):
        """When the custom image is not found, _resolve_image returns DEFAULT_IMAGE."""
        from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox

        sandbox = DockerLinuxSandbox()

        # Mock docker image inspect to fail (returncode 1)
        mock_proc = mocker.AsyncMock()
        mock_proc.returncode = 1
        mocker.patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_proc,
        )

        image = await sandbox._resolve_image()
        assert image == DockerLinuxSandbox.DEFAULT_IMAGE

    @pytest.mark.asyncio
    async def test_falls_back_when_docker_unavailable(self, mocker):
        """When docker inspect raises, _resolve_image returns DEFAULT_IMAGE."""
        from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox

        sandbox = DockerLinuxSandbox()

        # Mock create_subprocess_exec to raise (Docker not installed)
        mocker.patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("docker not found"),
        )

        image = await sandbox._resolve_image()
        assert image == DockerLinuxSandbox.DEFAULT_IMAGE

    @pytest.mark.asyncio
    async def test_uses_explicit_image_when_provided(self, mocker):
        """When an explicit image is passed to the constructor, it is used as-is."""
        from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox

        sandbox = DockerLinuxSandbox(image="my-custom-image:latest")

        # Should resolve immediately without calling docker inspect
        image = await sandbox._resolve_image()
        assert image == "my-custom-image:latest"


class TestDockerfile:
    """Validates the Dockerfile exists at the expected location."""

    def test_tool_env_dockerfile_exists(self):
        """The weebot-tool-env.Dockerfile must exist at docker/."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        dockerfile = root / "docker" / "weebot-tool-env.Dockerfile"
        assert dockerfile.exists(), (
            f"Expected {dockerfile} to exist. "
            "Run the build step from Enhancement 5."
        )

    def test_tool_env_dockerfile_is_valid(self):
        """The Dockerfile should have at least a FROM instruction."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        content = (root / "docker" / "weebot-tool-env.Dockerfile").read_text()
        assert content.startswith("FROM"), "Dockerfile must start with FROM"
        assert "LABEL org.weebot.image" in content, (
            "Dockerfile must have weebot labels"
        )
