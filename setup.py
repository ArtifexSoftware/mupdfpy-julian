#! /usr/bin/env python3

'''
Overview:

    We hard-code the URL of the MuPDF .tar.gz file that we require. This
    generally points to a particular source release on mupdf.com.

    Default behaviour:

        Building an sdist:
            We download the MuPDF .tar.gz file and embed within the sdist.

        Building PyMuPDF:
            If we are not in an sdist we first download the mupdf .tar.gz file.

            Then we extract and build MuPDF locally, before setuptools builds
            PyMuPDF. So PyMuPDF will always be built with the exact MuPDF
            release that we require.

Environmental variables:

    PYMUPDF_SETUP_DEVENV
        Location of devenv.com on Windows. If unset we search in some
        hard-coded default locations; if that fails we use just 'devenv.com'.

    PYMUPDF_SETUP_MUPDF_BUILD
        If set, overrides location of mupdf when building PyMuPDF:
            Empty string:
                Build PyMuPDF with the system mupdf.
            A string starting with 'git:':
                Use `git clone` to get a mupdf directory. We use the string in
                the git clone command; it must contain the git URL from which
                to clone, and can also contain other `git clone` args, for
                example:
                    PYMUPDF_SETUP_MUPDF_BUILD="git:--branch master https://github.com/ArtifexSoftware/mupdf.git"
            Otherwise:
                Location of mupdf directory.

    PYMUPDF_SETUP_MUPDF_BUILD_TYPE
        Unix only. Controls build type of MuPDF. Supported values are:
            debug
            memento
            release (default)

    PYMUPDF_SETUP_MUPDF_REBUILD
        If '0' we do not build MuPDF - avoids delay if it is known to be up to date.

    PYMUPDF_SETUP_MUPDF_CLEAN
        If '1', we do a clean MuPDF build.

    PYMUPDF_SETUP_MUPDF_TGZ
        If set, overrides location of MuPDF .tar.gz file:
            Empty string:
                Do not download MuPDF .tar.gz file. Sdist's will not contain
                MuPDF.

            A string containing '://':
                The URL from which to download the MuPDF .tar.gz file. Leaf
                must match mupdf-*.tar.gz.

            Otherwise:
                The path of local mupdf git checkout. We put all files in this
                checkout known to git into a local tar archive.

    PYMUPDF_SETUP_REBUILD
        If 0 we do not rebuild mupdfpy. If 1 we always rebuild mupdfpy. If
        unset we rebuild if necessary.

Building MuPDF:
    When building MuPDF, we overwrite the mupdf's include/mupdf/fitz/config.h
    with fitz/_config.h and do a PyMuPDF-specific build.
'''

import os
import textwrap
import pipcl
import platform
import shutil
import subprocess
import sys


_log_prefix = None
def log( text):
    global _log_prefix
    if not _log_prefix:
        p = os.path.abspath( __file__)
        p, p1 = os.path.split( p)
        p, p0 = os.path.split( p)
        _log_prefix = os.path.join( p0, p1)
    print(f'{_log_prefix}: {text}', file=sys.stdout)
    sys.stdout.flush()


g_root = os.path.abspath( f'{__file__}/..')

def _fs_find_in_paths( name, paths=None):
    '''
    Looks for `name` in paths and returns complete path. `paths` is list/tuple
    or colon-separated string; if `None` we use `$PATH`.
    '''
    if paths is None:
        paths = os.environ.get( 'PATH', '')
    if isinstance( paths, str):
        paths = paths.split( ':')
    for path in paths:
        p = f'{path}/{name}'
        if os.path.isfile( p):
            return p

def _fs_remove(path):
    '''
    Removes file or directory, without raising exception if it doesn't exist.

    We assert-fail if the path still exists when we return, in case of
    permission problems etc.
    '''
    try:
        os.remove( path)
    except Exception:
        pass
    shutil.rmtree( path, ignore_errors=1)
    assert not os.path.exists( path)



