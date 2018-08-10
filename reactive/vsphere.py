from charms.reactive import (
    hook,
    when_all,
    when_any,
    when_not,
    toggle_flag,
    clear_flag,
)
from charms.reactive.relations import endpoint_from_name

from charms import layer


@when_any('config.changed.credentials')
def update_creds():
    clear_flag('charm.vsphere.creds.set')


@when_not('charm.vsphere.creds.set')
def get_creds():
    toggle_flag('charm.vsphere.creds.set', layer.vsphere.get_credentials())


@when_all('charm.vsphere.creds.set')
@when_not('endpoint.clients.requests-pending')
def no_requests():
    layer.status.active('ready')


@when_all('charm.vsphere.creds.set',
          'endpoint.clients.requests-pending')
def handle_requests():
    clients = endpoint_from_name('clients')
    for request in clients.requests:
        layer.status.maintenance(
            'granting request for {}'.format(request.unit_name))
        if not request.has_credentials:
            creds = layer.vsphere.get_user_credentials()
            request.set_credentials(**creds)
        layer.vsphere.log('Finished request for {}', request.unit_name)
    clients.mark_completed()


@hook('stop')
def cleanup():
    layer.vsphere.cleanup()
