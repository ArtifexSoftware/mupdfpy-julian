#! /usr/bin/env python3

import os
import textwrap
import pipcl
import platform
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
    print(f'{_log_prefix}: {text}', file=sys.stderr)
    sys.stderr.flush()


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


def _run( command):
    command = textwrap.dedent( command).strip().replace( '\n', " \\\n")
    log( f'Running: {command}')
    sys.stdout.flush()
    subprocess.run( command, shell=True, check=True)

def _fs_mtime( filename, default=0):
    '''
    Returns mtime of file, or `default` if error - e.g. doesn't exist.
    '''
    try:
        return os.path.getmtime( filename)
    except OSError:
        return default


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
        remove( mupdf_tgz)
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
        remove( mupdf_url_leaf)
        urllib.request.urlretrieve( mupdf_url, mupdf_url_leaf)
        assert os.path.exists( mupdf_url_leaf)
        tar_check( mupdf_url_leaf, 'r:gz', mupdf_local)
        if mupdf_url_leaf != mupdf_tgz:
            remove( mupdf_tgz)
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
        remove( mupdf_tgz)
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
        if os.path.exists( mupdf_tgz):
            log( f'mupdf_tgz already exists: {mupdf_tgz}')
        else:
            get_mupdf_tgz()
        return tar_extract( mupdf_tgz, exists='return')
    
    elif path == '':
        # Use system mupdf.
        log( f'PYMUPDF_SETUP_MUPDF_BUILD="", using system mupdf')
        return None
    
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
    
    if 1:
        # Use custom mupdf directory.
        log( f'Using custom mupdf directory from $PYMUPDF_SETUP_MUPDF_BUILD: {path}')
        assert os.path.isdir( path), f'$PYMUPDF_SETUP_MUPDF_BUILD is not a directory: {path}'
        return path


