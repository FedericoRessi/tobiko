# Copyright 2019 Red Hat
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from __future__ import absolute_import

import functools
import io
import os
import typing

from oslo_log import log

import tobiko
from tobiko import config
from tobiko.openstack import keystone
from tobiko.openstack import ironic
from tobiko.openstack import metalsmith
from tobiko.openstack import topology
from tobiko.shell import sh
from tobiko.shell import ssh
from tobiko.tripleo import _undercloud


CONF = config.CONF
LOG = log.getLogger(__name__)


def load_overcloud_rcfile() -> typing.Dict[str, str]:
    conf = tobiko.tobiko_config().tripleo
    return _undercloud.fetch_os_env(*conf.overcloud_rcfile)


@functools.lru_cache()
def has_overcloud(min_version: str = None,
                  max_version: str = None) -> bool:
    try:
        check_overcloud(min_version=min_version,
                        max_version=max_version)
    except (OvercloudNotFound, OvercloudVersionMismatch) as ex:
        LOG.debug(f'Overcloud not found: {ex}')
        return False
    else:
        LOG.debug('Overcloud found')
        return True


skip_if_missing_overcloud = tobiko.skip_unless(
    'TripleO overcloud not configured', has_overcloud)


def skip_unless_has_overcloud(min_version: tobiko.VersionType = None,
                              max_version: tobiko.VersionType = None):
    return tobiko.skip_on_error(
        'TripleO overcloud not configured',
        check_overcloud,
        min_version=min_version,
        max_version=max_version,
        error_type=(OvercloudNotFound, OvercloudVersionMismatch))


class OvercloudKeystoneCredentialsFixtureBase(
        _undercloud.UndercloudKeystoneCredentialsFixtureBase):

    def _get_environ(self) -> typing.Dict[str, str]:
        return load_overcloud_rcfile()


class OvercloudKeystoneCredentialsFixture(
        OvercloudKeystoneCredentialsFixtureBase,
        keystone.DelegateKeystoneCredentialsFixture):

    @staticmethod
    def _get_delegates() -> typing.List[keystone.KeystoneCredentialsFixture]:
        return [
            tobiko.get_fixture(
                OvercloudCloudsFileKeystoneCredentialsFixture),
            tobiko.get_fixture(
                OvercloudEnvironKeystoneCredentialsFixture)]


def list_overcloud_nodes(**params):
    session = _undercloud.undercloud_keystone_session()
    client = metalsmith.get_metalsmith_client(session=session)
    return metalsmith.list_instances(client=client, **params)


def find_overcloud_node(**params):
    session = _undercloud.undercloud_keystone_session()
    client = metalsmith.get_metalsmith_client(session=session)
    return metalsmith.find_instance(client=client, **params)


def power_on_overcloud_node(instance: metalsmith.MetalsmithInstance,
                            timeout: tobiko.Seconds = 120.,
                            sleep_time: tobiko.Seconds = 5.):
    session = _undercloud.undercloud_keystone_session()
    client = ironic.get_ironic_client(session=session)
    ironic.power_on_node(client=client,
                         node=instance.uuid,
                         timeout=timeout,
                         sleep_time=sleep_time)


def power_off_overcloud_node(instance: metalsmith.MetalsmithInstance,
                             timeout: tobiko.Seconds = None,
                             sleep_time: tobiko.Seconds = None):
    session = _undercloud.undercloud_keystone_session()
    client = ironic.get_ironic_client(session=session)
    ironic.power_off_node(client=client,
                          node=instance.uuid,
                          timeout=timeout,
                          sleep_time=sleep_time)


def overcloud_ssh_client(ip_version: int = None,
                         network_name: str = None,
                         instance: metalsmith.MetalsmithInstance = None,
                         host_config=None):
    if host_config is None:
        host_config = overcloud_host_config(ip_version=ip_version,
                                            network_name=network_name,
                                            instance=instance)
    tobiko.check_valid_type(host_config.host, str)
    return ssh.ssh_client(host=host_config.host,
                          **host_config.connect_parameters)


def overcloud_host_config(ip_version: int = None,
                          network_name: str = None,
                          instance: metalsmith.MetalsmithInstance = None):
    host_config = OvercloudHostConfig(ip_version=ip_version,
                                      network_name=network_name,
                                      instance=instance)
    return tobiko.setup_fixture(host_config)


def overcloud_node_ip_address(ip_version: int = None,
                              network_name: str = None,
                              instance: metalsmith.MetalsmithInstance = None,
                              **params):
    if instance is None:
        instance = find_overcloud_node(**params)
    ip_version = ip_version or CONF.tobiko.tripleo.overcloud_ip_version
    network_name = network_name or CONF.tobiko.tripleo.overcloud_network_name
    address = metalsmith.find_instance_ip_address(instance=instance,
                                                  ip_version=ip_version,
                                                  network_name=network_name)
    LOG.debug(f"Got Overcloud node address '{address}' from Undercloud "
              f"(ip_version={ip_version}, network_name={network_name}, "
              f"instance={instance})")
    return address


class OvercloudSshKeyFileFixture(tobiko.SharedFixture):

    @property
    def key_filename(self):
        return tobiko.tobiko_config_path(
            CONF.tobiko.tripleo.overcloud_ssh_key_filename)

    def setup_fixture(self):
        self.setup_key_file()

    def setup_key_file(self):
        key_filename = self.key_filename
        key_dirname = os.path.dirname(key_filename)
        tobiko.makedirs(key_dirname, mode=0o700)

        ssh_client = _undercloud.undercloud_ssh_client()
        _get_undercloud_file(ssh_client=ssh_client,
                             source='~/.ssh/id_rsa',
                             destination=key_filename,
                             mode=0o600)
        _get_undercloud_file(ssh_client=ssh_client,
                             source='~/.ssh/id_rsa.pub',
                             destination=key_filename + '.pub',
                             mode=0o600)


