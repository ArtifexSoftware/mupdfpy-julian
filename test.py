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
        self.mupdfpy            = f'{__file__}/..'
        self.mupdf_dir          = f'{self.mupdfpy}/../mupdf'
        self.mupdf_build_dir    = f'{self.mupdf_dir}/build/shared-release'
        #self.mupdf              = None
        self.pymupdf            = f'{self.mupdfpy}/../PyMuPDF'
    
    def env_vars( self):
        '''
        Returns shell-style environmental variables assuming Python module
        'mupdf' is installed. I.e. we just need specify location of mupdfpy in
        PYTHONPATH.
        '''
        ret = ''
        ret += f' PYTHONPATH=$PYTHONPATH:{os.path.abspath(self.mupdfpy)}'
        return ret
    
    def env_vars_mupdf( self):
        '''
        Returns string for use as a command prefix that sets LD_LIBRARY_PATH
        and PYTHONPATH so that Python can find the mupdf Python module in a
        mupdf directory and mupdfpy's fitz Python module.
        '''
        ret = ''
        if self.mupdf_build_dir:
            ret += f' LD_LIBRARY_PATH=$LD_LIBRARY_PATH:{os.path.abspath(self.mupdf_build_dir)}'
        if self.mupdfpy or self.mupdf_build_dir:
            ret += f' PYTHONPATH=$PYTHONPATH'
            if self.mupdfpy:
                ret += f':{os.path.abspath(self.mupdfpy)}'
            if self.mupdf_build_dir:
                ret += f':{os.path.abspath(self.mupdf)}'
        return ret
    
    def env_vars_cppyy( self):
        '''
        Returns string for use as a command prefix that sets LD_LIBRARY_PATH
        and MUPDF_CPPYY and PYTHONPATH so that we can find mupdfpy
        Python module, the mupdf C and C++ libraries, and the
        mupdf/platform/python/mupdf_cppyy.py module.
        '''
        ret = ''
        ret += f' LD_LIBRARY_PATH=$LD_LIBRARY_PATH:{os.path.abspath( self.mupdf_build_dir)}'
        ret += f' MUPDF_CPPYY={os.path.abspath(self.mupdf_dir + "/platform/python/mupdf_cppyy.py")}'
        ret += f' PYTHONPATH=$PYTHONPATH:{os.path.abspath(self.mupdfpy)}'
        return ret
        


def run_pymupdf_tests( state, cppyy=False):
    '''
    Runs pytest in PyMuPDF/tests, using mupdfpy.
    '''
    for pytest in 'py.test', 'py.test-3':
        if shutil.which( pytest, mode=os.X_OK):
            break
    else:
        raise Exception( 'Cannot find py.test command')
    d = os.path.abspath( f'{state.pymupdf}/tests')
    if cppyy:
        subprocess.run( 'pip install cppyy', check=True, shell=1)
        env = state.env_vars_cppyy()
    else:
        env = state.env_vars()
    command = f'cd {d} && {env} {pytest} -s'
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
        elif arg == '--test-cppyy-simple':
            venv_name = 'pylocal'
            dir_mupdf = f'{state.mupdfpy}/../mupdf'
            command = ''
            command += f'{sys.executable} -m venv {venv_name} && . {venv_name}/bin/activate &&'
            command += f' {state.env_vars_cppyy()}'
            command += f' python -m fitz'
            print(f'Running: {command}')
            subprocess.run( command, check=True, shell=True)
        elif arg == '--tests-cppyy':
            run_pymupdf_tests( state, cppyy=True)
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