def _python_compile_flags():
    '''
    Returns compile flags from `python-config --includes`.
    '''
    # We use python-config which appears to
    # work better than pkg-config because
    # it copes with multiple installed
    # python's, e.g. manylinux_2014's
    # /opt/python/cp*-cp*/bin/python*.
    #
    # But... it seems that we should not
    # attempt to specify libpython on the link
    # command. The manylinkux docker containers
    # don't actually contain libpython.so, and
    # it seems that this deliberate. And the
    # link command runs ok.
    #
    python_exe = os.path.realpath( sys.executable)
    python_config = f'{python_exe}-config'
    if not _fs_find_in_paths( python_config):
        default = 'python3-config'
        #log( f'Warning, cannot find {python_config}, using {default=}.')
        python_config = default
    # --cflags gives things like
    # -Wno-unused-result -g etc, so we just use
    # --includes.
    python_flags = subprocess.run(
            f'{python_config} --includes',
            shell=True,
            capture_output=True,
            check=True,
            encoding='utf8',
            ).stdout.strip()
    return python_flags


def _command_lines( command):
    '''
    Process multiline command by running through textwrap.dedent(), removes
    comments (' #' until end of line), removes entirely blank lines.

    Returns list of lines.
    '''
    command = textwrap.dedent( command)
    lines = []
    for line in command.split( '\n'):
        h = line.find( ' #')
        if h >= 0:
            line = line[:h]
        if line.strip():
            lines.append(line.rstrip())
    return lines

def _fs_mtime( filename, default=0):
    '''
    Returns mtime of file, or `default` if error - e.g. doesn't exist.
    '''
    try:
        return os.path.getmtime( filename)
    except OSError:
        return default

def _git_get_branch( directory):
    command = f'cd {directory} && git branch --show-current'
    log( f'Running: {command}')
    p = subprocess.run(
            command,
            shell=True,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            )
    ret = None
    if p.returncode == 0:
        ret = p.stdout.strip()
        log( f'Have found MuPDF git branch: ret={ret!r}')
    return ret



mupdf_tgz = os.path.abspath( f'{__file__}/../mupdf.tgz')

def get_mupdf_tgz():
    '''
    Creates .tgz file containing MuPDF source, for inclusion in an sdist.
    
    What we do depends on environmental variable PYMUPDF_SETUP_MUPDF_TGZ; see
    docs at start of this file for details.

    Returns name of top-level directory within the .tgz file.
    '''
    mupdf_url_or_local = os.environ.get(
            'PYMUPDF_SETUP_MUPDF_TGZ',
            'https://mupdf.com/downloads/archive/mupdf-1.21.0-source.tar.gz',
            )
    log( f'mupdf_url_or_local={mupdf_url_or_local!r}')
    if mupdf_url_or_local == '':
        # No mupdf in sdist.
        log( 'mupdf_url_or_local is empty string so removing any mupdf_tgz={mupdf_tgz}')
        _fs_remove( mupdf_tgz)
        return
    
    if '://' in mupdf_url_or_local:
        # Download from URL into <mupdf_tgz>.
        mupdf_url = mupdf_url_or_local
        mupdf_url_leaf = os.path.basename( mupdf_url)
        leaf = '.tar.gz'
        assert mupdf_url_leaf.endswith(leaf), f'Unrecognised suffix in mupdf_url={mupdf_url!r}'
        mupdf_local = mupdf_url_leaf[ : -len(leaf)] + '/'
        assert mupdf_local.startswith( 'mupdf-')
        log(f'Downloading from: {mupdf_url}')
        _fs_remove( mupdf_url_leaf)
        urllib.request.urlretrieve( mupdf_url, mupdf_url_leaf)
        assert os.path.exists( mupdf_url_leaf)
        tar_check( mupdf_url_leaf, 'r:gz', mupdf_local)
        if mupdf_url_leaf != mupdf_tgz:
            _fs_remove( mupdf_tgz)
            os.rename( mupdf_url_leaf, mupdf_tgz)
        return mupdf_local
    
    else:
        # Create archive <mupdf_tgz> contining local mupdf directory's git
        # files.
        mupdf_local = mupdf_url_or_local
        if not mupdf_local.endswith( '/'):
            mupdf_local += '/'
        assert os.path.isdir( mupdf_local), f'Not a directory: {mupdf_local!r}'
        log( f'Creating .tgz from git files in: {mupdf_local}')
        _fs_remove( mupdf_tgz)
        with tarfile.open( mupdf_tgz, 'w:gz') as f:
            for name in get_gitfiles( mupdf_local, submodules=True):
                path = os.path.join( mupdf_local, name)
                if os.path.isfile( path):
                    f.add( path, f'mupdf/{name}', recursive=False)
        return mupdf_local


