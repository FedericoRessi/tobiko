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

import netaddr
from neutronclient.v2_0 import client as neutronclient

import tobiko
from tobiko.openstack import _client
from tobiko.openstack import _find


class NeutronClientFixture(_client.OpenstackClientFixture):

    def init_client(self, session):
        return neutronclient.Client(session=session)


CLIENTS = _client.OpenstackClientManager(init_client=NeutronClientFixture)


def neutron_client(obj):
    if not obj:
        return get_neutron_client()

    if isinstance(obj, neutronclient.Client):
        return obj

    fixture = tobiko.setup_fixture(obj)
    if isinstance(fixture, NeutronClientFixture):
        return fixture.client

    message = "Object {!r} is not a NeutronClientFixture".format(obj)
    raise TypeError(message)


def get_neutron_client(session=None, shared=True, init_client=None,
                       manager=None):
    manager = manager or CLIENTS
    client = manager.get_client(session=session, shared=shared,
                                init_client=init_client)
    tobiko.setup_fixture(client)
    return client.client


def find_network(obj, properties=None, client=None, **params):
    """Look for the unique network matching some property values"""
    return _find.find_resource(
        obj=obj, resource_type='network', properties=properties,
        resources=list_networks(client=client, **params))


def find_subnet(obj, properties=None, client=None, **params):
    """Look for the unique subnet matching some property values"""
    return _find.find_resource(
        obj=obj, resource_type='subnet', properties=properties,
        resources=list_subnets(client=client, **params))


def list_networks(show=False, client=None, **params):
    networks = neutron_client(client).list_networks(**params)['networks']
    if show:
        networks = [show_network(n['id'], client=client) for n in networks]
    return networks


def list_subnets(show=False, client=None, **params):
    subnets = neutron_client(client).list_subnets(**params)['subnets']
    if show:
        subnets = [show_subnet(s['id'], client=client) for s in subnets]
    return subnets


def list_subnet_cidrs(client=None, **params):
    return [netaddr.IPNetwork(subnet['cidr'])
            for subnet in list_subnets(client=client, **params)]


def show_network(network, client=None, **params):
    return neutron_client(client).show_network(network, **params)['network']


def show_router(router, client=None, **params):
    return neutron_client(client).show_router(router, **params)['router']


def show_subnet(subnet, client=None, **params):
    return neutron_client(client).show_subnet(subnet, **params)['subnet']
