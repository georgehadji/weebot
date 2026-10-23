"""OSWorld Settings (sandbox adapters for desktop automation benchmark).

Moved out of ``weebot/config/settings.py`` (ICM fix plan W2.4, F16) so the
main settings module holds only WeebotSettings. The only reader is
``weebot/infrastructure/sandbox/osworld.py``.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OSWorldSettings(BaseSettings):
    """Configuration for the OSWorld sandbox environment.

    Connects to a KVM/Docker container running an OSWorld-compatible VM.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sandbox backend type
    osworld_sandbox_type: str = Field(
        default="docker",
        description=(
            "Sandbox backend: 'kvm' (QEMU/libvirt), 'docker' (container), " "or 'remote' (HTTP API)"
        ),
    )

    # Connection
    osworld_host: str = Field(default="localhost", description="OSWorld VM host address")
    osworld_port: int = Field(default=8080, description="OSWorld VM API port")
    osworld_vm_id: str = Field(
        default="osworld-ubuntu-1", description="OSWorld VM instance identifier"
    )
    osworld_api_token: str = Field(default="", description="Auth token for OSWorld API")

    # Timeouts
    osworld_connect_timeout: int = Field(
        default=30, ge=1, description="Connection timeout in seconds"
    )
    osworld_action_timeout: int = Field(
        default=15, ge=1, description="Per-action timeout in seconds (click, type, screenshot)"
    )
    osworld_boot_timeout: int = Field(
        default=120, ge=10, description="VM boot/wait timeout in seconds"
    )
    osworld_max_retries: int = Field(
        default=3, ge=0, description="Max retries on transient failures"
    )

    # Screen calibration
    osworld_screen_width: int = Field(default=1920, ge=640, description="VM screen width in pixels")
    osworld_screen_height: int = Field(
        default=1080, ge=480, description="VM screen height in pixels"
    )
    osworld_dpi_scale: float = Field(
        default=1.0, ge=0.5, le=4.0, description="DPI scaling factor (1.0 = 96dpi)"
    )

    @property
    def base_url(self) -> str:
        return f"http://{self.osworld_host}:{self.osworld_port}"

    @property
    def screen_resolution(self) -> tuple[int, int]:
        return (self.osworld_screen_width, self.osworld_screen_height)
