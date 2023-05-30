'''
Python packaging operations, including PEP-517 support, for use by a `setup.py`
script.

Run doctests with: `python -m doctest pipcl.py`
'''

import base64
import glob
import hashlib
import inspect
import io
import os
import platform
import re
import shutil
import site
import setuptools
import subprocess
import sys
import sysconfig
import tarfile
import textwrap
import time
import zipfile

import wdev


class Package:
    '''
    Our constructor takes a definition of a Python package similar to that
    passed to `distutils.core.setup()` or `setuptools.setup()` - name,
    version, summary etc, plus callbacks for building, getting a list of sdist
    filenames, and cleaning.

    We provide methods that can be used to implement a Python package's
    `setup.py` supporting PEP-517.

    We also support basic command line handling for use
    with a legacy (pre-PEP-517) pip, implemented by
    legacy distutils/setuptools, and also described in:
    https://pip.pypa.io/en/stable/reference/build-system/setup-py/

    Here is a `doctest` example of using pipcl to create a SWIG extension
    module. Requires `swig`.

    Create an empty test directory:

        >>> import os
        >>> import shutil
        >>> shutil.rmtree('pipcl_test', ignore_errors=1)
        >>> os.mkdir('pipcl_test')

    Create a `setup.py` which uses `pipcl` to define an extension module.

        >>> import textwrap
        >>> with open('pipcl_test/setup.py', 'w') as f:
        ...     _ = f.write(textwrap.dedent("""
        ...             import sys
        ...             import pipcl
        ...
        ...             def build():
        ...                 so_leaf = pipcl.build_extension(
        ...                         name = 'foo',
        ...                         path_i = 'foo.i',
        ...                         outdir = 'build',
        ...                         )
        ...                 return [
        ...                         ('build/foo.py', 'foo/__init__.py'),
        ...                         (f'build/{so_leaf}', f'foo/{so_leaf}'),
        ...                         ('README', '$dist-info/README'),
        ...                         ]
        ...
        ...             def sdist():
        ...                 return [
        ...                         'foo.i',
        ...                         'setup.py',
        ...                         'pipcl.py',
        ...                         'wdev.py',
        ...                         'README',
        ...                         ]
        ...
        ...             p = pipcl.Package(
        ...                     name = 'foo',
        ...                     version = '1.2.3',
        ...                     fn_build = build,
        ...                     fn_sdist = sdist,
        ...                     )
        ...
        ...             build_wheel = p.build_wheel
        ...             build_sdist = p.build_sdist
        ... 
        ...             # Handle old-style setup.py command-line usage:
        ...             if __name__ == '__main__':
        ...                 p.handle_argv(sys.argv)
        ...             """))

    Create the files required by the above `setup.py` - the SWIG `.i` input
    file, the README file, and copies of `pipcl.py` and `wdev.py`.

        >>> with open('pipcl_test/foo.i', 'w') as f:
        ...     _ = f.write(textwrap.dedent("""
        ...             %{
        ...             #include <stdio.h>
        ...             #include <string.h>
        ...             int bar(const char* text)
        ...             {
        ...                 printf("bar(): text: %s\\\\n", text);
        ...                 int len = (int) strlen(text);
        ...                 printf("bar(): len=%i\\\\n", len);
        ...                 fflush(stdout);
        ...                 return len;
        ...             }
        ...             %}
        ...             int bar(const char* text);
        ...             """))

        >>> with open('pipcl_test/README', 'w') as f:
        ...     _ = f.write(textwrap.dedent("""
        ...             This is Foo.
        ...             """))

        >>> _ = shutil.copy2('pipcl.py', 'pipcl_test/pipcl.py')
        >>> _ = shutil.copy2('wdev.py', 'pipcl_test/wdev.py')

    Use `setup.py`'s command-line interface to build and install the extension
    module into `pipcl_test/install/`.

        >>> _ = subprocess.run(
        ...         f'cd pipcl_test && {sys.executable} setup.py --verbose --root install install',
        ...         shell=1, check=1)

    Create a test script which asserts that Python function call `foo.bar(s)`
    returns the length of `s`.

        >>> with open('pipcl_test/test.py', 'w') as f:
        ...     _ = f.write(textwrap.dedent("""
        ...             import sys
        ...             import foo
        ...             text = 'hello'
        ...             print(f'test.py: calling foo.bar() with text={text!r}')
        ...             sys.stdout.flush()
        ...             l = foo.bar(text)
        ...             print(f'test.py: foo.bar() returned: {l}')
        ...             assert l == len(text)
        ...             """))

    Run the test script, setting `PYTHONPATH` so that `import foo` works.

        >>> r = subprocess.run(
        ...         f'cd pipcl_test && {sys.executable} test.py',
        ...         shell=1, check=1, text=1,
        ...         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        ...         env=os.environ | dict(PYTHONPATH='install'),
        ...         )
        >>> print(r.stdout)
        test.py: calling foo.bar() with text='hello'
        bar(): text: hello
        bar(): len=5
        test.py: foo.bar() returned: 5
        <BLANKLINE>

    Check that building sdist and wheel succeeds. For now we don't attempt to
    check that the sdist and wheel actually work.

        >>> _ = subprocess.run(
        ...         f'cd pipcl_test && {sys.executable} setup.py --verbose sdist',
        ...         shell=1, check=1)

        >>> _ = subprocess.run(
        ...         f'cd pipcl_test && {sys.executable} setup.py --verbose bdist_wheel',
        ...         shell=1, check=1)
    
    
    Wheels and sdists
    
        Wheels:
            We generate wheels according to:
            https://packaging.python.org/specifications/binary-distribution-format/
            
            * `{name}-{version}.dist-info/RECORD` uses sha256 hashes.
            * We do not generate other `RECORD*` files such as
              `RECORD.jws` or `RECORD.p7s`.
            * `{name}-{version}.dist-info/WHEEL` has:
            
              * `Wheel-Version: 1.0`
              * `Root-Is-Purelib: false`
            * No support for signed wheels.
            * See documentation for `fn_build()` for more information about
              generated wheels.

        Sdists:
            We generate sdist's according to:
            https://packaging.python.org/specifications/source-distribution-format/
    '''
    def __init__(self,
            name,
            version,
            platform = None,
            supported_platform = None,
            summary = None,
            description = None,
            description_content_type = None,
            keywords = None,
            home_page = None,
            download_url = None,
            author = None,
            author_email = None,
            maintainer = None,
            maintainer_email = None,
            license = None,
            classifier = None,
            requires_dist = None,
            requires_python = None,
            requires_external = None,
            project_url = None,
            provides_extra = None,
            
            root = None,
            fn_build = None,
            fn_clean = None,
            fn_sdist = None,
            tag_python = None,
            tag_abi = None,
            tag_platform = None,
            
            wheel_compression = zipfile.ZIP_DEFLATED,
            wheel_compresslevel = None,
            ):
        '''
        The initial args before `root` define the package
        metadata and closely follow the definitions in:
        https://packaging.python.org/specifications/core-metadata/
        
        Args:
        
            name:
                A string, the name of the Python package.
            version:
                A string, the version of the Python package. Also see PEP-440
                `Version Identification and Dependency Specification`.
            platform:
                A string or list of strings.
            supported_platform:
                A string or list of strings.
            summary:
                A string, short description of the package.
            description:
                A string, a detailed description of the package.
            description_content_type:
                A string describing markup of `description` arg. For example
                `text/markdown; variant=GFM`.
            keywords:
                A string containing comma-separated keywords.
            home_page:
                URL of home page.
            download_url:
                Where this version can be downloaded from.
            author:
                Author.
            author_email:
                Author email.
            maintainer:
                Maintainer.
            maintainer_email:
                Maintainer email.
            license:
                A string containing the license text.
            classifier:
                A string or list of strings. Also see:

                * https://pypi.org/pypi?%3Aaction=list_classifiers
                * https://pypi.org/classifiers/

            requires_dist:
                A string or list of strings. Also see PEP-508.
            requires_python:
                A string or list of strings.
            requires_external:
                A string or list of strings.
            project_url:
                A string or list of strings, each of the form: `{name}, {url}`.
            provides_extra:
                A string or list of strings.

            root:
                Root of package, defaults to current directory.
            
            fn_build:
                A function taking no args that builds the package.

                Should return a list of items; each item should be a tuple of
                two strings `(from_, to_)`, or a single string `path` which is
                treated as the tuple `(path, path)`.

                `from_` should be the path to a file; if a relative path it is
                assumed to be relative to `root`. `to_` identifies what the
                file should be called within a wheel or when installing.

                Initial `$dist-info/` in `_to` is replaced by
                `{name}-{version}.dist-info/`; this is useful for license files
                etc.

                Initial `$data/` in `_to` is replaced by
                `{name}-{version}.data/`. We do not enforce particular
                subdirectories, instead it is up to `fn_build()` to use
                specific subdirectories such as `purelib`, `headers`,
                `scripts`, `data` etc.

                If we are building a wheel (e.g. `bdist_wheel` in the
                argv passed to `self.handle_argv()` or PEP-517 pip calls
                `self.build_wheel()`), we copy file `from_` to `to_` inside the
                wheel archive.

                If we are installing (e.g. `install` command in
                the argv passed to `self.handle_argv()`), then
                we copy `from_` to `{sitepackages}/{to_}`, where
                `sitepackages` is the installation directory, the
                default being `sysconfig.get_path('platlib')` e.g.
                `myvenv/lib/python3.9/site-packages/`.
            
            fn_clean:
                A function taking a single arg `all_` that cleans generated
                files. `all_` is true iff `--all` is in argv.

                For safety and convenience, can also returns a list of
                files/directory paths to be deleted. Relative paths are
                interpreted as relative to `root` and other paths are asserted
                to be within `root`.
            
            fn_sdist:
                A function taking no args that returns a list of paths, e.g.
                using `pipcl.git_items()`, for files that should be copied
                into the sdist. Relative paths are interpreted as relative to
                `root`. It is an error if a path does not exist or is not a
                file. The list must contain `pyproject.toml`.
            
            tag_python:
                First element of wheel tag defined in PEP-425. If None we use
                `cp{version}`.
            tag_abi:
                Second element of wheel tag defined in PEP-425. If None we use
                `none`.
            tag_platform:
                Third element of wheel tag defined in PEP-425. Default is
                derived from `setuptools.distutils.util.get_platform()` (was
                `distutils.util.get_platform()` as specified in the PEP), e.g.
                `openbsd_7_0_amd64`.

                For pure python packages use: `tag_platform=any`
            
            wheel_compression:
                zipfile compression to use for wheels.
            wheel_compresslevel:
                zipfile compression level for wheels.
            
        '''        
        assert name
        assert version
        
        def assert_str( v):
            if v is not None:
                assert isinstance( v, str), f'Not a string: {v!r}'
        def assert_str_or_multi( v):
            if v is not None:
                assert isinstance( v, (str, tuple, list)), f'Not a string, tuple or set: {v!r}'
        
        assert_str( name)
        assert_str( version)
        assert_str_or_multi( platform)
        assert_str_or_multi( supported_platform)
        assert_str( summary)
        assert_str( description)
        assert_str( description_content_type)
        assert_str( keywords)
        assert_str( home_page)
        assert_str( download_url)
        assert_str( author)
        assert_str( author_email)
        assert_str( maintainer)
        assert_str( maintainer_email)
        assert_str( license)
        assert_str_or_multi( classifier)
        assert_str_or_multi( requires_dist)
        assert_str( requires_python)
        assert_str_or_multi( requires_external)
        assert_str_or_multi( project_url)
        assert_str_or_multi( provides_extra)
        
        # https://packaging.python.org/en/latest/specifications/core-metadata/.
        assert re.match('([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$', name, re.IGNORECASE)
        
        # PEP-440.
        assert re.match(r'^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?$', version)
        
        # https://packaging.python.org/en/latest/specifications/binary-distribution-format/
        if tag_python:
            assert '-' not in tag_python
        if tag_abi:
            assert '-' not in tag_abi
        if tag_platform:
            assert '-' not in tag_platform
        
        self.name = name
        self.version = version
        self.platform = platform
        self.supported_platform = supported_platform
        self.summary = summary
        self.description = description
        self.description_content_type = description_content_type
        self.keywords = keywords
        self.home_page = home_page
        self.download_url = download_url
        self.author = author
        self.author_email  = author_email
        self.maintainer = maintainer
        self.maintainer_email = maintainer_email
        self.license = license
        self.classifier = classifier
        self.requires_dist = requires_dist
        self.requires_python = requires_python
        self.requires_external = requires_external
        self.project_url = project_url
        self.provides_extra = provides_extra
        
        self.root = os.path.abspath(root if root else os.getcwd())
        self.fn_build = fn_build
        self.fn_clean = fn_clean
        self.fn_sdist = fn_sdist
        self.tag_python = tag_python
        self.tag_abi = tag_abi
        self.tag_platform = tag_platform
        
        self.wheel_compression = wheel_compression
        self.wheel_compresslevel = wheel_compresslevel


    def build_wheel(self,
            wheel_directory,
            config_settings=None,
            metadata_directory=None,
            verbose=False,
            ):
        '''
        A PEP-517 `build_wheel()` function, with extra optional `verbose` arg.

        Also called by `handle_argv()` to handle the `bdist_wheel` command.

        Returns leafname of generated wheel within `wheel_directory`.
        '''
        _log(f'wheel_directory={wheel_directory}'
                f' config_settings={config_settings}'
                f' metadata_directory={metadata_directory}'
                )
        _log('os.environ is:')
        for n in sorted( os.environ.keys()):
            v = os.environ[ n]
            _log( f'    {n}: {v!r}')

        # Get two-digit python version, e.g. 'cp3.8' for python-3.8.6.
        #
        if self.tag_python:
            tag_python = self.tag_python
        else:
            tag_python = 'cp' + ''.join(platform.python_version().split('.')[:2])

        # ABI tag.
        if self.tag_abi:
            tag_abi = self.tag_abi
        else:
            tag_abi = 'none'
        
        # Find platform tag used in wheel filename, as described in
        # PEP-425. E.g. 'openbsd_6_8_amd64', 'win_amd64' or 'win32'.
        #
        if self.tag_platform:
            tag_platform = self.tag_platform
        else:
            tag_platform = setuptools.distutils.util.get_platform().replace('-', '_').replace('.', '_')

        # Final tag is, for example, 'cp39-none-win32', 'cp39-none-win_amd64'
        # or 'cp38-none-openbsd_6_8_amd64'.
        #
        tag = f'{tag_python}-{tag_abi}-{tag_platform}'

        path = f'{wheel_directory}/{self.name}-{self.version}-{tag}.whl'

        # Do a build and get list of files to copy into the wheel.
        #
        items = []
        if self.fn_build:
            _log(f'calling self.fn_build={self.fn_build}')
            items = self.fn_build()

        _log(f'Creating wheel: {path}')
        os.makedirs(wheel_directory, exist_ok=True)
        record = _Record()
        with zipfile.ZipFile(path, 'w', self.wheel_compression, self.wheel_compresslevel) as z:

            def add_file(from_, to_):
                z.write(from_, to_)
                record.add_file(from_, to_, verbose=verbose)

            def add_str(content, to_):
                z.writestr(to_, content)
                record.add_content(content, to_, verbose=verbose)

            dist_info_dir = self._dist_info_dir()
            
            # Add the files returned by fn_build().
            #
            for item in items:
                (from_abs, from_rel), (to_abs, to_rel) = self._fromto(item)
                add_file(from_abs, to_rel)

            # Add <name>-<version>.dist-info/WHEEL.
            #
            add_str(
                    f'Wheel-Version: 1.0\n'
                    f'Generator: pipcl\n'
                    f'Root-Is-Purelib: false\n'
                    f'Tag: {tag}\n'
                    ,
                    f'{dist_info_dir}/WHEEL',
                    )
            # Add <name>-<version>.dist-info/METADATA.
            #
            add_str(self._metainfo(), f'{dist_info_dir}/METADATA')
            
            # Add <name>-<version>.dist-info/COPYING.
            if self.license:
                add_str(self.license, f'{dist_info_dir}/COPYING')
            
            # Update <name>-<version>.dist-info/RECORD. This must be last.
            #
            z.writestr(f'{dist_info_dir}/RECORD', record.get())

        _log( f'Have created wheel: {path}')
        return os.path.basename(path)


    def build_sdist(self,
            sdist_directory,
            formats,
            config_settings=None,
            verbose=False,
            ):
        '''
        A PEP-517 `build_sdist()` function, with extra optional `verbose` arg.

        Also called by `handle_argv()` to handle the `sdist` command.

        Returns leafname of generated archive within `sdist_directory`.
        '''
        if verbose:
            _log( f'formats={formats}')
        if formats and formats != 'gztar':
            raise Exception( f'Unsupported: formats={formats}')
        paths = []
        if self.fn_sdist:
            paths = self.fn_sdist()

        manifest = []
        
        def add_content(tar, name, contents):
            '''
            Adds item called `name` to `tarfile.TarInfo` `tar`, containing
            `contents`. If contents is a string, it is encoded using utf8.
            '''
            if verbose:
                _log( f'Adding: {name}')
            if isinstance(contents, str):
                contents = contents.encode('utf8')
            ti = tarfile.TarInfo(name)
            ti.size = len(contents)
            ti.mtime = time.time()
            tar.addfile(ti, io.BytesIO(contents))
        
        def add_file(tar, path_abs, name):
            if verbose:
                _log( f'Adding file: {os.path.relpath(path_abs)} => {name}')
            tar.add( path_abs, name, recursive=False)

        os.makedirs(sdist_directory, exist_ok=True)
        tarpath = f'{sdist_directory}/{self.name}-{self.version}.tar.gz'
        if verbose:
            _log(f'Creating sdist: {tarpath}')
        with tarfile.open(tarpath, 'w:gz') as tar:
            found_pyproject_toml = False
            for path in paths:
                path_abs, path_rel = self._path_relative_to_root( path)
                if path_abs.startswith(f'{os.path.abspath(sdist_directory)}/'):
                    # Source files should not be inside <sdist_directory>.
                    assert 0, f'Path is inside sdist_directory={sdist_directory}: {path_abs!r}'
                if not os.path.exists(path_abs):
                    assert 0, f'Path does not exist: {path_abs!r}'
                if not os.path.isfile(path_abs):
                    assert 0, f'Path is not a file: {path_abs!r}'
                if path_rel == 'pyproject.toml':
                    found_pyproject_toml = True
                add_file( tar, path_abs, f'{self.name}-{self.version}/{path_rel}')
                manifest.append(path_rel)
            if not found_pyproject_toml:
                _log(f'Warning: no pyproject.toml specified.')
            # Always add a PKG-INFO file.
            add_content(tar, f'{self.name}-{self.version}/PKG-INFO', self._metainfo())

            if self.license:
                add(tar, f'{self.name}-{self.version}/COPYING', self.license)
            
        _log( f'Have created sdist: {tarpath}')
        return os.path.basename(tarpath)


    def _argv_clean(self, all_):
        '''
        Called by `handle_argv()`.
        '''
        if not self.fn_clean:
            return
        paths = self.fn_clean(all_)
        if paths:
            if isinstance(paths, str):
                paths = paths,
            for path in paths:
                if not os.path.isabs(path):
                    path = ps.path.join(self.root, path)
                path = os.path.abspath(path)
                assert path.startswith(self.root+os.sep), \
                        f'path={path!r} does not start with root={self.root+os.sep!r}'
                _log(f'Removing: {path}')
                shutil.rmtree(path, ignore_errors=True)


    def _argv_install(self, record_path, root, verbose=False):
        '''
        Called by `handle_argv()` to handle `install` command..
        '''
        if verbose:
            _log( f'{record_path=} {root=}')
        
        # Do a build and get list of files to install.
        #
        items = []
        if self.fn_build:
            items = self.fn_build()

        if root is None:
            root = sysconfig.get_path('platlib')
            if verbose:
                _log( f'Using sysconfig.get_path("platlib")={root!r}.')
            # todo: for pure-python we should use sysconfig.get_path('purelib') ?
        
        _log( f'Installing into {root=}')
        dist_info_dir = self._dist_info_dir()
        
        if not record_path:
            record_path = f'{root}/{dist_info_dir}/RECORD'
        record = _Record()
        
        def add_file(from_abs, from_rel, to_abs, to_rel):
            if verbose:
                _log(f'Copying from {from_rel} to {to_abs}')
            os.makedirs( os.path.dirname( to_abs), exist_ok=True)
            shutil.copy2( from_abs, to_abs)
            record.add_file(from_rel, to_rel)

        def add_str(content, to_abs, to_rel):
            if verbose:
                _log( f'Writing to: {to_abs}')
            with open( to_abs, 'w') as f:
                f.write( content)
            record.add_content(content, to_rel)
        
        for item in items:
            (from_abs, from_rel), (to_abs, to_rel) = self._fromto(item)
            to_abs2 = f'{root}/{to_rel}'
            add_file( from_abs, from_rel, to_abs2, to_rel)
        
        add_str( self._metainfo(), f'{root}/{dist_info_dir}/METADATA', f'{dist_info_dir}/METADATA')

        if verbose:
            _log( f'Writing to: {record_path}')
        with open(record_path, 'w') as f:
            f.write(record.get())

        if verbose:
            _log(f'Finished.')


    def _argv_dist_info(self, root):
        '''
        Called by `handle_argv()`. There doesn't seem to be any documentation
        for `setup.py dist_info`, but it appears to be like `egg_info` except
        it writes to a slightly different directory.
        '''
        if root is None:
            root = f'{self.name}-{self.version}.dist-info'
        self._write_info(f'{root}/METADATA')
        if self.license:
            with open( f'{root}/COPYING', 'w') as f:
                f.write( self.license)


    def _argv_egg_info(self, egg_base):
        '''
        Called by `handle_argv()`.
        '''
        if egg_base is None:
            egg_base = '.'
        self._write_info(f'{egg_base}/.egg-info')


    def _write_info(self, dirpath=None):
        '''
        Writes egg/dist info to files in directory `dirpath` or `self.root` if
        `None`.
        '''
        if dirpath is None:
            dirpath = self.root
        _log(f'Creating files in directory {dirpath}')
        os.makedirs(dirpath, exist_ok=True)
        with open(os.path.join(dirpath, 'PKG-INFO'), 'w') as f:
            f.write(self._metainfo())

        # These don't seem to be required?
        #
        #with open(os.path.join(dirpath, 'SOURCES.txt', 'w') as f:
        #    pass
        #with open(os.path.join(dirpath, 'dependency_links.txt', 'w') as f:
        #    pass
        #with open(os.path.join(dirpath, 'top_level.txt', 'w') as f:
        #    f.write(f'{self.name}\n')
        #with open(os.path.join(dirpath, 'METADATA', 'w') as f:
        #    f.write(self._metainfo())


    def handle_argv(self, argv):
        '''
        Attempt to handles old-style (pre PEP-517) command line passed by
        old releases of pip to a `setup.py` script, and manual running of
        `setup.py`.

        This is partial support at best.
        '''
        #_log(f'argv: {argv}')

        class ArgsRaise:
            pass

        class Args:
            '''
            Iterates over argv items.
            '''
            def __init__( self, argv):
                self.items = iter( argv)
            def next( self, eof=ArgsRaise):
                '''
                Returns next arg. If no more args, we return <eof> or raise an
                exception if <eof> is ArgsRaise.
                '''
                try:
                    return next( self.items)
                except StopIteration:
                    if eof is ArgsRaise:
                        raise Exception('Not enough args')
                    return eof

        command = None
        opt_all = None
        opt_dist_dir = 'dist'
        opt_egg_base = None
        opt_formats = None
        opt_install_headers = None
        opt_record = None
        opt_root = None
        opt_verbose = False
        
        args = Args(argv[1:])

        while 1:
            arg = args.next(None)
            if arg is None:
                break

            elif arg in ('-h', '--help', '--help-commands'):
                _log(textwrap.dedent('''
                        Usage:
                            [<options>...] <command> [<options>...]
                        Commands:
                            bdist_wheel
                                Creates a wheel called
                                <dist-dir>/<name>-<version>-<details>.whl, where
                                <dist-dir> is "dist" or as specified by --dist-dir,
                                and <details> encodes ABI and platform etc.
                            clean
                                Cleans build files.
                            dist_info
                                Creates files in <egg-base>/.egg-info/, where
                                <egg-base> is as specified with --egg-base.
                            egg_info
                                Creates files in <egg-base>/.egg-info/, where
                                <egg-base> is as specified with --egg-base.
                            install
                                Builds and installs. Writes installation
                                information to <record> if --record was
                                specified.
                            sdist
                                Make a source distribution:
                                    <dist-dir>/<name>-<version>.tar.gz
                            dist_info
                                Like <egg_info> but creates files in
                                <egg-base>/<name>.dist-info/
                        Options:
                            --all
                                Used by "clean".
                            --compile
                                Ignored.
                            --dist-dir | -d <dist-dir>
                                Default is "dist".
                            --egg-base <egg-base>
                                Used by "egg_info".
                            --formats <formats>
                                Used by "sdist".
                            --install-headers <directory>
                                Ignored.
                            --python-tag <python-tag>
                                Ignored.
                            --record <record>
                                Used by "install".
                            --root <path>
                                Used by "install".
                            --single-version-externally-managed
                                Ignored.
                            --verbose -v
                                Extra diagnostics.
                        Other:
                            windows-vs [-y <year>] [-v <version>] [-g <grade] [--verbose]
                                Windows only; looks for matching Visual Studio.
                            windows-python [-v <version>] [--verbose]
                                Windows only; looks for matching Python.
                        '''))
                return

            elif arg in ('bdist_wheel', 'clean', 'dist_info', 'egg_info', 'install', 'sdist'):
                assert command is None, 'Two commands specified: {command} and {arg}.'
                command = arg

            elif arg == '--all':                                opt_all = True
            elif arg == '--compile':                            pass
            elif arg == '--dist-dir' or arg == '-d':            opt_dist_dir = args.next()
            elif arg == '--egg-base':                           opt_egg_base = args.next()
            elif arg == '--formats':                            opt_formats = args.next()
            elif arg == '--install-headers':                    opt_install_headers = args.next()
            elif arg == '--python-tag':                         pass
            elif arg == '--record':                             opt_record = args.next()
            elif arg == '--root':                               opt_root = args.next()
            elif arg == '--single-version-externally-managed':  pass
            elif arg == '--verbose' or arg == '-v':             opt_verbose = True
            
            elif arg == 'windows-vs':
                command = arg
                break
            elif arg == 'windows-python':
                command = arg
                break
            else:
               raise Exception(f'Unrecognised arg: {arg}')

        assert command, 'No command specified'

        _log(f'Handling command={command}')
        if 0:   pass
        elif command == 'bdist_wheel':  self.build_wheel(opt_dist_dir, verbose=opt_verbose)
        elif command == 'clean':        self._argv_clean(opt_all)
        elif command == 'dist_info':    self._argv_dist_info(opt_egg_base)
        elif command == 'egg_info':     self._argv_egg_info(opt_egg_base)
        elif command == 'install':      self._argv_install(opt_record, opt_root, opt_verbose)
        elif command == 'sdist':        self.build_sdist(opt_dist_dir, opt_formats, verbose=opt_verbose)
        
        elif command == 'windows-python':
            verbose = False
            version = None
            while 1:
                arg = args.next(None)
                if arg is None:
                    break
                elif arg == '-v':
                    version = args.next()
                elif arg == '--verbose':
                    verbose = True
                else:
                    assert 0, f'Unrecognised {arg=}'
            python = wdev.WindowsPython(version=version, verbose=verbose)
            print(f'Python is:\n{python.description_ml("    ")}')
            
        elif command == 'windows-vs':
            grade = None
            verbose = False
            version = None
            year = None
            while 1:
                arg = args.next(None)
                if arg is None:
                    break
                elif arg == '-g':
                    grade = args.next()
                elif arg == '-v':
                    version = args.next()
                elif arg == '-y':
                    year = args.next()
                elif arg == '--verbose':
                    verbose = True
                else:
                    assert 0, f'Unrecognised {arg=}'
            vs = wdev.WindowsVS(year=year, grade=grade, version=version, verbose=verbose)
            print(f'Visual Studio is:\n{vs.description_ml("    ")}')
        
        else:
            assert 0, f'Unrecognised command: {command}'

        _log(f'Finished handling command: {command}')


    def __str__(self):
        return ('{'
            f'name={self.name!r}'
            f' version={self.version!r}'
            f' platform={self.platform!r}'
            f' supported_platform={self.supported_platform!r}'
            f' summary={self.summary!r}'
            f' description={self.description!r}'
            f' description_content_type={self.description_content_type!r}'
            f' keywords={self.keywords!r}'
            f' home_page={self.home_page!r}'
            f' download_url={self.download_url!r}'
            f' author={self.author!r}'
            f' author_email={self.author_email!r}'
            f' maintainer={self.maintainer!r}'
            f' maintainer_email={self.maintainer_email!r}'
            f' license={self.license!r}'
            f' classifier={self.classifier!r}'
            f' requires_dist={self.requires_dist!r}'
            f' requires_python={self.requires_python!r}'
            f' requires_external={self.requires_external!r}'
            f' project_url={self.project_url!r}'
            f' provides_extra={self.provides_extra!r}'
            
            f' root={self.root!r}'
            f' fn_build={self.fn_build!r}'
            f' fn_sdist={self.fn_sdist!r}'
            f' fn_clean={self.fn_clean!r}'
            f' tag_python={self.tag_python!r}'
            f' tag_abi={self.tag_abi!r}'
            f' tag_platform={self.tag_platform!r}'
            '}'
            )

    def _dist_info_dir( self):
        return f'{self.name}-{self.version}.dist-info'

    def _metainfo(self):
        '''
        Returns text for `.egg-info/PKG-INFO` file, or `PKG-INFO` in an sdist
        `.tar.gz` file, or `...dist-info/METADATA` in a wheel.
        '''
        # 2021-04-30: Have been unable to get multiline content working on
        # test.pypi.org so we currently put the description as the body after
        # all the other headers.
        #
        ret = ['']
        def add(key, value):
            if value is not None:
                if isinstance( value, (tuple, list)):
                    for v in value:
                        add( key, v)
                else:
                    assert '\n' not in value, f'key={key} value contains newline: {value!r}'
                    ret[0] += f'{key}: {value}\n'
        #add('Description', self.description)
        add('Metadata-Version', '2.1')
        
        # These names are from:
        # https://packaging.python.org/specifications/core-metadata/
        #
        for name in (
                'Name',
                'Version',
                'Platform',
                'Supported-Platform',
                'Summary',
                'Description-Content-Type',
                'Keywords',
                'Home-page',
                'Download-URL',
                'Author',
                'Author-email',
                'Maintainer',
                'Maintainer-email',
                'License',
                'Classifier',
                'Requires-Dist',
                'Requires-Python',
                'Requires-External',
                'Project-URL',
                'Provides-Extra',
                ):
            identifier = name.lower().replace( '-', '_')
            add( name, getattr( self, identifier))
        
        ret = ret[0]

        # Append description as the body
        if self.description:
            ret += '\n' # Empty line separates headers from body.
            ret += self.description.strip()
            ret += '\n'
        return ret

    def _path_relative_to_root(self, path, assert_within_root=True):
        '''
        Returns `(path_abs, path_rel)`, where `path_abs` is absolute path and
        `path_rel` is relative to `self.root`.

        Interprets `path` as relative to `self.root` if not absolute.

        We use `os.path.realpath()` to resolve any links.

        if `assert_within_root` is true, assert-fails if `path` is not within
        `self.root`.
        '''
        if os.path.isabs(path):
            p = path
        else:
            p = os.path.join(self.root, path)
        p = os.path.realpath(os.path.abspath(p))
        if assert_within_root:
            assert p.startswith(self.root+os.sep), f'Path not within root={self.root+os.sep!r}: {path}'
        p_rel = os.path.relpath(p, self.root)
        return p, p_rel

    def _fromto(self, p):
        '''
        Returns `((from_abs, from_rel), (to_abs, to_rel))`.

        If `p` is a string we convert to `(p, p)`. Otherwise we assert that
        `p` is a tuple of two strings. Non-absolute paths are assumed to be
        relative to `self.root`.

        If `to_` starts with `$dist-info/`, we replace this with
        `self._dist_info_dir()`.

        If `to_` starts with `$data/`, we replace this with
        `self._dist_info_dir()`.

        `from_abs` and `to_abs` are absolute paths. We assert that `to_abs` is
        `within self.root`.

        `from_rel` and `to_rel` are derived from the `_abs` paths and are
        `relative to self.root`.
        '''
        ret = None
        if isinstance(p, str):
            ret = p, p
        elif isinstance(p, tuple) and len(p) == 2:
            from_, to_ = p
            if isinstance(from_, str) and isinstance(to_, str):
                ret = from_, to_
        assert ret, 'p should be str or (str, str), but is: {p}'
        from_, to_ = ret
        prefix = '$dist-info/'
        if to_.startswith( prefix):
            to_ = f'{self._dist_info_dir()}/{to_[ len(prefix):]}'
        prefix = '$data/'
        if to_.startswith( prefix):
            to_ = f'{self.name}-{self.version}.data/{to_[ len(prefix):]}'
        from_ = self._path_relative_to_root( from_, assert_within_root=False)
        to_ = self._path_relative_to_root(to_)
        return from_, to_


