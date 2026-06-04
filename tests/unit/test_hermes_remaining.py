"""Unit tests for User Modeling (Hermes M12) and Modal Backend (M10)."""
import pytest


class TestUserModelingService:
    @pytest.mark.asyncio
    async def test_new_user_returns_empty_model(self, tmp_path):
        from weebot.application.services.user_modeling import UserModelingService

        svc = UserModelingService(models_dir=str(tmp_path))
        model = await svc.load_model("new-user")
        assert model.user_id == "new-user"
        assert model.interaction_count == 0

    @pytest.mark.asyncio
    async def test_record_observation(self, tmp_path):
        from weebot.application.services.user_modeling import UserModelingService

        svc = UserModelingService(models_dir=str(tmp_path))
        await svc.record_observation("user-1", "preference", "Prefers Python", confidence=0.8)
        model = await svc.load_model("user-1")
        assert model.interaction_count == 1
        assert len(model.observations) == 1
        assert model.observations[0].observation == "Prefers Python"

    @pytest.mark.asyncio
    async def test_infer_preference(self, tmp_path):
        from weebot.application.services.user_modeling import UserModelingService

        svc = UserModelingService(models_dir=str(tmp_path))
        await svc.infer_preference("user-1", "language", "python")
        model = await svc.load_model("user-1")
        assert model.preferences.get("language") == "python"

    @pytest.mark.asyncio
    async def test_context_summary(self, tmp_path):
        from weebot.application.services.user_modeling import UserModelingService

        svc = UserModelingService(models_dir=str(tmp_path))
        await svc.infer_preference("user-1", "language", "python")
        await svc.record_observation("user-1", "skill", "Expert in async Python")
        summary = await svc.get_context_summary("user-1")
        assert "python" in summary.lower()
        assert "expert" in summary.lower()


class TestModalSandboxBackend:
    @pytest.mark.asyncio
    async def test_execute_not_available_fallback(self):
        """When Modal is not available, returns graceful error."""
        from weebot.infrastructure.sandbox.modal_backend import ModalSandboxBackend
        import weebot.infrastructure.sandbox.modal_backend as mb

        original = mb._MODAL_AVAILABLE
        mb._MODAL_AVAILABLE = False
        try:
            backend = ModalSandboxBackend()
            result = await backend.execute(["echo", "hello"])
            assert not result.success
            assert "not available" in result.stderr.lower()
        finally:
            mb._MODAL_AVAILABLE = original