def get_mupdf():
    '''
    Downloads and/or extracts mupdf and returns location of mupdf directory.

    Exact behaviour depends on environmental variable
    PYMUPDF_SETUP_MUPDF_BUILD; see docs at start of this file for details.
    '''
    path = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD')
    if path is None:
        # Default.
        raise Exception( f'Using downloaded mupdf not currently supported; set PYMUPDF_SETUP_MUPDF_BUILD.')
        if os.path.exists( mupdf_tgz):
            log( f'mupdf_tgz already exists: {mupdf_tgz}')
        else:
            get_mupdf_tgz()
        path = tar_extract( mupdf_tgz, exists='return')
    
    elif path == '':
        # Use system mupdf.
        log( f'PYMUPDF_SETUP_MUPDF_BUILD="", using system mupdf')
        path = None
    
    else:
        git_prefix = 'git:'
        if path.startswith( git_prefix):
            # Get git clone of mupdf.
            #
            # `mupdf_url_or_local` is taken to be portion of a `git clone` command,
            # for example:
            #
            #   PYMUPDF_SETUP_MUPDF_BUILD="git:--branch master git://git.ghostscript.com/mupdf.git"
            #   PYMUPDF_SETUP_MUPDF_BUILD="git:--branch 1.20.x https://github.com/ArtifexSoftware/mupdf.git"
            #   PYMUPDF_SETUP_MUPDF_BUILD="git:--branch master https://github.com/ArtifexSoftware/mupdf.git"
            #
            # One would usually also set PYMUPDF_SETUP_MUPDF_TGZ= (empty string) to
            # avoid the need to download a .tgz into an sdist.
            #
            command_suffix = path[ len(git_prefix):]
            path = 'mupdf'
            assert not os.path.exists( path), \
                    f'Cannot use git clone because local directory already exists: {path}'
            command = (''
                    + f'git clone'
                    + f' --recursive'
                    #+ f' --single-branch'
                    #+ f' --recurse-submodules'
                    + f' --depth 1'
                    + f' --shallow-submodules'
                    #+ f' --branch {branch}'
                    #+ f' git://git.ghostscript.com/mupdf.git'
                    + f' {command_suffix}'
                    + f' {path}'
                    )
            log( f'Running: {command}')
            subprocess.run( command, shell=True, check=True)

            # Show sha of checkout.
            command = f'cd {path} && git show --pretty=oneline|head -n 1'
            log( f'Running: {command}')
            subprocess.run( command, shell=True, check=False)

        # Use custom mupdf directory.
        log( f'Using custom mupdf directory from $PYMUPDF_SETUP_MUPDF_BUILD: {path}')
        assert os.path.isdir( path), f'$PYMUPDF_SETUP_MUPDF_BUILD is not a directory: {path}'
    
    if path:
        path = os.path.abspath( path)
        if path.endswith( '/'):
            path = path[:-1]
    return path


linux = sys.platform.startswith( 'linux') or 'gnu' in sys.platform
openbsd = sys.platform.startswith( 'openbsd')
freebsd = sys.platform.startswith( 'freebsd')
darwin = sys.platform.startswith( 'darwin')
windows = platform.system() == 'Windows' or platform.system().startswith('CYGWIN')


def build():
    '''
    pipcl.py `build_fn()` callback.
    
    We use $PYMUPDF_SETUP_MUPDF_BUILD and $PYMUPDF_SETUP_MUPDF_BUILD_TYPE in a
    similar way as a normal PyMuPDF build.
    '''
    # Build MuPDF
    #
    if windows:
        mupdf_local, build_dir = build_mupdf_windows()
    else:
        mupdf_local, build_dir = build_mupdf_unix()
    log( f'build(): {build_dir=}')
    
    # Build `extra` module.
    #
    mupdf_dir, path_so, path_so_tail = _build_fitz_extra( build_dir, mupdf_local)
    
    # Generate list of (to, from) items to return to pipcl.
    #
    ret = []
    for p in [
            'fitz/__init__.py',
            'fitz/__main__.py',
            'fitz/extra.py',
            'fitz/fitz.py',
            'fitz/utils.py',
            ]:
        from_ = f'{g_root}/{p}'.replace( '/', os.sep)
        to_ = p.replace( '/', os.sep)
        ret.append( ( from_, to_))
    ret.append( ( path_so, path_so_tail))
    ret.append( ( f'{g_root}/README.md', '$dist-info/README.md'))

    if mupdf_dir:
        # Add MuPDF runtime files.
        log( f'{build_dir=}')
        if windows:
            for leaf in (
                    'mupdf.py',
                    '_mupdf.pyd',
                    'mupdfcpp64.dll',
                    ):
                from_ = f'{build_dir}/{leaf}'
                to_ = f'fitz/{leaf}'
                ret.append( ( from_, to_))
        else:
            for leaf in (
                    'mupdf.py',
                    '_mupdf.so',
                    'libmupdfcpp.so',
                    'libmupdf.so'
                    ):
                from_ = f'{build_dir}/{leaf}'
                to_ = f'fitz/{leaf}'
                ret.append( ( from_, to_))

    for f, t in ret:
        log( f'build(): {f} => {t}')
    return ret


