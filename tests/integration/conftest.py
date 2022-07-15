import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--series",
        type=str,
        default="focal",
        help="Set series for the machine units",
    )

    parser.addoption(
        "--datastore",
        type=str,
        default=None,
        help="vSphere datacenter name. In the vCenter control panel, this can be found"
        "at Inventory Lists > Resources > Datacenters.",
    )

    parser.addoption(
        "--folder",
        type=str,
        default=None,
        help="Virtual center VM folder path under the datacenter. Defaults to 'juju-kubernetes'."
        "This value must not be empty.",
    )


@pytest.fixture()
def series(request):
    return request.config.getoption("--series")


@pytest.fixture()
def datastore(request):
    return request.config.getoption("--datastore")


@pytest.fixture()
def folder(request):
    return request.config.getoption("--folder") or "juju-kubernetes"