def build_extension(
        name,
        path_i,
        outdir,
        includes=None,
        defines=None,
        libpaths=None,
        libs=None,
        force=True,
        optimise=True,
        debug=False,
        compiler_extra='',
        linker_extra='',
        swig='swig',
        cpp=True,
        ):
    '''
    Builds a C++ Python extension module using SWIG.
    
    Works on Unix and Windows.
    
    Args:
        name:
            Name of generated extension module.
        path_i:
            Path of input SWIG .i file. Internally we use swig to generate a
            corresponding `.c` or `.cpp` file.
        outdir:
            Output directory for generated files:
                {outdir}/{name}.py
                {outdir}/_{name}.so     # Unix
                {outdir}/_{name}.*.pyd  # Windows
            We return the leafname of the `.so` or `.pyd` file.
        includes:
            A string, or a sequence of extra include directories to be prefixed
            with `-I`.
        defines:
            A string, or a sequence of extra preprocessor defines to be
            prefixed with `-D`.
        libpaths
            A string, or a sequence of library paths to be prefixed with
            `/LIBPATH:` on Windows or `-L` on Unix.
        libs
            A string, or a sequence of library names to be prefixed with `-l`.
        force:
            Empty string or None:
                Run commands if files seem to be out of date; this might
                erroneously not rebuild.
            False, 0 or '0':
                Do not run any commands.
            True, 1 or '1':
                Always run commands.
        optimise:
            Whether to use compiler optimisations.
        debug:
            Whether to build with debug symbols.
        compiler_extra:
            Extra compiler flags.
        linker_extra:
            Extra linker flags.
        swig:
            Base swig command.
    
    Returns the leafname of the generated library file within `outdir`, e.g.
    `_{name}.so` on Unix or `_{name}.cp311-win_amd64.pyd` on Windows.
    '''
    includes_text = _flags( includes, '-I')
    defines_text = _flags( defines, '-D')
    libpaths_text = _flags( libpaths, '/LIBPATH:', '"') if windows() else _flags( libpaths, '-L')
    libs_text = _flags( libs, '-l')
    path_cpp = f'{path_i}.cpp' if cpp else f'{path_i}.c'
    if not os.path.exists( outdir):
        os.mkdir( outdir)
    # Run SWIG.
    #run( f'{swig} -version')
    if _doit(force, _fs_mtime(path_i) >= _fs_mtime(path_cpp)):
        run( f'''
                {swig}
                    -Wall
                    {"-c++" if cpp else ""}
                    -python
                    -module {name}
                    -outdir {outdir}
                    -o {path_cpp}
                    {includes_text}
                    {path_i}
                '''
                )
    else:
        _log(f'Not running swig because {path_cpp} newer than {path_i}')
    
    if windows():
        python_version = ''.join(platform.python_version_tuple()[:2])
        base            = f'_{name}.cp{python_version}-win_amd64'
        path_so_leaf    = f'{base}.pyd'
        path_so         = f'{outdir}/{path_so_leaf}'
        path_obj        = f'{path_so}.obj'
        
        permissive = '/permissive-'
        EHsc = '/EHsc'
        T = '/Tp' if cpp else '/Tc'
        optimise2 = '/DNDEBUG /O2' if optimise else ''
        
        command, flags = base_compiler(cpp=cpp)
        command = f'''
                {command}
                    # General:
                    /c                          # Compiles without linking.
                    {EHsc}                      # Enable "Standard C++ exception handling".
                    /MD                         # Creates a multithreaded DLL using MSVCRT.lib.

                    # Input/output files:
                    {T}{path_cpp}               # /Tp specifies C++ source file.
                    /Fo{path_obj}               # Output file.

                    # Include paths:
                    {includes_text}
                    {flags.includes}            # Include path for Python headers.

                    # Code generation:
                    {optimise2}
                    {permissive}                # Set standard-conformance mode.

                    # Diagnostics:
                    #/FC                         # Display full path of source code files passed to cl.exe in diagnostic text.
                    /W3                         # Sets which warning level to output. /W3 is IDE default.
                    /diagnostics:caret          # Controls the format of diagnostic messages.
                    /nologo                     #

                    {defines_text}
                    {compiler_extra}
                '''
        if _doit( force, _fs_mtime(path_cpp) >= _fs_mtime(path_obj)):
            run(command)
        else:
            _log(f'Not compiling because {path_cpp!r} older than {path_obj!r}.')

        command, flags = base_linker(cpp=cpp)
        command = f'''
                {command}
                    /DLL                    # Builds a DLL.
                    /EXPORT:PyInit__{name}  # Exports a function.
                    /IMPLIB:{base}.lib      # Overrides the default import library name.
                    {libpaths_text}
                    {flags.libs}
                    /OUT:{path_so}          # Specifies the output file name.
                    /nologo
                    {libs_text}
                    {path_obj}
                    {linker_extra}
                '''
        if _doit( force, _fs_mtime(path_obj) >= _fs_mtime(path_so)):
            run(command)
        else:
            _log(f'Not linking because {path_obj!r} older than {path_so!r}.')
    
    else:
    
        # Not Windows.
        #
        path_so_leaf = f'_{name}.so'
        path_so = f'{outdir}/{path_so_leaf}'
        cpp_flags = ''
        if debug:
            cpp_flags += ' -g'
        if optimise:
            cpp_flags += ' -O2 -DNDEBUG'
        cpp_flags = cpp_flags.strip()
        # Fun fact - on Linux, if the -L and -l options are before '{path_cpp}
        # -o {path_so}' they seem to be ignored...
        #
        # We use compiler to compile and link in one command.
        #
        command, flags = base_compiler(cpp=cpp)
        command = f'''
                {command}
                    -fPIC
                    -shared
                    {flags.includes}
                    {includes_text}
                    {defines_text}
                    {cpp_flags}
                    {path_cpp}
                    -o {path_so}
                    {compiler_extra}
                    {libpaths_text}
                    {libs_text}
                    -Wl,-rpath='$ORIGIN',-z,origin
                    {linker_extra}
                '''
        if _doit( force, lambda: _fs_mtime( path_cpp, 0) >= _fs_mtime( path_so, 0)):
            run(command)
        else:
            _log(f'Not compiling+linking because {path_cpp!r} older than {path_so!r}.')
    
    return path_so_leaf


