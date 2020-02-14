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

import socket

import netaddr

import tobiko
from tobiko import config
from tobiko.openstack import keystone
from tobiko.shell import ssh
from tobiko.shell import sh

CONF = config.CONF


def undercloud_ssh_client():
    host_config = undercloud_host_config()
    return ssh.ssh_client(host='undercloud-0', host_config=host_config)


def undercloud_host_config():
    tripleo_config = tobiko.tobiko_config().tripleo
    return ssh.ssh_host_config(
        host=tripleo_config.undercloud_ssh_hostname,
        username=tripleo_config.undercloud_ssh_username,
        port=tripleo_config.undercloud_ssh_port,
        key_file=tripleo_config.undercloud_ssh_key_filename)


def fetch_os_env(rcfile):
    command = ". {rcfile}; env | grep '^OS_'".format(rcfile=rcfile)
    result = sh.execute(command, ssh_client=undercloud_ssh_client())
    env = {}
    for line in result.stdout.splitlines():
        name, value = line.split('=')
        env[name] = value
    return env


def load_undercloud_rcfile():
    return fetch_os_env(rcfile=CONF.tobiko.tripleo.undercloud_rcfile)


class UndercloudKeystoneCredentialsFixture(
        keystone.EnvironKeystoneCredentialsFixture):
    def get_environ(self):
        return load_undercloud_rcfile()


def gethost_by_name(hostname):
    try:
        return netaddr.IPAddress(hostname)
    except Exception:
        ip_address = socket.gethostbyname(hostname)
        return netaddr.IPAddress(ip_address)


def has_undercloud():
    host_config = undercloud_host_config()
    try:
        gethost_by_name(host_config.hostname)
    except Exception:
        return False
    else:
        return True


skip_if_missing_undercloud = tobiko.skip_unless(
    'TripleO undercloud hostname not configured', has_undercloud)


def undercloud_keystone_client():
    session = undercloud_keystone_session()
    return keystone.get_keystone_client(session=session)


def undercloud_keystone_session():
    return keystone.get_keystone_session(
        credentials=UndercloudKeystoneCredentialsFixture)


def undercloud_keystone_credentials():
    return tobiko.setup_fixture(
        UndercloudKeystoneCredentialsFixture).credentials
