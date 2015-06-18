# -*- coding: utf-8 -*-
u"""Wrapper for setuptools.setup to simplify creating of `setup.py` files.

Python `setup.py` files should be short for well-structured projects.
`b_setup.setup` assumes there are directories such as `tests`, `docs`,
`bin`, etc. PyKern Projects use `py.test` so the appropriate `PyTest`
class is provided by this module.

Example:

    A sample ``setup.py`` script::

        setup(
            name='pyexample',
            description='Some Example app',
            author='Example, Inc.',
            author_email='somebody@example.com',
            url='http://example.com',
        )

Assumptions:

    - the use of ``pytest`` for tests. GUI and console scripts are
      found automatically by special suffixes ``_gui.py`` and
      ``_console.py``. See ``setup`` documentation for an example.

    - Under git control. Even if you are building an app for the first
      time, you should create the repo first. Does not assume anything
      about the remote (i.e. need not be a GitHub repo).

:copyright: Copyright (c) 2015 Bivio Software, Inc.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
# DO NOT import __future__. setuptools breaks with unicode in PY2:
# http://bugs.python.org/setuptools/issue152
# Get errors about package_data not containing wildcards, name not found, etc.

import copy
import datetime
import glob
import inspect
import os
import os.path
import pkg_resources
import re
import setuptools
import setuptools.command.sdist
import setuptools.command.test
import subprocess
import sys

import pip.download
import pip.req

#: File computed globals are stored
STATE_FILE='pykern_setup.yml'


#: Created only during PyTest run
PYTEST_INI_FILE = 'pytest.ini'

#: Created only during Tox run
TOX_INI_FILE = 'tox.ini'


class PyTest(setuptools.command.test.test):
    """Proper initialization of `pytest` for ``python setup.py test``"""

    def initialize_options(self):
        """Run tests in ``--boxed`` mode (if available).

        Requires pytest plug ``xdist``.
        See https://bitbucket.org/pytest-dev/pytest-xdist#rst-header-boxed
        """
        # Not a new style class so super() doesn't work
        setuptools.command.test.test.initialize_options(self)
        self.pytest_args = self._boxed_if_os_supports()

    def finalize_options(self):
        """Initialize test_args and set test_suite to True"""
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        """Import `pytest` and calls `main`. Calls `sys.exit` with result"""
        import pytest
        try:
            self._pytest_ini()
            exit = pytest.main(self.pytest_args)
        finally:
            try:
                os.remove(PYTEST_INI_FILE)
            except OSError:
                pass
        sys.exit(exit)

    def _boxed_if_os_supports(self):
        """Test for existence of `os.fork`

        This should be a conditional test in xdist.

        Returns:
            list: will be ``[--boxed]]`` if can `fork`
        """
        if hasattr(os, 'fork'):
            return ['--boxed']
        return []

    def _pytest_ini(self):
        """Create pytest.ini

        If you specify norecursedirs, pytest assumes that you don't
        just want to find files in "tests". This means it recurses
        ".tox", for example.

        We have a default set of subdirectories (*_work and *_data)
        which may contain python modules so we need to list norecursedirs.

        To workaround the problem, we specify "tests" in addopts.
        """
        _write(PYTEST_INI_FILE, '''[pytest]
# OVERWRITTEN by pykern.pksetup every "python setup.py test" run
norecursedirs = *_data *_work
addopts = tests
''')


class SDist(setuptools.command.sdist.sdist):
    """Fix up a few things before running sdist"""

    def check_readme(self, *args, **kwargs):
        """Avoid README error message

        Currently only supports ``README.txt`` and ``README``,
        but we have ``README.md``
        """
        pass


class Tox(setuptools.Command):
    """Create tox.ini file"""

    description = 'create tox.ini and run tox'

    user_options = []

    def initialize_options(self, *args, **kwargs):
        pass

    def finalize_options(self, *args, **kwargs):
        pass

    def run(self, *args, **kwargs):
        _sphinx_apidoc(self._distribution_to_dict())
        try:
            _write(TOX_INI_FILE, '''[tox]
# OVERWRITTEN by pykern.pksetup every "python setup.py tox" run
[testenv:py27]
basepython = python2.7
[testenv]
deps=-rrequirements.txt
commands=python setup.py test
[testenv:docs]
basepython=python
changedir=docs
commands=sphinx-build -b html -d {envtmpdir}/doctrees . {envtmpdir}/html
''')
            subprocess.check_call(['tox'])
        finally:
            from pykern import pkio
            pkio.unchecked_remove(TOX_INI_FILE)

    def _distribution_to_dict(self):
        d = self.distribution.metadata
        res = {}
        for k in d._METHOD_BASENAMES:
            m = getattr(d, 'get_' + k)
            res[k] = m()
        return res


def setup(**kwargs):
    """Parses `README.md` and `requirements.txt`, sets some defaults, then
    calls `setuptools.setup`.

    Scripts are found by looking for files in the top level package directory
    which end with ``_console.py`` or ``_gui.py``. These files must have a
    function called ``main``.

    Example:
        The file ``pykern_console.py`` might contain::

            def main():
                print('hello world')

        This would create a program called command line program ``pykern`` which
        would call ``main()`` when invoked.

    Args:
        kwargs: see `setuptools.setup`