# Functions that might be useful.
#

def base_compiler(vs=None, flags=None, cpp=False):
    '''
    Returns basic compiler command.
    
    Args:
        vs:
            Windows only. A `wdev.WindowsVS` instance or None to use default
            `wdev.WindowsVS` instance.
        flags:
            A `pipcl.PythonFlags` instance or None to use default
            `pipcl.PythonFlags` instance.
        cpp:
            If true we return C++ compiler command instead of C. On Windows
            this has no effect - we always return cl.exe.
    
    Returns (cc, flags):
        cc:
            C or C++ command. On Windows this is of the form
            `{vs.vcvars}&&{vs.cl}`; otherwise it is `cc` or `c++`.
        flags:
            The `flags` arg or a new `pipcl.PythonFlags` instance.
    '''
    if not flags:
        flags = PythonFlags()
    if windows():
        if not vs:
            vs = wdev.WindowsVS()
        cc = f'"{vs.vcvars}"&&"{vs.cl}"'
    else:
        cc = 'c++' if cpp else 'cc'
    return cc, flags


def base_linker(vs=None, flags=None, cpp=False):
    '''
    Returns basic linker command.
    
    Args:
        vs:
            Windows only. A `wdev.WindowsVS` instance or None to use default
            `wdev.WindowsVS` instance.
        flags:
            A `pipcl.PythonFlags` instance or None to use default
            `pipcl.PythonFlags` instance.
        cpp:
            If true we return C++ linker command instead of C. On Windows this
            has no effect - we always return link.exe.
    
    Returns (linker, flags):
        linker:
            Linker command. On Windows this is of the form
            `{vs.vcvars}&&{vs.link}`; otherwise it is `cc` or `c++`.
        flags:
            The `flags` arg or a new `pipcl.PythonFlags` instance.
    '''
    if not flags:
        flags = PythonFlags()
    if windows():
        if not vs:
            vs = wdev.WindowsVS()
        linker = f'"{vs.vcvars}"&&"{vs.link}"'
    else:
        linker = 'c++' if cpp else 'cc'
    return linker, flags
    