def build():
    '''
    We use $PYMUPDF_SETUP_MUPDF_BUILD and $PYMUPDF_SETUP_MUPDF_BUILD_TYPE
    in a similar way as a normal PyMuPDF build, except that
    PYMUPDF_SETUP_MUPDF_BUILD_TYPE must start with `shared-` or `fpic-`.
    '''
    # Build mupdf.
    
    mupdf_local = get_mupdf()
    if mupdf_local:
        if not mupdf_local.endswith( '/'):
            mupdf_local += '/'
    
    unix_build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'shared-release')
    assert unix_build_type.startswith( ( 'shared-', 'fpic-')), f'PYMUPDF_SETUP_MUPDF_BUILD_TYPE must start with `shared-` or `fpic-`'
    
    if mupdf_local:
        log( f'Building mupdf.')
        #shutil.copy2( 'fitz/_config.h', f'{mupdf_local}include/mupdf/fitz/config.h')
    
        if platform.system() == 'Windows' or platform.system().startswith('CYGWIN'):
            # Windows build.
            devenv = os.environ.get('PYMUPDF_SETUP_DEVENV')
            if not devenv:
                # Search for devenv in some known locations.
                devenv = glob.glob('C:/Program Files (x86)/Microsoft Visual Studio/2019/*/Common7/IDE/devenv.com')
                if devenv:
                    devenv = devenv[0]
            if not devenv:
                devenv = 'devenv.com'
                log( f'Cannot find devenv.com in default locations, using: {devenv!r}')
            windows_config = 'Win32' if word_size()==32 else 'x64'
            command = (
                    f'cd {mupdf_local}&&'
                    f'"{devenv}"'
                    f' platform/win32/mupdf.sln'
                    f' /Build "ReleaseTesseract|{windows_config}"'
                    f' /Project mupdf'
                    )
        else:
            # Unix build.
            flags = 'HAVE_X11=no HAVE_GLFW=no HAVE_GLUT=no HAVE_LEPTONICA=yes HAVE_TESSERACT=yes'
            flags += ' verbose=yes'
            env = ''
            make = 'make'
            if os.uname()[0] == 'Linux':
                env += ' CFLAGS="-fPIC"'
            if os.uname()[0] in ('OpenBSD', 'FreeBSD'):
                make = 'gmake'
                env += ' CFLAGS="-fPIC" CXX=clang++'
            command = f'cd {mupdf_local} && {env} ./scripts/mupdfwrap.py -d build/{unix_build_type} -b all'
            command += f' && echo "build/{unix_build_type}:"'
            command += f' && ls -l build/{unix_build_type}'
        
        log( f'Building MuPDF by running: {command}')
        subprocess.run( command, shell=True, check=True)
        log( f'Finished building mupdf.')
    else:
        # Use installed MuPDF.
        log( f'Using system mupdf.')
    
    
    # Build fitz.extra module.
    #os.makedirs( 'build', exist_ok=True)
    path_i = 'extra.i'
    path_cpp = 'fitz/extra.cpp'
    path_so = 'fitz/_extra.so'
    unix_build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'shared-release')
    cpp_flags = '-Wall'
    #cpp_flags += ' -Wl,-O1 -Wl,-Bsymbolic-functions -Wl,-z,relro -fwrapv'
    unix_build_type_flags = unix_build_type.split( '-')
    if 'release' in unix_build_type_flags:
        cpp_flags += ' -g -O2 -DNDEBUG'
    elif 'debug' in unix_build_type_flags or 'memento' in unix_build_type_flags:
        cpp_flags += ' -g'
        if unix_build_type == 'memento':
            cpp_flags += ' -DMEMENTO'
    else:
        assert 0, f'Unrecognised PYMUPDF_SETUP_MUPDF_BUILD_TYPE: {unix_build_type}'
    
    #cpp_flags += ' -DSWIGINTERN='
    
    mupdf_dir = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD')
    if mupdf_dir:
        include1 = f'-I{mupdf_dir}/platform/c++/include'
        include2 = f'-I{mupdf_dir}/include'
        linkdir = f'-L {mupdf_dir}/build/{unix_build_type}'
    elif mupdf_dir == '':
        include1 = ''
        include2 = ''
        linkdir = ''
    else:
        assert 0, f'No support yet for downloading mupdf'
    
    # Run swig.
    if 0 or _fs_mtime( path_i, 0) >= _fs_mtime( path_cpp, 0):
        _run( f'''
                swig
                    -Wall
                    -c++
                    -python
                    -module extra
                    -outdir fitz
                    -o {path_cpp}
                    {include1}
                    {include2}
                    {path_i}
                '''
                )
    else:
        log( f'Not running swig because mtime:{path_i} < mtime:{path_cpp}')
    
    python_flags = _python_compile_flags()

    # Compile and link swig-generated code.
    #
    # Fun fact - on Linux, if the -L and -l options are before '{path_cpp} -o
    # {path_so}' they seem to be ignored...
    #
    if 0 or _fs_mtime( path_cpp, 0) >= _fs_mtime( path_so, 0):
        libs = list()
        libs.append( 'mupdfcpp')
        if unix_build_type.startswith( 'shared-'):
            libs.append( 'mupdf')
        libs_text = ''
        for lib in libs:
            libs_text += f' -l {lib}'
        _run( f'''
                c++
                    -fPIC
                    -shared
                    {cpp_flags}
                    {python_flags}
                    {include1}
                    {include2}
                    -Wno-deprecated-declarations
                    {path_cpp}
                    -o {path_so}
                    -L {mupdf_dir}/build/{unix_build_type}
                    {libs_text}
                ''')
    else:
        log( f'Not running c++ because mtime:{path_cpp} < mtime:{path_so}')
    
    return [
            'README.md',
            'fitz/__init__.py',
            'fitz/__main__.py',
            'fitz/_extra.so',
            'fitz/extra.py',
            'fitz/fitz.py',
            'fitz/utils.py',
            'test.py',
            ]


def sdist():
    '''
    We are not currently able to embed a .tgz MuPDF release in the sdist, so we
    do not look at $PYMUPDF_SETUP_MUPDF_TGZ.
    '''
    return pipcl.git_items( g_root)


p = pipcl.Package(
        'fitz',
        '0.0.0',
        fn_build=build,
        fn_sdist=sdist,
        )

build_wheel = p.build_wheel
build_sdist = p.build_sdist


import sys
if __name__ == '__main__':
    p.handle_argv(sys.argv)