"""
    name = kwargs['name']
    assert type(name) == str, \
        'name must be a str; remove __future__ import unicode_literals in setup.py'
    long_description = _read('README.md')
    reqs = pip.req.parse_requirements(
        'requirements.txt', session=pip.download.PipSession())
    install_requires = [str(i.req) for i in reqs]
    # If the incoming is unicode, this works in Python3
    # https://bugs.python.org/issue13943
    del kwargs['name']
    base = {
        'classifiers': [],
        'cmdclass': {
            'test': PyTest,
            'sdist': SDist,
            'tox': Tox,
        },
        'test_suite': 'tests',
        'entry_points': _entry_points(name),
        'install_requires': install_requires,
        'long_description': long_description,
        'name': name,
        'packages': _packages(name),
        'tests_require': ['pytest'],
    }
    base = _state(base)
    base.update(kwargs)
    setuptools.setup(**base)


def _entry_points(pkg_name):
    """Find all *_{console,gui}.py files and define them

    Args:
        pkg_name (str): name of the package (directory)

    Returns:
        dict: Mapping of script names to module:methods
    """
    res = {}
    for s in ['console', 'gui']:
        tag = '_' + s
        for p in glob.glob(os.path.join(pkg_name, '*' + tag + '.py')):
            m = re.search(
                r'^([a-z]\w+)' + tag, os.path.basename(p), flags=re.IGNORECASE)
            if m:
                ep = res.setdefault(s + '_scripts', [])
                #TODO(robnagler): assert that 'def main()' exists in python module
                ep.append('{} = {}.{}:main'.format(m.group(1), pkg_name, m.group(0)))
    return res


def _git_ls_files(extra_args):
    """Find all the files under git control

    Will return nothing if package_data doesn't exist or no files in it.

    Args:
        extra_args (list): other args to append to command

    Returns:
        list: Files under git control.
    """
    cmd = ['git', 'ls-files']
    cmd.extend(extra_args)
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    return out.splitlines()


def _packages(name):
    """Find all packages by looking for ``__init__.py`` files.

    Mostly borrowed from https://bitbucket.org/django/django/src/tip/setup.py

    Args:
        name (str): name of the package (directory)

    Returns:
        list: packages names
    """
    def _fullsplit(path, result=None):
        """
        Split a pathname into components (the opposite of os.path.join) in a
        platform-neutral way.

        """
        if result is None:
            result = []
        head, tail = os.path.split(path)
        if head == '':
            return [tail] + result
        if head == path:
            return result
        return _fullsplit(head, [tail] + result)

    res = []
    for dirpath, _, filenames, in os.walk(name):
        if '__init__.py' in filenames:
            res.append(str('.'.join(_fullsplit(dirpath))))
    return res


def _package_data(name):
    """Find all package data checked in with git and otherwise.

    Asserts git is installed and git repo.

    Args:
        name (str): name of the package (directory)

    Returns:
        list: Files to include in package
    """
    d = _package_data_dir(name)
    res = _git_ls_files(['--others', '--exclude-standard', d])
    res.extend(_git_ls_files([d]))
    return sorted(res)


def _package_data_dir(name):
    """Name of package data dir

    Args:
        name (str): name of the package

    Returns:
        str: package data directory
    """
    from pykern import pkresource
    return os.path.join(name, pkresource.PACKAGE_DATA)


def _read(filename):
    """Read a file"""
    with open(filename, 'r') as f:
        return f.read()


def _sphinx_apidoc(base):
    """Call `sphinx-apidoc` with appropriately configured ``conf.py``.

    Args:
        base (dict): values to be passed to ``conf.py.in`` template
    """
    # Deferred import so initial setup.py works
    from pykern import pkjinja
    values = copy.deepcopy(base)
    values['year'] = datetime.datetime.now().year
    pkjinja.render_resource('docs-conf.py', base, output='docs/conf.py')
    subprocess.check_call([
        'sphinx-apidoc',
        '-f',
        '-o',
        'docs',
        base['name'],
    ])


def _state(base):
    """Gets global values (package_data, version, etc.) or computes them.

    If in a git repository, computes the globals first from the git repo values.

    Otherwise, reads pykern_setup.yml, which will be included in the ``MANIFEST.in``.

    Args:
        base (dict): incoming setup confi

    Returns:
        dict: new base state
    """
    import yaml
    if os.path.isdir('.git'):
        #develop sets the version, but not others
        #remove the pksetup_setup.yml?
        #do we really need to pull a new version, or parse the egg/git
        state = _state_compute(base)
    else:
        assert os.path.isfile(STATE_FILE), \
            '{}: not found, incorrectly built sdist or not git repo?'.format(STATE_FILE)
        state = yaml.load(_read(STATE_FILE))
    base.update(state)
    if os.getenv('READTHEDOCS'):
        _sphinx_apidoc(base)
    return base


def _state_compute(base):
    """Create :attr:`STATE_FILE` setting version, package_data, etc.
    """
    import yaml
    state = {
        'version': _version(),
    }
    include_pd = ''
    pd = _package_data(base['name'])
    if pd:
        state['package_data'] = {base['name']: pd}
        state['include_package_data'] = True
        include_pd = 'recursive-include {} *'.format(_package_data_dir(base['name']))
    # dump() does not work: "TypeError: must be unicode, not str"
    _write(STATE_FILE, yaml.dump(state, default_flow_style=False))
    s = '''include {}
include LICENSE
include requirements.txt
recursive-include docs *
recursive-include tests *
{}
'''.format(STATE_FILE, include_pd)
    _write('MANIFEST.in', s)
    return state


def _version():
    """Chronological version string for most recent commit or time of newer file.

    Finds the commit date of the most recent branch. Uses ``git
    ls-files`` to find files under git control which are modified or
    to be deleted, in which case we assume this is a developer, and we
    should just use the current time for the version. It will be newer
    than any committed version, which is all we care about for upgrades.

    Returns:
        str: Chronological version "yyyymmdd.hhmmss"

    """
    # Under development?
    if len(_git_ls_files(['--modified', '--deleted'])):
        vt = datetime.datetime.utcnow()
    else:
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD']).rstrip()
        vt = subprocess.check_output(
            ['git', 'log', '-1', '--format=%ct', branch]).rstrip()
        vt = datetime.datetime.fromtimestamp(float(vt))
    v = vt.strftime('%Y%m%d.%H%M%S')
    # Avoid 'UserWarning: Normalizing' by setuptools
    return str(pkg_resources.parse_version(v))

def _write(filename, content):
    """Writes a file"""
    with open(filename, 'w') as f:
        f.write(content)