def git_items( directory, submodules=False):
    '''
    Returns list of paths for all files known to git within `directory`. Each
    path is relative to `directory`.

    `directory` must be somewhere within a git checkout.

    We run a `git ls-files` command internally.

    This function can be useful for the `fn_sdist() callback.
    '''
    command = 'cd ' + directory + ' && git ls-files'
    if submodules:
        command += ' --recurse-submodules'
    text = subprocess.check_output( command, shell=True)
    ret = []
    for path in text.decode('utf8').strip().split( '\n'):
        path2 = os.path.join(directory, path)
        # Sometimes git ls-files seems to list empty/non-existant directories
        # within submodules.
        #
        if not os.path.exists(path2):
            _log(f'*** Ignoring git ls-files item that does not exist: {path2}')
        elif os.path.isdir(path2):
            _log(f'*** Ignoring git ls-files item that is actually a directory: {path2}')
        else:
            ret.append(path)
    return ret


def run( command, verbose=1):
    '''
    Outputs diagnostic describing `command` than runs using `subprocess.run()`.
    
    Args:
        command:
            A string, the command to run.

            `command` can be multi-line and we use `textwrap.dedent()` to
            improve formatting.

            Lines in `command` can contain comments:
            
            * If a line starts with `#` it is discarded.
            * If a line contains ` #` the trailing text is discarded.

            When running the command, on Windows newlines are replaced by
            spaces; otherwise each line is terminated by a backslash character.
    Returns:
        None on success, otherwise raises an exception.
    '''
    lines = _command_lines( command)
    if verbose:
        nl = '\n'
        _log( f'Running: {nl.join(lines)}')
    sep = ' ' if windows() else '\\\n'
    command2 = sep.join( lines) 
    subprocess.run( command2, shell=True, check=True)


