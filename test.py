#! /usr/bin/env python3

'''
Test script for mupdfpy.

Arguments are evaluated/run in the order in which they occur on the command
line.

Arguments:

    --mupdf <dir>
        Specify location of MuPDF library and Python files, for example:
            foo/bar/mupdf/build/shared-debug
        
        Default is None so we require that mupdf is installed, for example with
        'pip install mupdf'.
    
    --pymupdf <dir>
        Specify location of PyMuPDF directory, for example:
            foo/bar/PyMuPDF
        
        Default is assumed to be a PyMuPDF/ directory next to the mupdfpy
        directory.
    
    --run <command> ...
        Runs specified command, prefixing with settings for PYTHONPATH and
        LD_LIBRARY_PATH so that Python will find mupdfpy's fitz module.
        
        For example:
            PYTHONPATH=PySimpleGUI ./mupdfpy/test.py --mupdf mupdf/build/shared-release --run python3 PyMuPDF-Utilities/animations/morph-demo1.py
    
    --tests
        Run PyMuPDF's py.test tests.
        
        If running in a Python virtual environment, be sure to install pytest
        in the venv before running this command. Otherwise the system pytest
        will be used which in turn will use the system python, which won't see
        the venv's modules.
    
    --venv <name> <command>
        Run specified command in a Python virtual environment called <name> (in
        the current directory). See below for example usage.

Examples:

    Run PyMuPDF pytest tests using mupdfpy's rebased PyMuPDF. We run in a
    Python virtual environment in which we install mupdf from pypi.org:
    
        ./mupdfpy/test.py --venv pylocal 'pip install -U mupdf pytest && ./mupdfpy/test.py --tests'

    Test that the mupdf module can be installed from pypi.org and imported in a
    Python virtual environment:
    
        ./mupdfpy/test.py --venv pylocal 'pip install -U mupdf && python -m mupdf'
    
'''

import os
import subprocess
import shlex
import shutil
import sys


class State:
    '''
    Locations of PyMuPDF and mupdf directories.
    '''
    def __init__( self):
        self.mupdfpy    = f'{__file__}/..'
        #self.mupdf      = f'{self.mupdfpy}/../mupdf/build/shared-release'
        self.mupdf      = None
        self.pymupdf    = f'{self.mupdfpy}/../PyMuPDF'
    
    def env_vars( self):
        '''
        Returns string for use as a command prefix that sets LD_LIBRARY_PATH
        and PYTHONPATH so that Python can find the mupdf Python module and
        mupdfpy's fitz Python module.
        '''
        ret = ''
        if self.mupdf:
            ret += f' LD_LIBRARY_PATH=$LD_LIBRARY_PATH:{os.path.abspath(self.mupdf)}'
        if self.mupdfpy or self.mupdf:
            ret += f' PYTHONPATH=$PYTHONPATH'
            if self.mupdfpy:
                ret += f':{os.path.abspath(self.mupdfpy)}'
            if self.mupdf:
                ret += f':{os.path.abspath(self.mupdf)}'
        return ret


def run_pymupdf_tests( state):
    '''
    Runs pytest in PyMuPDF/tests, using mupdfpy.
    '''
    for pytest in 'py.test', 'py.test-3':
        if shutil.which( pytest, mode=os.X_OK):
            break
    else:
        raise Exception( 'Cannot find py.test command')
    d = os.path.abspath( f'{state.pymupdf}/tests')
    command = f'cd {d} && {state.env_vars()} {pytest} -s'
    print( f'Running: {command}', file=sys.stderr)
    sys.stderr.flush()
    subprocess.run( command, check=True, shell=1)


def main():
    state = State()
    args = iter( sys.argv[1:])
    while 1:
        try:
            arg = next( args)
        except StopIteration:
            break
        if arg in ( '-h', '--help'):
            print( __doc__)
        elif arg == '--mupdf':
            state.mupdf = next( args)
        elif arg == '--pymupdf':
            state.pymupdf = next( args)
        elif arg == '--test-cppyy':
            venv_name = 'pylocal'
            dir_mupdf = f'{state.mupdfpy}/../mupdf'
            command = ''
            command += f'{sys.executable} -m venv {venv_name} && . {venv_name}/bin/activate &&'
            command += f' LD_LIBRARY_PATH={os.path.abspath(dir_mupdf)}/build/shared-release'
            command += f' PYTHONPATH={os.path.abspath(state.mupdfpy)}'
            command += f' MUPDF_CPPYY={os.path.abspath(dir_mupdf)}/platform/python/mupdf_cppyy.py'
            command += f' python -m fitz'
            print(f'Running: {command}')
            subprocess.run( command, check=True, shell=True)
        elif arg == '--tests':
            run_pymupdf_tests( state)
        elif arg == '--run':
            command = state.env_vars() + ' '
            command += ' '.join( [a for a in args])
            print( f'Running: {command}')
            subprocess.run( command, check=True, shell=True)
        elif arg == '--venv':
            name = next( args)
            command = f'{sys.executable} -m venv {name} && . {name}/bin/activate && {next(args)}'
            print( f'Running: {command}')
            subprocess.run( command, check=True, shell=True)
        else:
            raise Exception( f'Unrecognised arg: {arg!r}')

if __name__ == '__main__':
    main()
