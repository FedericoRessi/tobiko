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

from oslo_log import log

import tobiko
from tobiko import config
from tobiko.openstack import keystone
from tobiko.shell import ssh
from tobiko.shell import sh

CONF = config.CONF

LOG = log.getLogger(__name__)


def undercloud_ssh_client():
    host_config = undercloud_host_config()
    return ssh.ssh_client(host='undercloud-0', host_config=host_config)


def undercloud_host_config():
    return tobiko.setup_fixture(UndecloudHostConfig)


class InvalidRCFile(tobiko.TobikoException):
    message = "Invalid RC file: {rcfile}"


def fetch_os_env(rcfile, *rcfiles):
    rcfiles = (rcfile,) + rcfiles
    errors = []
    for rcfile in rcfiles:
        try:
            result = sh.execute(f". {rcfile}; env | grep '^OS_'",
                                ssh_client=undercloud_ssh_client())
        except sh.ShellCommandFailed as ex:
            LOG.debug(f"Unable to get overcloud RC file '{rcfile}' content "
                      f"({ex})")
            errors.append(tobiko.exc_info)
        else:
            env = {}
            for line in result.stdout.splitlines():
                name, value = line.split('=')
                env[name] = value
            if env:
                return env
    for error in errors:
        LOG.exception(f"Unable to get overcloud RC file '{rcfile}' "
                      "content", exc_info=error)
    raise InvalidRCFile(rcfile=", ".join(rcfiles))


def load_undercloud_rcfile():
    return fetch_os_env(*CONF.tobiko.tripleo.undercloud_rcfile)


class UndercloudKeystoneCredentialsFixture(
        keystone.EnvironKeystoneCredentialsFixture):
    def get_environ(self):
        return load_undercloud_rcfile()


class HasUndercloudFixture(tobiko.SharedFixture):

    has_undercloud = None

    def setup_fixture(self):
        ssh_client = undercloud_ssh_client()
        try:
            ssh_client.connect(retry_count=1,
                               connection_attempts=1,
                               timeout=15.)
        except Exception as ex:
            LOG.debug('Unable to connect to undercloud host: %s', ex,
                      exc_info=1)
            self.has_undercloud = False
        else:
            self.has_undercloud = True


def has_undercloud():
    return tobiko.setup_fixture(HasUndercloudFixture).has_undercloud


skip_if_missing_undercloud = tobiko.skip_unless(
    'TripleO undercloud hostname not configured', has_undercloud)


class UndecloudHostConfig(tobiko.SharedFixture):

    host = 'undercloud-0'
    hostname = None
    port = None
    username = None
    key_filename = None

    def __init__(self, **kwargs):
        super(UndecloudHostConfig, self).__init__()
        self._connect_parameters = ssh.gather_ssh_connect_parameters(**kwargs)

    def setup_fixture(self):
        self.hostname = CONF.tobiko.tripleo.undercloud_ssh_hostname
        self.port = CONF.tobiko.tripleo.undercloud_ssh_port
        self.username = CONF.tobiko.tripleo.undercloud_ssh_username
        self.key_filename = CONF.tobiko.tripleo.undercloud_ssh_key_filename

    @property
    def connect_parameters(self):
        parameters = ssh.gather_ssh_connect_parameters(self)
        parameters.update(self._connect_parameters)
        return parameters


def undercloud_keystone_client():
    session = undercloud_keystone_session()
    return keystone.get_keystone_client(session=session)


def undercloud_keystone_session():
    return keystone.get_keystone_session(
        credentials=UndercloudKeystoneCredentialsFixture)


def undercloud_keystone_credentials():
    return tobiko.setup_fixture(
        UndercloudKeystoneCredentialsFixture).credentials
