"""`cli delete` does not claim a deletion it never made (F77).

It printed "Deleted project: <id>" and deleted nothing ("Implementation would
delete from database"). Like the other legacy project commands it now says it
is deprecated, and it exits non-zero so scripts do not take it as done.
"""

from __future__ import annotations

from click.testing import CliRunner

from cli.main import cli


def test_delete_says_it_did_nothing():
    result = CliRunner().invoke(cli, ["delete", "p1", "--yes"])
    assert "Deleted" not in result.output
    assert "deprecated" in result.output.lower()
    assert result.exit_code != 0
