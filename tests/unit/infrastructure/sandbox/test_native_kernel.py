"""NativeKernel keeps a real child interpreter alive between calls (H17)."""

from __future__ import annotations

import asyncio

import pytest

from weebot.infrastructure.sandbox.native_kernel import NativeKernel


@pytest.fixture
def kernel():
    backend = NativeKernel()
    handles = []

    class _Box:
        async def start(self, session="s"):
            handle = await backend.start(session)
            handles.append(handle)
            return handle

        exec = staticmethod(backend.exec)

    yield _Box()
    for handle in handles:
        asyncio.run(backend.stop(handle))


@pytest.mark.asyncio
async def test_variables_persist_across_calls(kernel):
    handle = await kernel.start()

    first = await kernel.exec(handle, "x = 41", 10)
    second = await kernel.exec(handle, "print(x + 1)", 10)

    assert first.success and first.stdout == ""
    assert second.success and second.stdout == "42\n"


@pytest.mark.asyncio
async def test_two_kernels_do_not_share_variables(kernel):
    a, b = await kernel.start("a"), await kernel.start("b")

    await kernel.exec(a, "x = 1", 10)
    result = await kernel.exec(b, "print(x)", 10)

    assert "NameError" in result.error


@pytest.mark.asyncio
async def test_an_exception_is_returned_and_the_kernel_survives(kernel):
    handle = await kernel.start()
    await kernel.exec(handle, "x = 7", 10)

    failed = await kernel.exec(handle, "1 / 0", 10)
    after = await kernel.exec(handle, "print(x)", 10)

    assert "ZeroDivisionError" in failed.error and not failed.died
    assert after.stdout == "7\n"


@pytest.mark.asyncio
async def test_a_syntax_error_is_returned_not_raised(kernel):
    handle = await kernel.start()

    result = await kernel.exec(handle, "def f(:", 10)

    assert "SyntaxError" in result.error and not result.died


@pytest.mark.asyncio
async def test_sys_exit_ends_the_call_not_the_kernel(kernel):
    handle = await kernel.start()
    await kernel.exec(handle, "x = 1", 10)

    exited = await kernel.exec(handle, "import sys; sys.exit(3)", 10)
    after = await kernel.exec(handle, "print(x)", 10)

    assert "SystemExit" in exited.error and not exited.died
    assert after.stdout == "1\n"


@pytest.mark.asyncio
async def test_stdout_and_stderr_come_back_in_order(kernel):
    handle = await kernel.start()

    result = await kernel.exec(
        handle, "import sys\nprint('a')\nprint('b', file=sys.stderr)\nprint('c')", 10
    )

    assert result.stdout == "a\nb\nc\n"


@pytest.mark.asyncio
async def test_output_written_below_python_cannot_corrupt_the_reply(kernel):
    handle = await kernel.start()

    result = await kernel.exec(handle, "import os\nos.system('echo loud')\nprint('after')", 10)
    again = await kernel.exec(handle, "print('still fine')", 10)

    assert result.success and result.stdout == "after\n"
    assert again.stdout == "still fine\n"


@pytest.mark.asyncio
async def test_code_that_reads_stdin_gets_nothing_and_does_not_hang(kernel):
    handle = await kernel.start()

    result = await kernel.exec(handle, "input()", 10)

    assert "EOFError" in result.error and not result.died


@pytest.mark.asyncio
async def test_long_output_is_cut_and_says_so(kernel):
    handle = await kernel.start()

    result = await kernel.exec(handle, "print('a' * 300_000)", 10)

    assert len(result.stdout) < 210_000 and result.stdout.endswith("[output truncated]")


@pytest.mark.asyncio
async def test_a_timeout_stops_the_kernel_and_the_next_call_says_it_is_gone(kernel):
    handle = await kernel.start()
    await kernel.exec(handle, "x = 1", 10)

    slow = await kernel.exec(handle, "import time; time.sleep(30)", 1)
    after = await kernel.exec(handle, "print(x)", 10)

    assert slow.timed_out and slow.died
    assert after.died and "not running" in after.error


@pytest.mark.asyncio
async def test_a_kernel_that_exits_by_itself_is_reported_dead(kernel):
    handle = await kernel.start()

    result = await kernel.exec(handle, "import os; os._exit(5)", 10)

    assert result.died and "exit code 5" in result.error


@pytest.mark.asyncio
async def test_provider_keys_are_not_in_the_kernel_environment(kernel, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    monkeypatch.setenv("WEEBOT_TEST_SECRET_TOKEN", "hunter2")
    handle = await kernel.start()

    result = await kernel.exec(
        handle,
        "import os\n"
        "print(os.environ.get('OPENROUTER_API_KEY'), os.environ.get('WEEBOT_TEST_SECRET_TOKEN'))",
        10,
    )

    assert result.stdout == "None None\n"


@pytest.mark.asyncio
async def test_network_is_blockaded_by_proxy_variables_when_off(kernel):
    handle = await kernel.start()

    result = await kernel.exec(handle, "import os; print(os.environ.get('HTTP_PROXY'))", 10)

    assert result.stdout == "http://127.0.0.1:9\n"


@pytest.mark.asyncio
async def test_stopping_twice_is_harmless():
    backend = NativeKernel()
    handle = await backend.start("s")

    await backend.stop(handle)
    await backend.stop(handle)

    assert (await backend.exec(handle, "1", 5)).died
