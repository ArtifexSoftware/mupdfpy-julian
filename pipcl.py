'''
Support for Python packaging operations.
'''

import base64
import distutils.util
import glob
import hashlib
import io
import os
import platform
import re
import shutil
import site
import subprocess
import sys
import sysconfig
import tarfile
import textwrap
import time
import zipfile


class Package:
    '''
    Python packaging operations, including PEP-517 support, for use by a
    `setup.py` script.

    Our constructor takes a definition of a Python package similar to that
    passed to `distutils.core.setup()` or `setuptools.setup()` - name, version,
    summary etc, plus callbacks for build, clean and sdist filenames.

    We provide methods that can be used to implement a Python package's
    `setup.py` supporting PEP-517, plus basic command line handling for use
    with a legacy (pre-PEP-517) pip.

    A setup.py can be implemented with::

        import pipcl
        import subprocess

        def build():
            subprocess.check_call('cc -shared -fPIC -o foo.so foo.c')
            return ['foo.py', 'foo.so']

        def sdist():
            return ['foo.py', 'foo.c', 'pyproject.toml', ...]

        p = pipcl.Package('foo', '1.2.3', fn_build=build, fn_sdist=sdist, ...)

        build_wheel = p.build_wheel
        build_sdist = p.build_sdist

    Handle old-style setup.py command-line usage by appending::

        import sys
        if __name__ == '__main__':
            p.handle_argv(sys.argv)
    
    This supports some of the command-line usage expected by older versions of
    `pip`, implemented by legacy distutils/setuptools, and also described in:
    https://pip.pypa.io/en/stable/reference/build-system/setup-py/
    
    Wheels:
        We generate wheels according to:
        https://packaging.python.org/specifications/binary-distribution-format/
        * `<name>-<version>.dist-info/RECORD` uses sha256 hashes.
          * We do not generate other `RECORD*` files such as `RECORD.jws` and
              `RECORD.p7s`.
        * `<name>-<version>.dist-info/WHEEL` has:
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
            ):
        '''
        Specification of package.
        
        The initial args before `root` define the package
        metadata and closely follow the definitions in:
        https://packaging.python.org/specifications/core-metadata/
        
        name:
            A string, the name of the Python package.
        version:
            A string, the version of the Python package. Also see PEP-440
            "Version Identification and Dependency Specification".
        platform:
            A string or list of strings.
        supported_platform:
            A string or list of strings.
        summary:
            A string.
        description:
            A string.
        description_content_type:
            A string describing markup of `description` arg. For example:
                    text/markdown; variant=GFM
        keywords:
            A string containing comma-separated keywords.
        home_page:
            .
        download_url:
            Where this version can be downloaded from.
        author:
            .
        author_email:
            .
        maintainer:
            .
        maintainer_email:
            .
        license:
            A string containing the license text.
        classifier:
            A string or list of strings. Also see:
                https://pypi.org/pypi?%3Aaction=list_classifiers
                https://pypi.org/classifiers/
        requires_dist:
            A string or list of strings. Also see PEP-508.
        requires_python:
            A string or list of strings.
        requires_external:
            A string or list of strings.
        project_url:
            A string or list of strings, each of the form: `<name>, <url>`.
        provides_extra:
            A string or list of strings.
        
        root:
            Root of package, defaults to current directory.
        fn_build:
            A function taking no args that builds the package.

            Should return a list of items; each item should be a tuple of two
            strings `(from_, to_)`, or a single string `path` which is treated
            as the tuple `(path, path)`.

            `from_` should be the path to a file; if a relative path it is
            assumed to be relative to `root`. `to_` identifies what the file
            should be called within a wheel or when installing.
            
            Initial `$dist-info/` in `_to` is replaced by
            `<name>-<version>.dist-info/`; this is useful for license files
            etc.

            Initial `$data/` in `_to` is replaced by
            `<name>-<version>.data/`. We do not enforce particular
            subdirectories, instead it is up to `fn_build()` to use specific
            subdirectories such as 'purelib', 'headers', 'scripts', 'data' etc.

            If we are building a wheel (e.g. 'bdist_wheel' in the argv passed
            to `self.handle_argv()` or PEP-517 pip calls `self.build_wheel()`),
            we copy file `from_` to `to_` inside the wheel archive.

            If we are installing (e.g. 'install' command in the argv
            passed to `self.handle_argv()`), then we copy `from_` to
            `sitepackages`/`to_`, where `sitepackages` is the installation
            directory, the default being `sysconfig.get_path('platlib')` e.g.
            `myvenv/lib/python3.9/site-packages/`.
        fn_clean:
            A function taking a single arg `all_` that cleans generated files.
            `all_` is true iff '--all' is in argv.

            For safety and convenience, can also returns a list of
            files/directory paths to be deleted. Relative paths are interpreted
            as relative to `root` and other paths are asserted to be within
            `root`.
        fn_sdist:
            A function taking no args that returns a list of paths, e.g. using
            `pipcl.git_items()`, for files that should be copied into the
            sdist. Relative paths are interpreted as relative to `root`. It is
            an error if a path does not exist or is not a file. The list must
            contain `pyproject.toml`.
        tag_python:
            First element of wheel tag defined in PEP-425. If None we use
            'cp<version>'.
        tag_abi:
            Second element of wheel tag defined in PEP-425. If None we use
            'none'.
        tag_platform:
            Third element of wheel tag defined in PEP-425. Default is derived
            from `distutils.util.get_platform()` as specified in the PEP, e.g.
            'openbsd_7_0_amd64'.
            
            For pure python packages use: `tag_platform='any'`
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


    def build_wheel(self, wheel_directory, config_settings=None, metadata_directory=None):
        '''
        A PEP-517 `build_wheel()` function.

        Also called by `handle_argv()` to handle the 'bdist_wheel' command.

        Returns leafname of generated wheel within `wheel_directory`.
        '''
        _log('build_wheel():'
                f' wheel_directory={wheel_directory}'
                f' config_settings={config_settings}'
                f' metadata_directory={metadata_directory}'
                )
        _log('build_wheel(): os.environ is:')
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
            tag_platform = distutils.util.get_platform().replace('-', '_').replace('.', '_')

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

        _log(f'build_wheel(): Writing wheel {path} ...')
        os.makedirs(wheel_directory, exist_ok=True)
        record = _Record()
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:

            def add_file(from_, to_):
                z.write(from_, to_)
                record.add_file(from_, to_)

            def add_str(content, to_):
                z.writestr(to_, content)
                record.add_content(content, to_)

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

        _log( f'build_wheel(): Have created wheel: {path}')
        return os.path.basename(path)


    def build_sdist(self, sdist_directory, formats, config_settings=None):
        '''
        A PEP-517 `build_sdist()` function.

        Also called by `handle_argv()` to handle the 'sdist' command.

        Returns leafname of generated archive within `sdist_directory`.
        '''
        _log( f'build_sdist(): formats={formats}')
        if formats and formats != 'gztar':
            raise Exception( f'Unsupported: formats={formats}')
        paths = []
        if self.fn_sdist:
            paths = self.fn_sdist()

        manifest = []
        def add(tar, name, contents):
            '''
            Adds item called `name` to `tarfile.TarInfo` `tar`, containing
            `contents`. If contents is a string, it is encoded using utf8.
            '''
            if isinstance(contents, str):
                contents = contents.encode('utf8')
            ti = tarfile.TarInfo(name)
            ti.size = len(contents)
            ti.mtime = time.time()
            tar.addfile(ti, io.BytesIO(contents))

        os.makedirs(sdist_directory, exist_ok=True)
        tarpath = f'{sdist_directory}/{self.name}-{self.version}.tar.gz'
        _log(f'build_sdist(): Writing sdist {tarpath} ...')
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
                #log(f'path={path}')
                tar.add( path_abs, f'{self.name}-{self.version}/{path_rel}', recursive=False)
                manifest.append(path_rel)
            assert found_pyproject_toml, f'No pyproject.toml specified.'
            # Always add a PKG-INFO file.
            add(tar, f'{self.name}-{self.version}/PKG-INFO', self._metainfo())

            if self.license:
                add(tar, f'{self.name}-{self.version}/COPYING', self.license)
            
        _log( f'build_sdist(): Have created sdist: {tarpath}')
        return os.path.basename(tarpath)


    def argv_clean(self, all_):
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


    def argv_install(self, record_path, root, verbose=False):
        '''
        Called by `handle_argv()` to handle 'install' command..
        '''
        if verbose:
            _log( f'argv_install(): {record_path=} {root=}')
        
        # Do a build and get list of files to install.
        #
        items = []
        if self.fn_build:
            items = self.fn_build()

        if root is None:
            root = sysconfig.get_path('platlib')
            if verbose:
                _log( f'argv_install(): Using sysconfig.get_path("platlib")={root!r}.')
            # todo: for pure-python we should use sysconfig.get_path('purelib') ?
        
        _log( f'argv_install(): Installing into {root=}')
        dist_info_dir = self._dist_info_dir()
        
        if not record_path:
            record_path = f'{root}/{dist_info_dir}/RECORD'
        record = _Record()
        
        def add_file(from_abs, from_rel, to_abs, to_rel):
            if verbose:
                _log(f'argv_install(): copying from {from_abs} to {to_abs}')
            os.makedirs( os.path.dirname( to_abs), exist_ok=True)
            shutil.copy2( from_abs, to_abs)
            if verbose:
                _log(f'argv_install(): adding to record: {from_rel=} {to_rel=}')
            record.add_file(from_rel, to_rel)

        def add_str(content, to_abs, to_rel):
            if verbose:
                _log( f'argv_install(): Writing to: {to_abs}')
            with open( to_abs, 'w') as f:
                f.write( content)
            record.add_content(content, to_rel)
        
        for item in items:
            (from_abs, from_rel), (to_abs, to_rel) = self._fromto(item)
            to_abs2 = f'{root}/{to_rel}'
            add_file( from_abs, from_rel, to_abs2, to_rel)
        
        add_str( self._metainfo(), f'{root}/{dist_info_dir}/METADATA', f'{dist_info_dir}/METADATA')

        if verbose:
            _log( f'argv_install(): Writing to: {record_path}')
        with open(record_path, 'w') as f:
            f.write(record.get())

        if verbose:
            _log(f'argv_install(): Finished.')


    def argv_dist_info(self, root):
        '''
        Called by `handle_argv()`. There doesn't seem to be any documentation
        for 'setup.py dist_info', but it appears to be like 'egg_info' except it
        writes to a slightly different directory.
        '''
        if root is None:
            root = f'{self.name}-{self.version}.dist-info'
        self._write_info(f'{root}/METADATA')
        if self.license:
            with open( f'{root}/COPYING', 'w') as f:
                f.write( self.license)


    def argv_egg_info(self, egg_base):
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
        _log(f'_write_info(): creating files in directory {dirpath}')
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
        #_log(f'handle_argv(): argv: {argv}')

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
            
            elif arg == 'windows-vs':
                command = arg
                break
            elif arg == 'windows-python':
                command = arg
                break
            else:
               raise Exception(f'Unrecognised arg: {arg}')

        assert command, 'No command specified'

        _log(f'handle_argv(): Handling command={command}')
        if 0:   pass
        elif command == 'bdist_wheel':  self.build_wheel(opt_dist_dir)
        elif command == 'clean':        self.argv_clean(opt_all)
        elif command == 'dist_info':    self.argv_dist_info(opt_egg_base)
        elif command == 'egg_info':     self.argv_egg_info(opt_egg_base)
        elif command == 'install':      self.argv_install(opt_record, opt_root)
        elif command == 'sdist':        self.build_sdist(opt_dist_dir, opt_formats)
        
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
            python = WindowsPython(version=version, verbose=verbose)
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
            vs = WindowsVS(year=year, grade=grade, version=version, verbose=verbose)
            print(f'Visual Studio is:\n{vs.description_ml("    ")}')
        
        else:
            assert 0, f'Unrecognised command: {command}'

        _log(f'handle_argv(): Finished handling command={command}')


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

        if assert_within_root is true, assert-fails if `path` is not within
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


