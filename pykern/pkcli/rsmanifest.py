# -*- coding: utf-8 -*-
u"""Create and read global and user manifests.

:copyright: Copyright (c) 2017 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function

# Appears in each directory
BASENAME = 'rsmanifest.json'

#POSIT: https://github.com/radiasoft/containers/blob/master/bin/build build_rsmanifest()
# Written once at build time
CONTAINER_FILE = '/' + BASENAME

# Read and written multiple times as the run user
USER_FILE = '~/' + BASENAME

# Identifies codes which are not installed in a virtualenv
_NO_VENV = ''


def add_code(name, version, uri, source_d, virtual_env=None):
    """Add a new code to ~?rsmanifest.json

    Args:
        name (str): name of the package
        version (str): commit or version
        uri (str): repo, source link
        source_d (str): directory containing
        virtual_env (str): name of the virtual_env to qualify
    """
    from pykern import pkcollections
    from pykern import pkio
    from pykern import pkjson
    import datetime
    import json

    fn = pkio.expand_user_path(USER_FILE)
    try:
        values = pkcollections.json_load_any(fn)
    except Exception as e:
        if not (pkio.exception_is_not_found(e) or isinstance(e, ValueError)):
            raise
        values = pkcollections.Dict(
            version='20170217.180000',
            codes=pkcollections.Dict({_NO_VENV: pkcollections.Dict()}),
        )
    if not virtual_env:
        virtual_env = _NO_VENV
    v = values.codes.get(virtual_env) or pkcollections.Dict()
    v[name.lower()] = pkcollections.Dict(
        installed=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        name=name,
        source_d=source_d,
        uri=uri,
        version=version,
    )
    values.codes[virtual_env] = v
    pkjson.dump_pretty(values, filename=fn)


def read_all(merge_file=None):
    """Merge all manifests

    Args:
        merge_file (str or py.path): where to write data (optional)
    Returns:
        dict: merged data
    """
    from pykern import pkio
    from pykern import pkjson

    fn = pkio.expand_user_path(USER_FILE)
    # Both must exist or error
    u = pkjson.load_any(fn)
    c = pkjson.load_any(CONTAINER_FILE)
    assert u.version == c.version, \
        '(user.version) {} != {} (container.version)'.format(u.version, c.version)
    # There are "guaranteed" to be no collisions, but if there are
    # we override user.
    c.update(u)
    if merge_file:
        pkjson.dump_pretty(c, filename=merge_file)
    return c
