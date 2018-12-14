from charms.reactive import (
    hook,
    is_flag_set,
    when_all,
    when_any,
    when_not,
    toggle_flag,
    clear_flag,
)
from charms.reactive.relations import endpoint_from_name

from charms import layer


@when_any('config.changed.credentials',
          'config.changed.vsphere_ip',
          'config.changed.user',
          'config.changed.password',
          'config.changed.datacenter')
def update_creds():
    clear_flag('charm.vsphere.creds.set')


@when_any('config.changed.datastore',
          'config.changed.folder',
          'config.changed.respool_path')
def update_config():
    clear_flag('charm.vsphere.config.set')


@when_not('charm.vsphere.creds.set')
def manage_creds():
    toggle_flag('charm.vsphere.creds.set', layer.vsphere.save_credentials())


@when_not('charm.vsphere.config.set')
def manage_config():
    toggle_flag('charm.vsphere.config.set', layer.vsphere.get_vsphere_config())


@when_all('charm.vsphere.creds.set',
          'charm.vsphere.config.set')
@when_not('endpoint.clients.requests-pending')
def no_requests():
    layer.status.active('ready')


@when_all('charm.vsphere.creds.set',
          'charm.vsphere.config.set',
          'endpoint.clients.joined')
@when_any('config.changed',
          'endpoint.clients.requests-pending')
def handle_requests():
    clients = endpoint_from_name('clients')
    config_change = is_flag_set('config.changed')
    requests = clients.all_requests if config_change else clients.new_requests
    for request in requests:
        layer.status.maintenance(
            'granting request for {}'.format(request.unit_name))
        creds = layer.vsphere.get_vsphere_credentials()
        config = layer.vsphere.get_vsphere_config()

        request.set_credentials(**creds)
        request.set_config(**config)
        layer.vsphere.log('Finished request for {}', request.unit_name)
    clients.mark_completed()


@hook('stop')
def cleanup():
    layer.vsphere.cleanup()
