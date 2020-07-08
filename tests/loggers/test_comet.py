from unittest.mock import patch

import pytest

from pytorch_lightning.loggers import CometLogger
from pytorch_lightning.utilities.exceptions import MisconfigurationException


def test_comet_logger_online():
    """Test comet online with mocks."""
    # Test api_key given
    with patch('pytorch_lightning.loggers.comet.CometExperiment') as comet:
        logger = CometLogger(api_key='key', workspace='dummy-test', project_name='general')

        _ = logger.experiment

        comet.assert_called_once_with(api_key='key', workspace='dummy-test', project_name='general')

    # Test both given
    with patch('pytorch_lightning.loggers.comet.CometExperiment') as comet:
        logger = CometLogger(save_dir='test', api_key='key', workspace='dummy-test', project_name='general')

        _ = logger.experiment

        comet.assert_called_once_with(api_key='key', workspace='dummy-test', project_name='general')

    # Test neither given
    with pytest.raises(MisconfigurationException):
        CometLogger(workspace='dummy-test', project_name='general')

    # Test already exists
    with patch('pytorch_lightning.loggers.comet.CometExistingExperiment') as comet_existing:
        logger = CometLogger(
            experiment_key='test',
            experiment_name='experiment',
            api_key='key',
            workspace='dummy-test',
            project_name='general',
        )

        _ = logger.experiment

        comet_existing.assert_called_once_with(
            api_key='key', workspace='dummy-test', project_name='general', previous_experiment='test'
        )

        comet_existing().set_name.assert_called_once_with('experiment')

    with patch('pytorch_lightning.loggers.comet.API') as api:
        CometLogger(api_key='key', workspace='dummy-test', project_name='general', rest_api_key='rest')

        api.assert_called_once_with('rest')


def test_comet_logget_experiment_name():
    """Test that Comet Logger experiment name works correctly."""

    api_key = "key"
    experiment_name = "My Name"

    # Test api_key given
    with patch('pytorch_lightning.loggers.comet.CometExperiment') as comet:
        logger = CometLogger(api_key=api_key, experiment_name=experiment_name,)

        # The experiment object should not exists
        assert logger._experiment is None

        _ = logger.experiment

        comet.assert_called_once_with(api_key=api_key, project_name=None, workspace=None)

        comet().set_name.assert_called_once_with(experiment_name)
