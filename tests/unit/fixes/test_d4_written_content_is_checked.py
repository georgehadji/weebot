"""D4: the step audit checks that a written file still holds what the step wrote.

StepEvidenceAuditor only checked that written files exist. The uncalled
state_verifier compared content too; that one check moves here before the class
is deleted. Only a full-content write (create, write_large, write_file) is
compared, and only when no later partial edit in the step touched the same path.
"""

from weebot.application.services.step_evidence_auditor import StepEvidenceAuditor
from weebot.domain.models.audit import AuditVerdict
from weebot.domain.models.event import ToolEvent
from weebot.infrastructure.adapters.file_storage_adapter import LocalFileStorageAdapter


def _create(path, text):
    return ToolEvent(
        tool_name="file_editor",
        function_args={"command": "create", "path": path, "file_text": text},
        result="ok",
    )


async def test_a_file_that_no_longer_holds_what_was_written_is_flagged(tmp_path):
    (tmp_path / "a.txt").write_text("someone else's text", encoding="utf-8")
    auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))
    report = await auditor.audit_step(None, [_create("a.txt", "hello")])
    assert report.verdict != AuditVerdict.PASS
    assert any("content" in v.description for v in report.violations)


async def test_matching_content_passes_and_line_endings_do_not_count(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))
    report = await auditor.audit_step(None, [_create("a.txt", "one\ntwo\n")])
    assert report.verdict == AuditVerdict.PASS


async def test_a_later_partial_edit_is_not_a_mismatch(tmp_path):
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    edit = ToolEvent(
        tool_name="file_editor",
        function_args={"command": "str_replace", "path": "a.txt", "old_str": "x", "new_str": "y"},
        result="ok",
    )
    auditor = StepEvidenceAuditor(file_storage=LocalFileStorageAdapter(root_dir=tmp_path))
    report = await auditor.audit_step(None, [_create("a.txt", "hello"), edit])
    assert report.verdict == AuditVerdict.PASS
