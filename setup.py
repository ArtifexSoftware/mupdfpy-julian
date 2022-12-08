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

def remove(path):
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
        raise Exception( f'Using downloaded mupdf not currently supported; set PYMUPDF_SETUP_MUPDF_BUILD.')
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
    log( f'{mupdf_local=}')
    if mupdf_local:
        if not mupdf_local.endswith( '/'):
            mupdf_local += '/'
    
    unix_build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'shared-release')
    assert unix_build_type.startswith( ( 'shared-', 'fpic-')), f'PYMUPDF_SETUP_MUPDF_BUILD_TYPE must start with `shared-` or `fpic-`'
    
    if mupdf_local:
        log( f'Building mupdf.')
        shutil.copy2( f'{g_root}/mupdf_config.h', f'{mupdf_local}include/mupdf/fitz/config.h')
    
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
            
            unix_build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'release')
            assert unix_build_type in ('debug', 'memento', 'release')
            flags += f' build={unix_build_type}'
            
            # This is for MacOS cross-compilation, where ARCHFLAGS can be
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
            unix_build_dir = f'{mupdf_local}build/{build_prefix}{unix_build_type}'
            
            command = f'cd {mupdf_local} && {env} ./scripts/mupdfwrap.py -d build/{build_prefix}{unix_build_type} -b all'
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
    
    
    # Build fitz.extra module.
    #os.makedirs( 'build', exist_ok=True)
    path_i = f'{g_root}/extra.i'
    path_cpp = f'{g_root}/fitz/extra.cpp'
    path_so = f'{g_root}/fitz/_extra.so'
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
    else:
        # Use system mupdf.
        include1 = ''
        include2 = ''
        linkdir = ''
    
    # Run swig.
    if 0 or _fs_mtime( path_i, 0) >= _fs_mtime( path_cpp, 0):
        _run( f'''
                swig
                    -Wall
                    -c++
                    -python
                    -module extra
                    -outdir {g_root}/fitz
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
                    -Wno-unused-const-variable
                    {path_cpp}
                    -o {path_so}
                    -L {mupdf_dir}/build/{unix_build_type}
                    {libs_text}
                    -Wl,-rpath='$ORIGIN',-z,origin
                ''')
    else:
        log( f'Not running c++ because mtime:{path_cpp} < mtime:{path_so}')
    
    ret = []
    for p in [
            'fitz/__init__.py',
            'fitz/__main__.py',
            'fitz/_extra.so',
            'fitz/extra.py',
            'fitz/fitz.py',
            'fitz/utils.py',
            ]:
        from_ = f'{g_root}/{p}'
        to_ = p
        ret.append( ( from_, to_))
    ret.append( ( f'{g_root}/test.py', f'fitz/test.py'))
    ret.append( ( f'{g_root}/README.md', '$dist-info/README.md'))

    # This doesn't yet work. So need to set PYTHONPATH and LD_LIBRARY_PATH so
    # that we can import mupdf python API.
    if mupdf_dir:
        # Add MuPDF runtime files.
        
        for leaf in (
                'mupdf.py',
                '_mupdf.so',
                'libmupdfcpp.so',
                'libmupdf.so'
                ):
            from_ = f'{mupdf_dir}/build/{unix_build_type}/{leaf}'
            to_ = f'fitz/{leaf}'
            #to_ = f'{leaf}'
            #to_ = to_.replace( '.so', '.cpython-39-x86_64-linux-gnu.so')
            ret.append( ( from_, to_))

    return ret

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
        'fitz',
        '1.21.0',
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
