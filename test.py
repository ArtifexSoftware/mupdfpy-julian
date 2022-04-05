#! /usr/bin/env python3

'''
Test script for mupdfpy.

Arguments are evaluated/run in the order in which they occur on the command
line.

Arguments:

    --env <type>
        type:
            'installed' (default):
                Use installed MuPDF Python bindings, e.g. from 'pip install
                mupdf'.
            'mupdf':
                Use local MuPDF Python bindings, as specified by
                --mupdf-build-dir.
            'cppyy':
                Use experimental local MuPDF experimental cppyy Python
                bindings, as specified by --mupdf and --mupdf-build-dir.
    
    --mupdf <dir>
        Specify location of local mupdf directory. This is used to find
        mupdf/platform/python/mupdfwrap_cppyy.py by '--env cppyy'.
    
    --mupdf-build-dir <dir>
        Specify location of MuPDF library and Python files, for example:
            foo/bar/mupdf/build/shared-debug
    
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
    
    --tests-pypy
        Experimental. Like --tests but runs tests with pypy.
    
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
        self.pymupdf            = f'{self.mupdfpy}/../PyMuPDF'
        self.env                = 'installed'
    
    def env_vars( self):
        if self.env == 'installed':
            return self.env_vars_installed()
        elif self.env == 'mupdf':
            return self.env_vars_mupdf()
        elif self.env == 'cppyy':
            return self.env_vars_cppyy()
        else:
            raise Exception( 'Unrecognised env={env}')
    
    def env_vars_installed( self):
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
                ret += f':{os.path.abspath(self.mupdf_build_dir)}'
        return ret
    
    def env_vars_cppyy( self):
        '''
        Returns string for use as a command prefix that sets LD_LIBRARY_PATH
        and MUPDF_CPPYY and PYTHONPATH so that we can find mupdfpy
        Python module, the mupdf C and C++ libraries, and the
        build/*/mupdf_cppyy.py module.
        '''
        ret = ''
        ret += f' LD_LIBRARY_PATH=$LD_LIBRARY_PATH:{os.path.abspath( self.mupdf_build_dir)}'
        #ret += f' MUPDF_CPPYY={os.path.abspath(self.mupdf_dir + "/platform/python/mupdf_cppyy.py")}'
        ret += f' PYTHONPATH=$PYTHONPATH:{os.path.abspath(self.mupdfpy)}:{os.path.abspath(self.mupdf_build_dir)}'
        ret += f' MUPDF_CPPYY='
        return ret
        


def run_pymupdf_tests( state, pypy=False):
    '''
    Runs pytest in PyMuPDF/tests, using mupdfpy.
    '''
    for pytest in 'py.test', 'py.test-3':
        if shutil.which( pytest, mode=os.X_OK):
            break
    else:
        raise Exception( 'Cannot find py.test command')
    d = os.path.abspath( f'{state.pymupdf}/tests')
    env = state.env_vars()
    if pypy:
        command = f'cd {d} && {env} pypy3 `which {pytest}` -s'
    else:
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
        
        elif arg == '--env':
            state.env = next( args)
        
        elif arg == '--mupdf':
            state.mupdf = next( args)
        
        elif arg == '--mupdf-build-dir':
            state.mupdf_build_dir = next( args)
        
        elif arg == '--pymupdf':
            state.pymupdf = next( args)
        
        elif arg == '--cppyy-simple':
            env = state.env_vars()
            command = f'{env} {sys.executable} -m mupdf_cppyy'
            print(f'Running: {command}')
            subprocess.run( command, check=True, shell=True)
            
            #venv_name = 'pylocal'
            #dir_mupdf = f'{state.mupdfpy}/../mupdf'
            #command = ''
            #command += f'{sys.executable} -m venv {venv_name} && . {venv_name}/bin/activate &&'
            #command += f' {state.env_vars_cppyy()}'
            #command += f' python -m fitz'
            #print(f'Running: {command}')
            #subprocess.run( command, check=True, shell=True)
        
        elif arg == '--test-cppyy-simple2':
            # This demonstrates that cppyy allows enumeration of items in
            # namespaces, but not of items at top-level scope.
            #
            # So we can enumerate the mupdf namespace, e.g. get to see find the
            # MuPDF wrapper classes, but cannot enumerate the enums that MuPDF
            # C API defines, such as PDF_ENUM_NAME_3D etc.
            #
            # https://root-forum.cern.ch/t/cppyy-gbl-and-root-namespace/34396/7
            #
            import cppyy
            import inspect
            
            def show( namespace):
                '''
                Show items in <namespace> whose names do not start with an
                underscore.
                '''
                print( f'{namespace}:')
                for n, v in inspect.getmembers( namespace):
                    if not n.startswith( '_'):
                        print( f'    {n}={v}')
            
            # Create some C++ functions, enums and a namespace:
            cppyy.cppdef('''
                    enum { FOO };
                    void foo() {}
                    namespace N
                    {
                        enum { BAR };
                        void bar() {}
                    }
                    ''')
            
            show( cppyy.gbl)    # Does not show FOO or foo().
            show( cppyy.gbl.N)  # Shows BAR and bar().
            
            # foo() and FOO do exist if we ask for them explicitly:
            print( f'cppyy.__version__={cppyy.__version__}')
            print( f'cppyy.gbl.foo={cppyy.gbl.FOO}')
            print( f'cppyy.gbl.foo={cppyy.gbl.foo}')
            print( f'cppyy.gbl.N.bar={cppyy.gbl.N.BAR}')
            print( f'cppyy.gbl.N.bar={cppyy.gbl.N.bar}')
            
            show( cppyy.gbl)    # Now shows FOO and foo().
            
            show( cppyy)
        
        elif arg == '--tests':
            run_pymupdf_tests( state)
        
        elif arg == '--tests-pypy':
            run_pymupdf_tests( state, pypy=True)
        
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
