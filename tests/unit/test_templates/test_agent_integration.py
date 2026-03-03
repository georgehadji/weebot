"""Tests for agent system integration."""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, AsyncMock
import asyncio


class TestTemplateAgentManager:
    """Test TemplateAgentManager."""
    
    @pytest.fixture
    def mock_agent_system(self):
        """Mock the agent system availability."""
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", True):
            with patch("weebot.templates.agent_integration.AgentFactory") as mock_factory:
                with patch("weebot.templates.agent_integration.WeebotAgent") as mock_agent:
                    yield mock_factory, mock_agent
    
    def test_manager_creation(self, mock_agent_system):
        """Create agent manager."""
        from weebot.templates.agent_integration import TemplateAgentManager
        
        manager = TemplateAgentManager()
        assert manager is not None
        assert manager.agent_factory is not None
    
    def test_manager_creation_no_agent_system(self):
        """Manager creation fails without agent system."""
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", False):
            from weebot.templates.agent_integration import TemplateAgentManager
            
            with pytest.raises(RuntimeError):
                TemplateAgentManager()
    
    def test_get_or_create_agent_caching(self, mock_agent_system):
        """Agent caching works correctly."""
        from weebot.templates.agent_integration import TemplateAgentManager
        
        mock_factory, mock_agent = mock_agent_system
        
        # Create different instances for each call
        instances = {}
        def create_instance(*args, **kwargs):
            instance = Mock()
            # Track calls to know which role this is for
            if not hasattr(create_instance, 'call_count'):
                create_instance.call_count = 0
            idx = create_instance.call_count
            create_instance.call_count += 1
            instances[idx] = instance
            return instance
        
        mock_agent.side_effect = create_instance
        
        manager = TemplateAgentManager()
        
        # First call creates agent
        agent1 = manager.get_or_create_agent("researcher")
        assert agent1 is not None
        
        # Second call returns cached
        agent2 = manager.get_or_create_agent("researcher")
        assert agent2 is agent1
        
        # Different role creates new agent
        agent3 = manager.get_or_create_agent("analyst")
        assert agent3 is not agent1
    
    def test_get_system_prompt_for_role(self, mock_agent_system):
        """System prompts are role-specific."""
        from weebot.templates.agent_integration import TemplateAgentManager
        
        manager = TemplateAgentManager()
        
        # Check specific roles have different prompts
        researcher_prompt = manager._get_system_prompt_for_role("researcher")
        analyst_prompt = manager._get_system_prompt_for_role("analyst")
        writer_prompt = manager._get_system_prompt_for_role("writer")
        
        assert "research" in researcher_prompt.lower()
        assert "analyst" in analyst_prompt.lower()
        assert "writer" in writer_prompt.lower()
        
        # Unknown role gets default
        default_prompt = manager._get_system_prompt_for_role("unknown_role")
        assert "assistant" in default_prompt.lower()
    
    def test_get_agent_info(self, mock_agent_system):
        """Get agent manager info."""
        from weebot.templates.agent_integration import TemplateAgentManager
        
        manager = TemplateAgentManager()
        info = manager.get_agent_info()
        
        assert "cached_agents" in info
        assert "available_roles" in info
        assert "researcher" in info["available_roles"]
        assert "analyst" in info["available_roles"]
    
    def test_clear_cache(self, mock_agent_system):
        """Clear agent cache."""
        from weebot.templates.agent_integration import TemplateAgentManager
        
        mock_factory, mock_agent = mock_agent_system
        mock_agent.return_value = Mock()
        
        manager = TemplateAgentManager()
        
        # Create some agents
        manager.get_or_create_agent("researcher")
        manager.get_or_create_agent("analyst")
        
        assert len(manager._agent_cache) == 2
        
        # Clear cache
        manager.clear_cache()
        assert len(manager._agent_cache) == 0
    
    @pytest.mark.asyncio
    async def test_execute_task(self, mock_agent_system):
        """Execute task with agent."""
        from weebot.templates.agent_integration import TemplateAgentManager
        
        mock_factory, mock_agent = mock_agent_system
        mock_instance = Mock()
        mock_instance.run = AsyncMock()
        mock_instance.get_status = Mock(return_value={"progress": 1})
        mock_agent.return_value = mock_instance
        
        manager = TemplateAgentManager()
        
        result = await manager.execute_task(
            role="researcher",
            task="Research Python"
        )
        
        assert result["success"] is True
        assert result["agent_role"] == "researcher"
        assert result["task"] == "Research Python"
        mock_instance.run.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_task_failure(self, mock_agent_system):
        """Handle task execution failure."""
        from weebot.templates.agent_integration import TemplateAgentManager
        
        mock_factory, mock_agent = mock_agent_system
        mock_instance = Mock()
        mock_instance.run = AsyncMock(side_effect=Exception("Agent failed"))
        mock_agent.return_value = mock_instance
        
        manager = TemplateAgentManager()
        
        result = await manager.execute_task(
            role="researcher",
            task="Research Python"
        )
        
        assert result["success"] is False
        assert "error" in result