def build_mupdf_windows():
    mupdf_local = get_mupdf()
    
    assert mupdf_local
    if mupdf_local:
        build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'release')
        assert build_type in ('debug', 'memento', 'release'), f'{unix_build_type=}'

        python_version = '.'.join(platform.python_version_tuple()[:2])
        windows_build_tail = f'build\\shared-{build_type}-x64-py{python_version}'
        windows_build_dir = f'{mupdf_local}\\{windows_build_tail}'
        #log( f'Building mupdf.')
        shutil.copy2( f'{g_root}/mupdf_config.h', f'{mupdf_local}/include/mupdf/fitz/config.h')
        vs = pipcl.WindowsVS()
        command = f'cd {mupdf_local}'
        command += F' && {sys.executable} ./scripts/mupdfwrap.py -d {windows_build_tail} -b --refcheck-if "#if 1" --devenv "{vs.devenv}" all'
        if os.environ.get( 'PYMUPDF_SETUP_MUPDF_REBUILD') == '0':
            log( f'PYMUPDF_SETUP_MUPDF_REBUILD is "0" so not building MuPDF; would have run: {command}')
        else:
            log( f'Building MuPDF by running: {command}')
            subprocess.run( command, shell=True, check=True)
            log( f'Finished building mupdf.')
    
    return mupdf_local, windows_build_dir


def build_mupdf_unix():
    '''
    Builds MuPDF and returns `(mupdf_local, unix_build_dir)`:
        mupdf_local:
            Path of MuPDF directory.
        unix_build_dir:
            Absolute path of build directory within MuPDF, e.g.
            ".../mupdf/build/mupdfpy-shared-release".
    
    If we are using the system MuPDF, returns `(None, None)`.
    '''
    mupdf_local = get_mupdf()
    
    if mupdf_local:
        #log( f'Building mupdf.')
        shutil.copy2( f'{g_root}/mupdf_config.h', f'{mupdf_local}/include/mupdf/fitz/config.h')
    
        flags = 'HAVE_X11=no HAVE_GLFW=no HAVE_GLUT=no HAVE_LEPTONICA=yes HAVE_TESSERACT=yes'
        flags += ' verbose=yes'
        env = ''
        if openbsd or freebsd:
            env += ' CXX=clang++'

        unix_build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'release')
        assert unix_build_type in ('debug', 'memento', 'release'), f'{unix_build_type=}'

        # Add extra flags for MacOS cross-compilation, where ARCHFLAGS can be
        # '-arch arm64'.
        #
        archflags = os.environ.get( 'ARCHFLAGS')
        if archflags:
            flags += f' XCFLAGS="{archflags}" XLIBS="{archflags}"'

        # We specify a build directory path containing 'mupdfpy' so that we
        # coexist with non-mupdfpy builds (because mupdfpy builds have a
        # different config.h).
        #
        # We also append further text to try to allow different builds to
        # work if they reuse the mupdf directory.
        #
        # Using platform.machine() (e.g. 'amd64') ensures that different
        # builds of mupdf on a shared filesystem can coexist. Using
        # $_PYTHON_HOST_PLATFORM allows cross-compiled cibuildwheel builds
        # to coexist, e.g. on github.
        #
        build_prefix = f'mupdfpy-{platform.machine()}-'
        build_prefix_extra = os.environ.get( '_PYTHON_HOST_PLATFORM')
        if build_prefix_extra:
            build_prefix += f'{build_prefix_extra}-'
        build_prefix += 'shared-'
        unix_build_dir = f'{mupdf_local}/build/{build_prefix}{unix_build_type}'

        # Unlike PyMuPDF we need MuPDF's Python bindings, so we build MuPDF
        # with `mupdf/scripts/mupdfwrap.py` instead of running `make`.
        #
        command = f'cd {mupdf_local} && {env} {sys.executable} ./scripts/mupdfwrap.py -d build/{build_prefix}{unix_build_type} -b all'
        command += f' && echo {unix_build_dir}:'
        command += f' && ls -l {unix_build_dir}'
        
        if os.environ.get( 'PYMUPDF_SETUP_MUPDF_REBUILD') == '0':
            log( f'PYMUPDF_SETUP_MUPDF_REBUILD is "0" so not building MuPDF; would have run: {command}')
        else:
            log( f'Building MuPDF by running: {command}')
            subprocess.run( command, shell=True, check=True)
            log( f'Finished building mupdf.')
    else:
        # Use installed MuPDF.
        log( f'Using system mupdf.')
        unix_build_dir = None
    
    return mupdf_local, unix_build_dir


