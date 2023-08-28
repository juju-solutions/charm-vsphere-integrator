import json
import os
import subprocess
from base64 import b64decode

import yaml

from charmhelpers.core import hookenv
from charmhelpers.core.unitdata import kv

from charms.layer import status


# When debugging hooks, for some reason HOME is set to /home/ubuntu, whereas
# during normal hook execution, it's /root. Set it here to be consistent.
os.environ["HOME"] = "/root"


def log(msg, *args):
    hookenv.log(msg.format(*args), hookenv.INFO)


def log_err(msg, *args):
    hookenv.log(msg.format(*args), hookenv.ERROR)


def save_credentials():
    """
    Save the credentials from either the config or the hook tool to the kv.

    Prefers the config so that it can be overridden.
    """
    config = hookenv.config()

    # try credentials config
    if config["credentials"]:
        try:
            creds_data = b64decode(config["credentials"]).decode("utf8")
            creds_data = json.loads(creds_data)
            log('Using "credentials" config values for credentials')
            _save_creds(creds_data)
            return True
        except Exception:
            status.blocked("invalid value for credentials config")
            return False
    no_creds_msg = "missing credentials; set credentials config"

    # try individual config
    # NB: if a user sets one of these, they better set 'em all!
    if all(
        [config["vsphere_ip"], config["user"], config["password"], config["datacenter"]]
    ):
        log("Using individual config values for credentials")
        _save_creds(config)
        return True

    # try to use Juju's trust feature
    try:
        result = subprocess.run(
            ["credential-get"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        creds_data = yaml.safe_load(result.stdout.decode("utf8"))
        log("Using credentials-get for credentials")
        _save_creds(creds_data)
        return True
    except FileNotFoundError:
        pass  # juju trust not available
    except subprocess.CalledProcessError as e:
        if "permission denied" not in e.stderr.decode("utf8"):
            raise
        no_creds_msg = "missing credentials access; grant with: juju trust"

    # no creds provided
    status.blocked(no_creds_msg)
    return False


def get_vsphere_credentials():
    return _load_creds()


def get_vsphere_config():
    config = hookenv.config()
    vsphere_config = {
        "datastore": config["datastore"],
        "folder": config["folder"],
        "respool_path": config["respool_path"],
    }
    # datastore and folder can't be emtpy
    if not vsphere_config["datastore"]:
        status.blocked("Missing required 'datastore' config")
        return False
    if not vsphere_config["folder"]:
        status.blocked("Missing required 'folder' config")
        return False
    return vsphere_config


def cleanup():
    pass


# Internal helpers


def _save_creds(creds_data):
    if "endpoint" in creds_data:
        # we're using 'juju trust'
        vsphere_ip = creds_data["endpoint"]
        datacenter = creds_data["region"]
        attrs = creds_data["credential"]["attributes"]
    else:
        # we're using charm config
        attrs = creds_data
        vsphere_ip = attrs["vsphere_ip"]
        datacenter = attrs["datacenter"]

    kv().set(
        "charm.vsphere.full-creds",
        dict(
            vsphere_ip=vsphere_ip,
            user=attrs["user"],
            password=attrs["password"],
            datacenter=datacenter,
        ),
    )


def _load_creds():
    return kv().get("charm.vsphere.full-creds")
