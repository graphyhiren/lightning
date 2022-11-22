import os

from click.testing import CliRunner
from tests_examples_app.public import _PATH_EXAMPLES

from lightning_app.cli.lightning_cli import run_app


def test_pickle_or_not_example():

    runner = CliRunner()
    result = runner.invoke(
        run_app,
        [
            os.path.join(_PATH_EXAMPLES, "app_pickle_or_not", "app.py"),
            "--blocking",
            "False",
            "--open-ui",
            "False",
        ],
        catch_exceptions=False,
    )
    assert "Pickle or Not End" in str(result.stdout_bytes)
    assert result.exit_code == 0