def windows():
    return platform.system() == 'Windows'


class PythonFlags:
    '''
    Compile/link flags for the current python, for example the include path
    needed to get `Python.h`.
    
    Members:
        .includes:
            String containing compiler flags for include paths.
        .libs:
            String containing linker flags for library paths.
    '''
    def __init__(self):
        if windows():
            wp = wdev.WindowsPython()
            self.includes = f'/I{wp.root}\\include'
            self.libs = f'/LIBPATH:"{wp.root}\\libs"'
        else:
            # We use python-config which appears to work better than pkg-config
            # because it copes with multiple installed python's, e.g.
            # manylinux_2014's /opt/python/cp*-cp*/bin/python*.
            #
            # But... it seems that we should not attempt to specify libpython
            # on the link command. The manylinkux docker containers don't
            # actually contain libpython.so, and it seems that this
            # deliberate. And the link command runs ok.
            #
            python_exe = os.path.realpath( sys.executable)
            python_config = f'{python_exe}-config'
            self.includes = subprocess.run(
                    f'{python_config} --includes',
                    shell=True,
                    capture_output=True,
                    check=True,
                    encoding='utf8',
                    ).stdout.strip()
            self.libs = ''


# Internal helpers.
#

def _command_lines( command):
    '''
    Process multiline command by running through `textwrap.dedent()`, removes
    comments (lines starting with `#` or ` #` until end of line), removes
    entirely blank lines.

    Returns list of lines.
    '''
    command = textwrap.dedent( command)
    lines = []
    for line in command.split( '\n'):
        if line.startswith( '#'):
            h = 0
        else:
            h = line.find( ' #')
        if h >= 0:
            line = line[:h]
        if line.strip():
            lines.append(line.rstrip())
    return lines