class TestTemplateAgentTaskHandler:
    """Test TemplateAgentTaskHandler."""
    
    def test_handler_simulation_mode(self):
        """Handler detects simulation mode."""
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", False):
            from weebot.templates.agent_integration import TemplateAgentTaskHandler
            
            handler = TemplateAgentTaskHandler()
            assert handler.is_simulation_mode() is True
    
    def test_simulate_execution(self):
        """Simulation returns proper response."""
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", False):
            from weebot.templates.agent_integration import TemplateAgentTaskHandler
            
            handler = TemplateAgentTaskHandler()
            
            result = handler._simulate_execution("researcher", "Test task")
            
            assert result["success"] is True
            assert result["agent_role"] == "researcher"
            assert result["task"] == "Test task"
            assert result["simulation"] is True
            assert "note" in result["result"]


class TestHelperFunctions:
    """Test helper functions."""
    
    def test_register_agent_handlers(self):
        """Register handlers with engine."""
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", True):
            with patch("weebot.templates.agent_integration.TemplateAgentManager"):
                from weebot.templates.agent_integration import register_agent_handlers
                from weebot.templates import TemplateEngine
                
                engine = TemplateEngine()
                engine.register_task_handler = Mock()
                
                register_agent_handlers(engine)
                
                engine.register_task_handler.assert_called_once()
    
    def test_create_agent_enabled_engine(self):
        """Create engine with agent support."""
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", True):
            with patch("weebot.templates.agent_integration.TemplateAgentManager"):
                from weebot.templates.agent_integration import create_agent_enabled_engine
                
                engine, manager = create_agent_enabled_engine(load_builtin=False)
                
                assert engine is not None
                assert manager is not None


class TestRoleProfiles:
    """Test role profile definitions."""
    
    def test_role_profiles_exist(self):
        """Role profiles are defined."""
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", True):
            with patch("weebot.templates.agent_integration.AgentFactory"):
                from weebot.templates.agent_integration import TemplateAgentManager
                
                manager = TemplateAgentManager()
                
                # Check all expected roles exist
                expected_roles = [
                    "researcher", "analyst", "writer", "reviewer",
                    "developer", "tester", "default"
                ]
                
                for role in expected_roles:
                    assert role in manager.ROLE_PROFILES
                    assert "description" in manager.ROLE_PROFILES[role]
                    assert "tools" in manager.ROLE_PROFILES[role]


class TestIntegrationWithTemplates:
    """Test integration with actual templates."""
    
    def test_code_review_template_execution(self):
        """Execute code review template."""
        with patch("weebot.templates.agent_integration.HAS_AGENT_SYSTEM", False):
            from weebot.templates import TemplateEngine
            from weebot.templates.agent_integration import register_agent_handlers
            
            engine = TemplateEngine()
            engine.registry.load_builtin_templates()
            
            # Register handlers
            register_agent_handlers(engine)
            
            # Check template exists
            if engine.registry.has_template("Code Review Workflow"):
                result = engine.execute(
                    "Code Review Workflow",
                    {
                        "code_source": "test.py",
                        "language": "python",
                        "review_type": "quick"
                    }
                )
                
                # Should succeed in simulation mode
                assert result.success is True
                assert len(result.task_results) > 0
