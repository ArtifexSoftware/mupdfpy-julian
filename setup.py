#! /usr/bin/env python3

import os
import textwrap
import pipcl
import subprocess


def fs_find_in_paths( name, paths=None):
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


def build():
    os.makedirs( 'build', exist_ok=True)
    command = textwrap.dedent(f'''
            swig
            -Wall
            -c++
            -python
            -module fitz_extra
            -outdir build
            -o build/fitz_extra.cpp
            -I../mupdf/platform/c++/include
            -I../mupdf/include
            extra.i
            '''
            ).strip().replace( '\n', " ")
    subprocess.run( command, shell=True, check=True)
    
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
    if not fs_find_in_paths( python_config):
        default = 'python3-config'
        print( f'Warning, cannot find {python_config}, using {default=}.')
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
            ).stdout

    command = textwrap.dedent(f'''
            c++
            -fPIC
            -shared
            -I ../mupdf/platform/c++/include
            -I ../mupdf/include
            {python_flags}
            build/fitz_extra.cpp
            -o build/_fitz_extra.so
            ''').strip().replace( '\n', " ")
    
    subprocess.run( command, shell=True, check=True)
    
    return [
            'README.md',
            'fitz/__init__.py',
            'fitz/__main__.py',
            'fitz/fitz.py',
            'fitz/utils.py',
            ( 'build/fitz_extra.py', 'fitz/fitz_extra.py'),
            ( 'build/_fitz_extra.so', 'fitz/_fitz_extra.so'),
            'test.py',
            ]


def sdist():
    assert 0

p = pipcl.Package(
        'fitz',
        '0.0.0',
        fn_build=build,
        fn_sdist=sdist,
        )

def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    return p.build_wheel(wheel_directory, config_settings, metadata_directory)

def build_sdist(sdist_directory, config_settings=None):
    return p.build_sdist(sdist_directory, config_settings)

import sys
if __name__ == '__main__':
    p.handle_argv(sys.argv)
