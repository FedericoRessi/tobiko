# Copyright 2018 Red Hat
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


class TobikoException(Exception):
    """Base Tobiko Exception.

    To use this class, inherit from it and define a 'message' property.
    """

    message = "An unknown exception occurred."

    def __init__(self, **properties):
        super(TobikoException, self).__init__()
        self._properties = properties
        message = self.message  # pylint: disable=exception-message-attribute
        if properties:
            message = message % properties
        self._message = message

    def __str__(self):
        return self._message

    def __getattr(self, name):
        try:
            return self._properties[name]
        except KeyError:
            pass
        msg = ("'{!r}' object has no attribute {!r}").format(self, name)
        raise AttributeError(msg)
