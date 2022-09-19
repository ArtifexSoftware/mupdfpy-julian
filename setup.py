#! /usr/bin/env python3

import os
import textwrap
import pipcl
import subprocess


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
        #print( f'Warning, cannot find {python_config}, using {default=}.')
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
    print( f'Running: {command}')
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


def build():
    '''
    We use $PYMUPDF_SETUP_MUPDF_BUILD and $PYMUPDF_SETUP_MUPDF_BUILD_TYPE
    in a similar way as a normal PyMuPDF build, except that we require that
    $PYMUPDF_SETUP_MUPDF_BUILD is set - we are not currently able to download
    and build a hard-coded MuPDF release.
    '''
    # Build fitz.extra module.
    #os.makedirs( 'build', exist_ok=True)
    path_i = 'extra.i'
    path_cpp = 'fitz/extra.cpp'
    path_so = 'fitz/_extra.so'
    unix_build_type = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD_TYPE', 'release')
    cpp_flags = '-Wall'
    #cpp_flags += ' -Wl,-O1 -Wl,-Bsymbolic-functions -Wl,-z,relro -fwrapv'
    if unix_build_type == 'release':
        cpp_flags += ' -g -O2 -DNDEBUG'
    elif unix_build_type == 'debug':
        cpp_flags += ' -g'
    else:
        assert 0
    
    mupdf_dir = os.environ.get( 'PYMUPDF_SETUP_MUPDF_BUILD')
    if mupdf_dir:
        include1 = f'-I{mupdf_dir}/platform/c++/include'
        include2 = f'-I{mupdf_dir}/include'
        linkdir = f'-L {mupdf_dir}/build/shared-{unix_build_type}'
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
        print( f'Not running swig because mtime:{path_i} < mtime:{path_cpp}')
    
    python_flags = _python_compile_flags()

    # Compile and link swig-generated code.
    #
    # Fun fact - on Linux, if the -L and -l options are before '{path_cpp} -o
    # {path_so}' they seem to be ignored...
    #
    if 0 or _fs_mtime( path_cpp, 0) >= _fs_mtime( path_so, 0):
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
                    {linkdir}
                    -l mupdfcpp
                    -l mupdf
                ''')
    else:
        print( f'Not running c++ because mtime:{path_cpp} < mtime:{path_so}')
    
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
