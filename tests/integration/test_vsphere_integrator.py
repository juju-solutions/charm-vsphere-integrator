import asyncio
import logging
import pytest
from pathlib import Path
from typing import List
from lightkube import AsyncClient
from lightkube.config.kubeconfig import KubeConfig
from lightkube.codecs import load_all_yaml
from lightkube.resources.core_v1 import Node
import shlex

log = logging.getLogger(__name__)

BASE_MODEL = "kubernetes-core"


@pytest.fixture(scope="module")
async def k8s_cp(ops_test):
    """Establish Charmed Kubernetes without the vsphere integrator."""
    required_charms = ("kubernetes-control-plane", "kubernetes-worker")
    required_apps = {
        charm: app_name
        for app_name, app in ops_test.model.applications.items()
        for charm in required_charms
        if charm in app.charm_url
    }
    if len(required_apps) != len(required_charms):
        log.info("Deploy Charmed Kubernetes")
        await ops_test.model.deploy(BASE_MODEL, channel="edge")
        k8s_cp = "kubernetes-control-plane"
    else:
        k8s_cp = required_apps["kubernetes-control-plane"]

    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)
    yield k8s_cp


@pytest.fixture(scope="module")
async def kubeconfig(ops_test, k8s_cp: str):
    kubeconfig_path = ops_test.tmp_path / "kubeconfig"
    retcode, stdout, stderr = await ops_test.juju(
        "scp",
        f"{k8s_cp}/leader:/home/ubuntu/config",
        kubeconfig_path,
    )
    if retcode != 0:
        log.error(f"retcode: {retcode}")
        log.error(f"stdout:\n{stdout.strip()}")
        log.error(f"stderr:\n{stderr.strip()}")
        pytest.fail("Failed to copy kubeconfig from kubernetes-control-plane")
    assert Path(kubeconfig_path).stat().st_size, "kubeconfig file is 0 bytes"
    yield kubeconfig_path


@pytest.fixture(scope="module")
async def lk_client(kubeconfig):
    yield AsyncClient(config=KubeConfig.from_file(kubeconfig))


@pytest.fixture()
async def bind_pvc(lk_client):
    objects = load_all_yaml(Path("tests/data/bind_pvc.yaml").read_text())
    for obj in objects:
        await lk_client.create(obj, obj.metadata.name, namespace=obj.metadata.namespace)

    yield objects[1]

    for obj in reversed(objects):
        await lk_client.delete(
            type(obj), obj.metadata.name, namespace=obj.metadata.namespace
        )


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures(
    "k8s_cp"
)  # deploy k8s-cp to completation before vsphere-integrator
async def test_build_and_deploy(ops_test, series: str, datastore: str, folder: str):
    log.info("Build Charm...")
    charm = await ops_test.build_charm(".")

    log.info("Build Overlay...")
    context = dict(charm=charm, series=series, datastore=datastore, folder=folder)
    (overlay,) = await ops_test.async_render_bundles(
        Path("tests/data/charm.yaml"), **context
    )

    log.info("Deploy Overlay...")
    cmd = f"deploy {BASE_MODEL} --channel=edge --overlay {overlay} --trust"
    rc, stdout, stderr = await ops_test.juju(*shlex.split(cmd))
    assert rc == 0, f"Bundle deploy failed: {(stderr or stdout).strip()}"

    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)


@pytest.mark.abort_on_fail
async def test_provider_ids(ops_test, k8s_cp: str, lk_client: AsyncClient):
    """Tests that every node has a provider id."""
    kubelet_apps = [k8s_cp, "kubernetes-worker"]
    unit_args = await get_kubelet_args(ops_test, kubelet_apps)
    log.info("provider-ids from kubelet are %s.", unit_args)

    has_provider_id = (all(args.get("--provider-id") for args in unit_args.values()),)
    if not has_provider_id:
        log.info("provider-ids not found without reconfiguring kubelets.")
        # reconfigure kubelets to ensure they have provider-id arg
        key = "kubelet-extra-args"
        await asyncio.gather(
            *(
                ops_test.model.applications[app].set_config({key: "v=1"})
                for app in kubelet_apps
            )
        )
        # Allow time for the cluster to apply the providerID
        await ops_test.model.wait_for_idle(wait_for_active=True, timeout=5 * 60)

        # Gather the provider-ids again
        unit_args = await get_kubelet_args(ops_test, kubelet_apps)
        log.info("now provider-ids from kubelet are %s.", unit_args)

        # Confirm each unit has a provider-id
        has_provider_id = (
            all(args.get("--provider-id") for args in unit_args.values()),
        )
    assert has_provider_id, "Every node should have a providerID, not empty"

    nodes = await get_node_provider_ids(lk_client)
    if not all(nodes.values()):
        log.info("providerIDs not found on node specs.")
        # Patch providerID on each node
        await patch_provider_id(ops_test, unit_args, lk_client)

        # Restart kube-controller-managers
        restart = ["systemctl", "restart", "snap.kube-controller-manager.daemon"]
        await ops_test.juju("run", "-a", k8s_cp, "--", *restart)

        nodes = await get_node_provider_ids(lk_client)

    assert all(nodes.values()), "All nodes should have a providerID"


async def test_pvc_creation(lk_client, bind_pvc):
    async def _wait_til_bound():
        unbound = True
        while unbound:
            obj = await lk_client.get(type(bind_pvc), bind_pvc.metadata.name)
            unbound = obj.status.phase != "Bound"

    await asyncio.wait_for(_wait_til_bound(), timeout=1 * 60)


async def get_kubelet_args(ops_test, kubelet_apps: List[str]):
    async def unit_kubelet_args(unit):
        cmd = f"run -u {unit.name} -- pgrep -la kubelet"
        rc, stdout, _ = await ops_test.juju(*shlex.split(cmd))
        if rc == 0:
            _, kubelet_cmd = stdout.split(" ", 1)
            _, *args = shlex.split(kubelet_cmd)
            return dict(arg.split("=", 1) for arg in args)
        return {}

    return {
        unit.name: await unit_kubelet_args(unit)
        for app in kubelet_apps
        for unit in ops_test.model.applications[app].units
    }


async def get_node_provider_ids(lk_client):
    lister = lk_client.list(Node)
    node_list = {}
    try:
        async for node in lister:
            node_list[node.metadata.name] = getattr(node.spec, "providerID", None)
    finally:
        await lister.aclose()
    return node_list


async def patch_provider_id(ops_test, unit_args, lk_client):
    for unit, args in unit_args.items():
        spec = dict(spec=dict(providerID=args["--provider-id"]))
        rc, hostname, stderr = await ops_test.juju("run", "-u", unit, "hostname")
        assert rc == 0, f"Failed to get hostname {unit}: {hostname or stderr}"
        await lk_client.patch(Node, hostname.strip(), spec)