def _get_undercloud_file(ssh_client, source, destination, mode):
    content = sh.execute(['cat', source],
                         ssh_client=ssh_client).stdout
    with io.open(destination, 'wb') as fd:
        fd.write(content.encode())
    os.chmod(destination, mode)


class OvercloudHostConfig(tobiko.SharedFixture):

    key_file = tobiko.required_fixture(OvercloudSshKeyFileFixture)

    def __init__(self,
                 host: str = None,
                 hostname: str = None,
                 ip_version: int = None,
                 instance: metalsmith.MetalsmithInstance = None,
                 key_filename: str = None,
                 network_name: str = None,
                 port: int = None,
                 username: str = None,
                 **kwargs):
        super(OvercloudHostConfig, self).__init__()
        self.host = host
        self.instance = instance
        self.ip_version = ip_version
        self.key_filename = key_filename
        self.host = host
        self.hostname = hostname
        self.network_name = network_name
        self.port = port
        self.username = username
        self._connect_parameters = ssh.gather_ssh_connect_parameters(**kwargs)

    def setup_fixture(self):
        if self.hostname is None:
            self.hostname = str(overcloud_node_ip_address(
                hostname=self.host,
                ip_version=self.ip_version,
                network_name=self.network_name,
                instance=self.instance))
        if self.host is None:
            self.host = self.hostname
        if self.port is None:
            self.port = CONF.tobiko.tripleo.overcloud_ssh_port
        if self.username is None:
            self.username = CONF.tobiko.tripleo.overcloud_ssh_username
        if self.key_filename is None:
            self.key_filename = self.key_file.key_filename

    @property
    def connect_parameters(self):
        parameters = ssh.ssh_host_config(
            host=str(self.hostname)).connect_parameters
        parameters.update(ssh.gather_ssh_connect_parameters(self))
        parameters.update(self._connect_parameters)
        return parameters


def get_overcloud_nodes_dataframe(
        oc_node_df_function: typing.Callable[[ssh.SSHClientType],
                                             typing.Any]):
    """
     :param oc_node_df_function : a function that queries a oc node
     using a cli command and returns a datraframe with an added
     hostname field.

     This function concats oc nodes dataframes into a unified overcloud
     dataframe, seperated by hostname field

    :return: dataframe of all overcloud nodes processes
    """
    import pandas
    oc_nodes_dfs = list()
    for instance in list_overcloud_nodes():
        ssh_client = overcloud_ssh_client(instance=instance)
        oc_nodes_dfs.append(oc_node_df_function(ssh_client))
    oc_procs_df = pandas.concat(oc_nodes_dfs, ignore_index=True)
    return oc_procs_df


def is_redis_expected():
    if topology.verify_osp_version('17.0', lower=True):
        return True
    services_requiring_redis = (
        'designate', 'octavia', 'ceilometer', 'gnocchi', 'panko')
    for service in services_requiring_redis:
        if keystone.has_service(name=service):
            return True
    return False


def overcloud_version() -> tobiko.Version:
    from tobiko.tripleo import _topology
    node = topology.find_openstack_node(group='overcloud')
    assert isinstance(node, _topology.TripleoTopologyNode)
    return node.rhosp_version


@functools.lru_cache()
def check_overcloud(min_version: str = None,
                    max_version: str = None):
    try:
        _undercloud.check_undercloud()
    except _undercloud.UndercloudNotFound as ex:
        raise OvercloudNotFound(cause=f'undercloud not found: {ex}') from ex

    if min_version or max_version:
        tobiko.check_version(overcloud_version(),
                             min_version=min_version,
                             max_version=max_version,
                             mismatch_error=OvercloudVersionMismatch)


class OvercloudNotFound(tobiko.ObjectNotFound):
    message = 'overcloud not found: {cause}'


class OvercloudVersionMismatch(tobiko.VersionMismatch):
    message = 'overcloud version mismatch: {version} {cause}'


class OvercloudCloudsFileKeystoneCredentialsFixture(
        OvercloudKeystoneCredentialsFixtureBase,
        keystone.CloudsFileKeystoneCredentialsFixture):

    @staticmethod
    def _get_default_cloud_name() -> typing.Optional[str]:
        return tobiko.tobiko_config().tripleo.overcloud_cloud_name


class OvercloudEnvironKeystoneCredentialsFixture(
        OvercloudKeystoneCredentialsFixtureBase,
        keystone.EnvironKeystoneCredentialsFixture):
    pass


def overcloud_keystone_session() -> keystone.KeystoneSession:
    credentials = overcloud_keystone_credentials()
    return keystone.get_keystone_session(credentials=credentials)


def overcloud_keystone_credentials() -> keystone.KeystoneCredentialsFixture:
    return tobiko.get_fixture(OvercloudKeystoneCredentialsFixture)


def overcloud_keystone_client() -> keystone.KeystoneClient:
    session = overcloud_keystone_session()
    return keystone.get_keystone_client(session=session)


def setup_overcloud_keystone_credentials():
    if has_overcloud():
        keystone.register_default_keystone_credentials(
            credentials=overcloud_keystone_credentials(),
            position=0)
