import os
from unittest import mock

import pytest

from pytorch_lightning.plugins.environments import LSFEnvironment


@mock.patch.dict(os.environ, {
    "LSB_HOSTS": "batch 10.10.10.0 10.10.10.1",
    "LSB_JOBID": "1234",
})
def test_missing_lsb_hosts():
    """ Test an error when the lsb hosts list cannot be found. """
    del os.environ["LSB_HOSTS"]
    with pytest.raises(ValueError, match="Could not find hosts in environment variable LSB_HOSTS"):
        LSFEnvironment()


@mock.patch.dict(os.environ, {
    "LSB_HOSTS": "batch 10.10.10.0 10.10.10.1",
    "LSB_JOBID": "1234",
})
def test_missing_lsb_job_id():
    """ Test an error when the job id cannot be found. """
    del os.environ["LSB_JOBID"]
    with pytest.raises(ValueError, match="Could not find job id in environment variable LSB_JOBID"):
        LSFEnvironment()


@mock.patch.dict(os.environ, {
    "MASTER_PORT": "4321",
    "LSB_JOBID": "1234",
    "LSB_HOSTS": "batch 10.10.10.0 10.10.10.1",
})
def test_manual_master_port_and_address():
    """ Test a user can set the port manually through the MASTER_PORT env variable. """
    env = LSFEnvironment()
    assert env.master_port() == 4321


@mock.patch.dict(os.environ, {
    "LSB_HOSTS": "batch 10.10.10.0 10.10.10.1 10.10.10.2 10.10.10.3",
    "LSB_JOBID": "1234",
    "JSM_NAMESPACE_SIZE": "4",
    "JSM_NAMESPACE_RANK": "3",
    "JSM_NAMESPACE_LOCAL_RANK": "1"
})
def test_attributes_from_environment_variables():
    """ Test that the LSF environment takes the attributes from the environment variables. """
    env = LSFEnvironment()
    assert env.creates_children()
    assert env.master_address() == "10.10.10.0"
    assert env.master_port() == 10234
    assert env.world_size() == 4
    assert env.global_rank() == 3
    assert env.local_rank() == 1
    env.set_global_rank(100)
    assert env.global_rank() == 3
    env.set_world_size(100)
    assert env.world_size() == 4