# Functions that might be useful.
#

def git_items( directory, submodules=False):
    '''
    Returns list of paths for all files known to git within `directory`. Each
    path is relative to `directory`.

    `directory` must be somewhere within a git checkout.

    We run a 'git ls-files' command internally.
    
    This function can be useful for the `fn_sdist()  callback.
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


def parse_pkg_info(path):
    '''
    Parses a `PKJG-INFO` file, each line is `<key>: <value>\n`. Returns a dict.
    '''
    ret = dict()
    with open(path) as f:
        for line in f:
            s = line.find(': ')
            if s >= 0 and line.endswith('\n'):
                k = line[:s]
                v = line[s+2:-1]
                ret[k] = v
    return ret


# Implementation helpers.
#

def _log(text=''):
    '''
    Logs lines with prefix.
    '''
    for line in text.split('\n'):
        print(f'pipcl.py: {line}')
    sys.stdout.flush()


class _Record:
    '''
    Internal - builds up text suitable for writing to a RECORD item, e.g.
    within a wheel.
    '''
    def __init__(self):
        self.text = ''

    def add_content(self, content, to_):
        if isinstance(content, str):
            content = content.encode('utf8')
        h = hashlib.sha256(content)
        digest = h.digest()
        digest = base64.urlsafe_b64encode(digest)
        self.text += f'{to_},sha256={digest},{len(content)}\n'

    def add_file(self, from_, to_):
        with open(from_, 'rb') as f:
            content = f.read()
        self.add_content(content, to_)

    def get(self):
        return self.text


def cpu_name():
    '''
    Returns 'x32' or 'x64' depending on Python build.
    '''
    #log(f'sys.maxsize={hex(sys.maxsize)}')
    return f'x{32 if sys.maxsize == 2**31 else 64}'


class WindowsCpu:
    '''
    For Windows only. Paths and names that depend on cpu.

    Members:
        .bits
            32 or 64.
        .windows_subdir
            '' or 'x64/'.
        .windows_name
            'x86' or 'x64'.
        .windows_config
            'x64' or 'Win32', e.g. /Build Release|x64
        .windows_suffix
            '64' or ''.
    '''
    def __init__(self, name=None):
        if not name:
            name = cpu_name()
        self.name = name
        if name == 'x32':
            self.bits = 32
            self.windows_subdir = ''
            self.windows_name = 'x86'
            self.windows_config = 'Win32'
            self.windows_suffix = ''
        elif name == 'x64':
            self.bits = 64
            self.windows_subdir = 'x64/'
            self.windows_name = 'x64'
            self.windows_config = 'x64'
            self.windows_suffix = '64'
        else:
            assert 0, f'Unrecognised cpu name: {name}'

    def __str__(self):
        return self.name


class WindowsPython:
    '''
    Experimental. Windows only. Information about installed Python with
    specific word size and version.

    Members:

        .path:
            Path of python binary.
        .version:
            `<major>.<minor>`, e.g. '3.9' or '3.11'. Same as `version` passed
            to `__init__()` if not None, otherwise the inferred version.
        .root:
            The parent directory of `.path`; allows
            Python headers to be found, for example
            `<root>/include/Python.h`.
        .cpu:
            A `WindowsCpu` instance, same as `cpu` passed to `__init__()` if
            not None, otherwise the inferred cpu.

    We parse the output from 'py -0p' to find all available python
    installations.
    '''
    
    def __init__( self, cpu=None, version=None, verbose=False):
        '''
        cpu:
            A WindowsCpu instance. If None, we use whatever we are running on.
        version:
            Two-digit Python version as a string such as '3.8'. If None we use
            current Python's version.
        verbose:
            If true we show diagnostics.

        We parse the output from 'py -0p' to find all available python
        installations.
        '''
        if cpu is None:
            cpu = WindowsCpu(cpu_name())
        if version is None:
            version = '.'.join(platform.python_version().split('.')[:2])
        command = 'py -0p'
        if verbose:
            _log(f'Running: {command}')
        text = subprocess.check_output( command, shell=True, text=True)
        for line in text.split('\n'):
            #_log( f'    {line}')
            m = re.match( '^ *-V:([0-9.]+)(-32)? ([*])? +(.+)$', line)
            if not m:
                if verbose:
                    _log( f'No match for {line=}')
                continue
            version2 = m.group(1)
            bits = 32 if m.group(2) else 64
            current = m.group(3)
            if verbose:
                _log( f'{version2=} {bits=}')
            if bits != cpu.bits or version2 != version:
                continue
            path = m.group(4).strip()
            root = path[ :path.rfind('\\')]
            if not os.path.exists(path):
                # Sometimes it seems that the specified .../python.exe does not exist,
                # and we have to change it to .../python<version>.exe.
                #
                assert path.endswith('.exe'), f'path={path!r}'
                path2 = f'{path[:-4]}{version}.exe'
                _log( f'Python {path!r} does not exist; changed to: {path2!r}')
                assert os.path.exists( path2)
                path = path2

            self.path = path
            self.version = version
            self.root = root
            self.cpu = cpu
            #_log( f'pipcl.py:WindowsPython():\n{self.description_ml("    ")}')
            return
        
        raise Exception( f'Failed to find python matching cpu={cpu}. Run "py -0p" to see available pythons')
        
    def description_ml(self, indent=''):
        ret = textwrap.dedent(f'''
                root:    {self.root}
                path:    {self.path}
                version: {self.version}
                cpu:     {self.cpu}
                ''')
        return textwrap.indent( ret, indent)


class WindowsVS:
    '''
    Experimental. Windows only. Finds locations of Visual Studio command-line
    tools. Assumes VS2019-style paths.
    
    Members and example values:
    
        .year:      2019
        .grade:     Community
        .version:   14.28.29910
        .directory: C:\Program Files (x86)\Microsoft Visual Studio\2019\Community
        .vcvars:    C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat
        .cl:        C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC\14.28.29910\bin\Hostx64\x64\cl.exe
        .link:      C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC\14.28.29910\bin\Hostx64\x64\link.exe
        .devenv:    C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\Common7\IDE\devenv.com
    '''
    def __init__( self, year=None, grade=None, version=None, cpu=None, verbose=False):
        '''
        Args:
            year:
                None or, for example, '2019'.
            grade:
                None or, for example, one of:
                    'Community'
                    'Professional'
                    'Enterprise'
            version:
                None or, for example: '14.28.29910'
            cpu:
                None or a `WindowsCpu` instance.
        '''
        if not cpu:
            cpu = WindowsCpu()

        # Find `directory`.
        #
        pattern = f'C:\\Program Files*\\Microsoft Visual Studio\\{year if year else "2*"}\\{grade if grade else "*"}'
        directories = glob.glob( pattern)
        if verbose:
            _log( f'Matches for: {pattern=}')
            _log( f'{directories=}')
        assert directories, f'No match found for: {pattern}'
        directories.sort()
        directory = directories[-1]

        # Find `devenv`.
        #
        devenv = f'{directory}\\Common7\\IDE\\devenv.com'
        assert os.path.isfile( devenv), f'Does not exist: {devenv}'

        # Extract `year` and `grade` from `directory`.
        #    
        # We use r'...' for regex strings because an extra level of escaping is
        # required for backslashes.
        #
        regex = rf'^C:\\Program Files.*\\Microsoft Visual Studio\\([^\\]+)\\([^\\]+)'
        m = re.match( regex, directory)
        assert m, f'No match: {regex=} {directory=}'
        year2 = m.group(1)
        grade2 = m.group(2)
        if year:
            assert year2 == year
        else:
            year = year2
        if grade:
            assert grade2 == grade
        else:
            grade = grade2

        # Find vcvars.bat.
        #
        vcvars = f'{directory}\\VC\Auxiliary\\Build\\vcvars{cpu.bits}.bat'
        assert os.path.isfile( vcvars), f'No match for: {vcvars}'

        # Find cl.exe.
        #
        cl_pattern = f'{directory}\\VC\\Tools\\MSVC\\{version if version else "*"}\\bin\\Host{cpu.windows_name}\\{cpu.windows_name}\\cl.exe'
        cl_s = glob.glob( cl_pattern)
        assert cl_s, f'No match for: {cl_pattern}'
        cl_s.sort()
        cl = cl_s[ -1]

        # Extract `version` from cl.exe's path.
        #
        m = re.search( rf'\\VC\\Tools\\MSVC\\([^\\]+)\\bin\\Host{cpu.windows_name}\\{cpu.windows_name}\\cl.exe$', cl)
        assert m
        version2 = m.group(1)
        if version:
            assert version2 == version
        else:
            version = version2
        assert version

        # Find link.exe.
        #
        link_pattern = f'{directory}\\VC\\Tools\\MSVC\\{version}\\bin\\Host{cpu.windows_name}\\{cpu.windows_name}\\link.exe'
        link_s = glob.glob( link_pattern)
        assert link_s, f'No match for: {link_pattern}'
        link_s.sort()
        link = link_s[ -1]

        self.cl = cl
        self.devenv = devenv
        self.directory = directory
        self.grade = grade
        self.link = link
        self.vcvars = vcvars
        self.version = version
        self.year = year

    def description_ml( self, indent=''):
        ret = textwrap.dedent(f'''
                year:         {self.year}
                grade:        {self.grade}
                version:      {self.version}
                directory:    {self.directory}
                vcvars:       {self.vcvars}
                cl:           {self.cl}
                link:         {self.link}
                devenv:       {self.devenv}
                ''')
        return textwrap.indent( ret, indent)
    
    def __str__( self):
        return ' '.join( self._description())
    