def _cpu_name():
    '''
    Returns `x32` or `x64` depending on Python build.
    '''
    #log(f'sys.maxsize={hex(sys.maxsize)}')
    return f'x{32 if sys.maxsize == 2**31 else 64}'



def _doit( force, default):
    '''
    Returns true/false for whether to run a command.
    '''
    if force in (None, ''):
        return default() if callable(default) else default
    elif force in (True, 1, '1'):
        return True
    elif force in (False, 0, '0'):
        return False
    else:
        assert 0, f'Unrecognised {force=}'
    

def _flags( items, prefix='', quote=''):
    '''
    Turns sequence into string, prefixing/quoting each item.
    '''
    if not items:
        return ''
    if isinstance( items, str):
        return items
    ret = ''
    for item in items:
        if ret:
            ret += ' '
        ret += f'{prefix}{quote}{item}{quote}'
    return ret.strip()


def _fs_mtime( filename, default=0):
    '''
    Returns mtime of file, or `default` if error - e.g. doesn't exist.
    '''
    try:
        return os.path.getmtime( filename)
    except OSError:
        return default

def _log(text=''):
    '''
    Logs lines with prefix.
    '''
    caller = inspect.stack()[1].function
    for line in text.split('\n'):
        print(f'pipcl.py: {caller}(): {line}')
    sys.stdout.flush()


class _Record:
    '''
    Internal - builds up text suitable for writing to a RECORD item, e.g.
    within a wheel.
    '''
    def __init__(self):
        self.text = ''

    def add_content(self, content, to_, verbose=False):
        if isinstance(content, str):
            content = content.encode('utf8')
        h = hashlib.sha256(content)
        digest = h.digest()
        digest = base64.urlsafe_b64encode(digest)
        self.text += f'{to_},sha256={digest},{len(content)}\n'
        if verbose:
            _log(f'Adding {to_}')

    def add_file(self, from_, to_, verbose=False):
        with open(from_, 'rb') as f:
            content = f.read()
        self.add_content(content, to_, verbose=False)
        if verbose:
            _log(f'Adding file: {os.path.relpath(from_)} => {to_}')

    def get(self):
        return self.text