def _build_fitz_extra( build_dir, mupdf_local):
    '''
    Builds Python extension module `extra`.
    '''
    mupdf_dir = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD')
    if mupdf_dir:
        includes = (f'{mupdf_dir}/platform/c++/include', f'{mupdf_dir}/include')
    else:
        includes = None
    if windows:
        defines = ('FZ_DLL_CLIENT',)
        python_version = ''.join(platform.python_version_tuple()[:2])
        libpaths = (
                f'{mupdf_local}\\platform\\win32\\x64\\Release',
                f'{mupdf_local}\\platform\\win32\\x64\\ReleaseTesseract',
                )
        libs = 'mupdfcpp64.lib'
        compiler_extra = ''
        linker_extra = ''
        optimise = True
        debug = False
    else:
        build_dir_flags = os.path.basename( build_dir).split( '-')
        defines = None,
        libpaths = (build_dir,)
        libs = ('mupdfcpp', 'mupdf')
        compiler_extra = '-Wall -Wno-deprecated-declarations -Wno-unused-const-variable'
        linker_extra = ''
        optimise = 'release' in build_dir_flags
        debug = 'debug' in build_dir_flags
    force = os.environ.get('PYMUPDF_SETUP_REBUILD')
    
    path_so_leaf = pipcl.build_extension(
            'extra',
            f'{g_root}/extra.i',
            f'{g_root}/fitz',
            includes = includes,
            defines = defines,
            libpaths = libpaths,
            libs = libs,
            compiler_extra = compiler_extra,
            linker_extra = linker_extra,
            force = force,
            optimise = optimise,
            debug = debug,
            )
    path_so_tail = f'fitz/{path_so_leaf}'
    path_so = f'{g_root}/{path_so_tail}'

    return mupdf_dir, path_so, path_so_tail
    

def sdist():
    '''
    We are not currently able to embed a .tgz MuPDF release in the sdist, so we
    do not look at $PYMUPDF_SETUP_MUPDF_TGZ.
    '''
    return pipcl.git_items( g_root)


classifier = [
        #"Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Operating System :: MacOS",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: C",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: Implementation :: CPython",
        "Topic :: Utilities",
        "Topic :: Multimedia :: Graphics",
        "Topic :: Software Development :: Libraries",
        ]

with open( f'{g_root}/README.md', encoding="utf-8") as f:
    readme = f.read()

p = pipcl.Package(
        'mupdfpy',
        '1.21.1',
        summary="Rebased PyMuPDF bindings for the PDF toolkit and renderer MuPDF",
        description=readme,
        description_content_type="text/markdown",
        classifier=classifier,
        author="Artifex",
        author_email="support@artifex.com",
        requires_python=">=3.7",
        license="GNU AFFERO GPL 3.0",
        #project_url=[
        #        ("Documentation", "https://pymupdf.readthedocs.io/"),
        #        ("Source", "https://github.com/pymupdf/pymupdf"),
        #        ("Tracker", "https://github.com/pymupdf/PyMuPDF/issues"),
        #        ("Changelog", "https://pymupdf.readthedocs.io/en/latest/changes.html"),
        #        ],
        fn_build=build,
        fn_sdist=sdist,
        )

build_wheel = p.build_wheel
build_sdist = p.build_sdist


import sys
if __name__ == '__main__':
    p.handle_argv(sys.argv)
