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

    PYMUPDF_SETUP_COMPOUND
        If set, should be location of PyMuPDF checkout, and we include both
        PyMuPDF and mupdfpy modules in the generated package.

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

    PYMUPDF_SETUP_MUPDF_VS_UPGRADE
        If '1' we run mupdf `scripts/mupdfwrap.py` with `--vs-upgrade 1` to
        help Windows builds work with Visual Studio versions newer than 2019.

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

    PYMUPDF_SETUP_MUPDF_OVERWRITE_CONFIG
        If '0' we do not overwrite MuPDF's include/mupdf/fitz/config.h with
        PyMuPDF's own configuration file, before building MuPDF.
    
    PYMUPDF_SETUP_REBUILD
        If 0 we do not rebuild mupdfpy. If 1 we always rebuild mupdfpy. If
        unset we rebuild if necessary.

    WDEV_VS_YEAR
        If set, we use as Visual Studio year, for example '2019' or '2022'.

    WDEV_VS_GRADE
        If set, we use as Visual Studio grade, for example 'Community' or
        'Professional' or 'Enterprise'.
'''

import os
import textwrap
import time
import pipcl
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import zipfile


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

g_compound = os.environ.get('PYMUPDF_SETUP_COMPOUND')

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

def remove(path):
    '''
    Removes file or directory, without raising exception if it doesn't exist.

    We assert-fail if the path still exists when we return, in case of
    permission problems etc.
    '''
    # First try deleting `path` as a file.
    try:
        os.remove( path)
    except Exception as e:
        pass
    
    if os.path.exists(path):
        # Try deleting `path` as a directory. Need to use
        # shutil.rmtree() callback to handle permission problems; see:
        # https://docs.python.org/3/library/shutil.html#rmtree-example
        #
        def error_fn(fn, path, excinfo):
            # Clear the readonly bit and reattempt the removal.
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree( path, onerror=error_fn)
    
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


def tar_check(path, mode='r:gz', prefix=None, remove=False):
    '''
    Checks items in tar file have same <top-directory>, or <prefix> if not None.

    We fail if items in tar file have different top-level directory names.

    path:
        The tar file.
    mode:
        As tarfile.open().
    prefix:
        If not None, we fail if tar file's <top-directory> is not <prefix>.
    
    Returns the directory name (which will be <prefix> if not None).
    '''
    with tarfile.open( path, mode) as t:
        items = t.getnames()
        assert items
        item = items[0]
        assert not item.startswith('./') and not item.startswith('../')
        s = item.find('/')
        if s == -1:
            prefix_actual = item + '/'
        else:
            prefix_actual = item[:s+1]
        if prefix:
            assert prefix == prefix_actual, f'prefix={prefix} prefix_actual={prefix_actual}'
        for item in items[1:]:
            assert item.startswith( prefix_actual), f'prefix_actual={prefix_actual!r} != item={item!r}'
    return prefix_actual


def tar_extract(path, mode='r:gz', prefix=None, exists='raise'):
    '''
    Extracts tar file.
    
    We fail if items in tar file have different <top-directory>.

    path:
        The tar file.
    mode:
        As tarfile.open().
    prefix:
        If not None, we fail if tar file's <top-directory> is not <prefix>.
    exists:
        What to do if <top-directory> already exists:
            'raise': raise exception.
            'remove': remove existing file/directory before extracting.
            'return': return without extracting.
    
    Returns the directory name (which will be <prefix> if not None, with '/'
    appended if not already present).
    '''
    prefix_actual = tar_check( path, mode, prefix)
    if os.path.exists( prefix_actual):
        if exists == 'raise':
            raise Exception( f'Path already exists: {prefix_actual!r}')
        elif exists == 'remove':
            remove( prefix_actual)
        elif exists == 'return':
            log( f'Not extracting {path} because already exists: {prefix_actual}')
            return prefix_actual
        else:
            assert 0, f'Unrecognised exists={exists!r}'
    assert not os.path.exists( prefix_actual), f'Path already exists: {prefix_actual}'
    log( f'Extracting {path}')
    with tarfile.open( path, mode) as t:
        t.extractall()
    return prefix_actual



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
            'https://mupdf.com/downloads/archive/mupdf-1.22.0-source.tar.gz',
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
        mupdf_local = mupdf_url_leaf[ : -len(leaf)]
        assert mupdf_local.startswith( 'mupdf-')
        log(f'Downloading from: {mupdf_url}')
        _fs_remove( mupdf_url_leaf)
        urllib.request.urlretrieve( mupdf_url, mupdf_url_leaf)
        assert os.path.exists( mupdf_url_leaf)
        tar_check( mupdf_url_leaf, 'r:gz', f'{mupdf_local}/')
        if mupdf_url_leaf != mupdf_tgz:
            _fs_remove( mupdf_tgz)
            os.rename( mupdf_url_leaf, mupdf_tgz)
        return mupdf_local
    
    else:
        # Create archive <mupdf_tgz> contining local mupdf directory's git
        # files.
        mupdf_local = mupdf_url_or_local
        if mupdf_local.endswith( '/'):
            mupdf_local = mupdf_local[:-1]
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
            
            # Remove any existing directory to avoid the clone failing. (We
            # could assume any existing directory is a git checkout, and do
            # `git pull` or similar, but that's complicated and fragile.)
            #
            remove(path)
            
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
    mupdf_local = get_mupdf()

    env_extra = dict()
    
    if mupdf_local:
        from_ = f'{g_root}/src/mupdf_config.h'
        to_ =f'{mupdf_local}/include/mupdf/fitz/config.h'
        if os.environ.get('PYMUPDF_SETUP_MUPDF_OVERWRITE_CONFIG') == '0':
            # Use MuPDF default config.
            log( f'Not copying {from_} to {to_}.')
        else:
            # Use our special config in MuPDF.
            log( f'Copying {from_} to {to_}.')
            shutil.copy2( from_, to_)
            # Tell the MuPDF build to exclude large unused font files such as
            # resources/fonts/han/SourceHanSerif-Regular.ttc.
            env_extra[ 'XCFLAGS'] ='-DTOFU_CJK_EXT='
        s = os.stat( f'{to_}')
        log( f'{to_}: {s} mtime={time.strftime("%F-%T", time.gmtime(s.st_mtime))}')
    
    if windows:
        mupdf_build_dir = build_mupdf_windows( mupdf_local, env_extra)
    else:
        mupdf_build_dir = build_mupdf_unix( mupdf_local, env_extra)
    log( f'build(): {mupdf_build_dir=}')
    
    # Build `extra` module and PyMuPDF `fitz` module.
    #
    p = _build_fitz_extra( mupdf_local, mupdf_build_dir)
    if g_compound:
        to_dir = 'fitz_new'
        path_so_leaf, path_so_leaf2 = p
    else:
        to_dir = 'fitz'
        path_so_leaf = p
    
    # Generate list of (from. to) items to return to pipcl.
    #
    
    ret = []
    for p in [
            '__init__.py',
            '__main__.py',
            'extra.py',
            'fitz.py',
            'utils.py',
            path_so_leaf,
            ]:
        from_ = f'{g_root}/src/{p}'
        to_ = f'{to_dir}/{p}'
        ret.append( ( from_, to_))
    ret.append( ( f'{g_root}/README.md', '$dist-info/README.md'))

    if mupdf_local:
        # Add (from, to) items for MuPDF runtime files.
        log( f'{mupdf_build_dir=}')
        if windows:
            leafs = (
                    'mupdf.py',
                    '_mupdf.pyd',
                    'mupdfcpp64.dll',
                    )
        else:
            leafs = (
                    'mupdf.py',
                    '_mupdf.so',
                    'libmupdfcpp.so',
                    'libmupdf.so',
                    )
        for leaf in leafs:
            from_ = f'{mupdf_build_dir}/{leaf}'
            to_ = f'{to_dir}/{leaf}'
            ret.append( ( from_, to_))

    if g_compound:
        # Add PyMuPDF files.
        to_dir = 'fitz'
        for p in [
                '__init__.py',
                '__main__.py',
                'fitz.py',
                'utils.py',
                path_so_leaf2,
                ]:
            from_ = f'{g_compound}/fitz/{p}'
            to_ = f'{to_dir}/{p}'
            ret.append( ( from_, to_))
        # Add mupdf shared library next to `path_so_leaf2` so it will be found
        # at runtime. Would prefer to embed a softlink to mupdfpy's file but
        # wheels do not seem to support them.
        leaf = 'mupdfcpp64.dll' if windows else 'libmupdf.so'
        ret.append( ( f'{mupdf_build_dir}/{leaf}', f'{to_dir}/{leaf}'))

    for f, t in ret:
        log( f'build(): {f} => {t}')
    return ret

def env_add(env, name, value, sep=' '):
    v = env.get(name)
    env[ name] =  f'{v}{sep}{value}' if v else value

def build_mupdf_windows( mupdf_local, env):
    
    assert mupdf_local
    build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'release')
    assert build_type in ('debug', 'memento', 'release'), f'{unix_build_type=}'

    python_version = '.'.join(platform.python_version_tuple()[:2])
    windows_build_tail = f'build\\shared-{build_type}-x64-py{python_version}'
    windows_build_dir = f'{mupdf_local}\\{windows_build_tail}'
    #log( f'Building mupdf.')
    vs = pipcl.wdev.WindowsVS()
    command = f'cd {mupdf_local} && {sys.executable} ./scripts/mupdfwrap.py'
    if os.environ.get('PYMUPDF_SETUP_MUPDF_VS_UPGRADE') == '1':
        command += ' --vs-upgrade 1'
    command += f' -d {windows_build_tail} -b --refcheck-if "#if 1" --devenv "{vs.devenv}" all'
    env2 = os.environ.copy()
    env2.update(env)
    if os.environ.get( 'PYMUPDF_SETUP_MUPDF_REBUILD') == '0':
        log( f'PYMUPDF_SETUP_MUPDF_REBUILD is "0" so not building MuPDF; would have run with {env}={env2!r}: {command}')
    else:
        log( f'Building MuPDF by running with {env}={env2!r}: {command}')
        subprocess.run( command, shell=True, check=True, env=env2)
        log( f'Finished building mupdf.')
    
    return windows_build_dir


def build_mupdf_unix( mupdf_local, env):
    '''
    Builds MuPDF and returns `unix_build_dir`, the absolute path of build
    directory within MuPDF, e.g. `.../mupdf/build/mupdfpy-shared-release`.

    Args:
        mupdf_local:
            Path of MuPDF directory.
    
    If we are using the system MuPDF, returns `None`.
    '''    
    if not mupdf_local:
        log( f'Using system mupdf.')
        return None

    #log( f'Building mupdf.')
    shutil.copy2( f'{g_root}/src/mupdf_config.h', f'{mupdf_local}/include/mupdf/fitz/config.h')

    flags = 'HAVE_X11=no HAVE_GLFW=no HAVE_GLUT=no HAVE_LEPTONICA=yes HAVE_TESSERACT=yes'
    flags += ' verbose=yes'
    env = env.copy()
    if openbsd or freebsd:
        env_add(env, 'CXX', 'clang++', ' ')

    unix_build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'release')
    assert unix_build_type in ('debug', 'memento', 'release'), f'{unix_build_type=}'

    # Add extra flags for MacOS cross-compilation, where ARCHFLAGS can be
    # '-arch arm64'.
    #
    archflags = os.environ.get( 'ARCHFLAGS')
    if archflags:
        env_add(env, 'XCFLAGS', archflags)
        env_add(env, 'XLIBS', archflags)

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
    env_string = ''
    for n, v in env.items():
        env_string += f' {n}={shlex.quote(v)}'
    command = f'cd {mupdf_local} &&{env_string} {sys.executable} ./scripts/mupdfwrap.py -d build/{build_prefix}{unix_build_type} -b all'
    command += f' && echo {unix_build_dir}:'
    command += f' && ls -l {unix_build_dir}'

    if os.environ.get( 'PYMUPDF_SETUP_MUPDF_REBUILD') == '0':
        log( f'PYMUPDF_SETUP_MUPDF_REBUILD is "0" so not building MuPDF; would have run: {command}')
    else:
        log( f'Building MuPDF by running: {command}')
        subprocess.run( command, shell=True, check=True)
        log( f'Finished building mupdf.')
    
    return unix_build_dir


def _build_fitz_extra( mupdf_local, mupdf_build_dir):
    '''
    Builds Python extension module `extra`.
    '''
    if mupdf_local:
        includes = (f'{mupdf_local}/platform/c++/include', f'{mupdf_local}/include')
    else:
        includes = None
    if windows:
        defines = ('FZ_DLL_CLIENT',)
        #python_version = ''.join(platform.python_version_tuple()[:2])
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
        mupdf_build_dir_flags = os.path.basename( mupdf_build_dir).split( '-')
        defines = None,
        libpaths = (mupdf_build_dir,)
        libs = ('mupdfcpp', 'mupdf')
        compiler_extra = '-Wall -Wno-deprecated-declarations -Wno-unused-const-variable'
        linker_extra = ''
        optimise = 'release' in mupdf_build_dir_flags
        debug = 'debug' in mupdf_build_dir_flags
    force = os.environ.get('PYMUPDF_SETUP_REBUILD')
    
    path_so_leaf = pipcl.build_extension(
            name = 'extra',
            path_i = f'{g_root}/src/extra.i',
            outdir = f'{g_root}/src',
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
    
    if not g_compound:
        return path_so_leaf
    
    # Build PyMuPDF.
    log('Building PyMuPDF')
    if mupdf_local:
        includes = (
                f'{mupdf_local}/include',
                f'{mupdf_local}/include/mupdf',
                f'{mupdf_local}/thirdparty/freetype/include',
                )
    else:
        includes = None
    libs = 'mupdfcpp64.lib' if windows else ('mupdf',)
    path_so_leaf2 = pipcl.build_extension(
            name = 'fitz',
            path_i = f'{g_compound}/fitz/fitz.i',
            outdir = f'{g_compound}/fitz',
            includes = includes,
            defines = defines,
            libpaths = libpaths,
            libs = libs,
            compiler_extra = compiler_extra,
            linker_extra = linker_extra,
            force = force,
            optimise = optimise,
            debug = debug,
            cpp = False,
            )

    return path_so_leaf, path_so_leaf2
    

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
        'PyMuPDF' if g_compound else 'mupdfpy',
        '1.22.3',
        summary="Rebased PyMuPDF bindings for the PDF toolkit and renderer MuPDF",
        description=readme,
        description_content_type="text/markdown",
        classifier=classifier,
        author="Artifex",
        author_email="support@artifex.com",
        requires_python=">=3.7",
        license="GNU AFFERO GPL 3.0",
        project_url=[
                ("Documentation", "https://pymupdf.readthedocs.io/"),
                ("Source", "https://github.com/pymupdf/pymupdf"),
                ("Tracker", "https://github.com/pymupdf/PyMuPDF/issues"),
                ("Changelog", "https://pymupdf.readthedocs.io/en/latest/changes.html"),
                ],
        fn_build=build,
        fn_sdist=sdist,
        
        # 30MB: 9 ZIP_DEFLATED
        # 28MB: 9 ZIP_BZIP2
        # 23MB: 9 ZIP_LZMA
        wheel_compression = zipfile.ZIP_LZMA,
        wheel_compresslevel = 9,
        )


build_wheel = p.build_wheel
build_sdist = p.build_sdist


import sys
if __name__ == '__main__':
    p.handle_argv(sys.argv)
