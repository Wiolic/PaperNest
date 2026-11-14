import json

from typer.testing import CliRunner

from papertrail import __version__
from papertrail.interfaces.cli.main import app

runner = CliRunner()


def test_version_json() -> None:
    result = runner.invoke(app, ["version", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"version": __version__}


def test_version_plain() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
