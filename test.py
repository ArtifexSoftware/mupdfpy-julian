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
                --mupdf and --mupdf-build-dir.
            'cppyy':
                Use local experimental cppyy Python bindings, as specified by
                --mupdf-build-dir.
    
    --mupdf <dir>
        Specify location of local mupdf directory. This is used to find
        mupdf/scripts/platform/python/mupdfwrap_cppyy.py by '--env cppyy'.
        
        Default is directory mupdf/ next to the mupdfpy directory.
    
    --mupdf-build-dir <dir>
        Specify location of MuPDF library and Python files, for example:
            foo/bar/mupdf/build/shared-debug
        Also used to find mupdf_cppyy.py by --env cppyy.
        
        Default is: {mupdf}/build/shared-release
    
    --pymupdf <dir>
        Specify location of PyMuPDF directory, for example:
            foo/bar/PyMuPDF
        
        Default is directory PyMuPDF/ next to the mupdfpy directory.
    
    --run <command> ...
        Runs specified command, prefixing with settings for PYTHONPATH and
        LD_LIBRARY_PATH so that Python will find mupdfpy's fitz module.
        
        For example:
            PYTHONPATH=PySimpleGUI ./mupdfpy/test.py --mupdf mupdf/build/shared-release --run python3 PyMuPDF-Utilities/animations/morph-demo1.py

    --tests [<pytest-flags>] <test-file> | all | '' | '.'
        Run PyMuPDF's py.test tests.
        
        <pytest-flags>:
            E.g. '-x' to stop at first error.
        
        E.g.:
            --test test_annots.py
        
        Uses 'all' or '' or '.' to run all tests.   
        
        If running in a Python virtual environment, be sure to install pytest
        in the venv before running this command. Otherwise the system pytest
        will be used which in turn will use the system python, which won't see
        the venv's modules.
    
    --tests-pypy
        Experimental. Like --tests but runs tests with pypy.

    --test-wheel <items>
        items:
            List of single-character items:
                0:  Create new venv.
                1:  Build mupdfpy wheel.
                2:  Install wheel (with `pip --force-reinstall`).
                3:  Test use of wheel.
            `all` is treated as `0123`.
    
    --venv <name> <command>
        Run remaining args in a new test.py invocation running in a Python
        virtual environment called <name> (in the current directory). See below
        for example usage.

Examples:

    Run PyMuPDF pytest tests using mupdfpy's rebased PyMuPDF. We run in a
    Python virtual environment in which we install mupdf from pypi.org:
    
        ./mupdfpy/test.py --venv pylocal 'pip install -U mupdf pytest && ./mupdfpy/test.py --tests'

    Test that the mupdf module can be installed from pypi.org and imported in a
    Python virtual environment:
    
        ./mupdfpy/test.py --venv pylocal 'pip install -U mupdf && python -m mupdf'
    
'''

import glob
import os
import subprocess
import shlex
import shutil
import sys


def log( text):
    print( text, file=sys.stderr)


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
        ret += f' PYTHONPATH=$PYTHONPATH:{os.path.abspath(self.mupdfpy)}:{os.path.abspath(self.mupdf_dir)}/scripts'
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
            ret += f':{os.path.abspath(self.mupdf_dir)}/scripts'
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
        ret += f' PYTHONPATH=$PYTHONPATH:{os.path.abspath(self.mupdfpy)}:{os.path.abspath(self.mupdf_build_dir)}:{os.path.abspath(self.mupdf_dir)}/scripts'
        ret += f' MUPDF_CPPYY='
        ret += f' CPPYY_CRASH_QUIET=1 MUPDF_cppyy_sig_exceptions=1'
        return ret
        


def run_pymupdf_tests( state, testname=None, pypy=False, ptest_flags=''):
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
        command = f'cd {d} && {env} {pytest} {ptest_flags} -s'
    if testname:
        command += f' {testname}'
    log( f'Running: {command}')
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
            log( f'Running: {command}')
            subprocess.run( command, check=True, shell=True)
            
            #venv_name = 'pylocal'
            #dir_mupdf = f'{state.mupdfpy}/../mupdf'
            #command = ''
            #command += f'{sys.executable} -m venv {venv_name} && . {venv_name}/bin/activate &&'
            #command += f' {state.env_vars_cppyy()}'
            #command += f' python -m fitz'
            #log(f'Running: {command}')
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
                log( f'{namespace}:')
                for n, v in inspect.getmembers( namespace):
                    if not n.startswith( '_'):
                        log( f'    {n}={v}')
            
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
            log( f'cppyy.__version__={cppyy.__version__}')
            log( f'cppyy.gbl.foo={cppyy.gbl.FOO}')
            log( f'cppyy.gbl.foo={cppyy.gbl.foo}')
            log( f'cppyy.gbl.N.bar={cppyy.gbl.N.BAR}')
            log( f'cppyy.gbl.N.bar={cppyy.gbl.N.bar}')
            
            show( cppyy.gbl)    # Now shows FOO and foo().
            
            show( cppyy)

        elif arg == '--test-cppyy-simple3':
            # https://github.com/wlav/cppyy/issues/51
            import cppyy
            cppyy.cppdef('''
                    #define foo() foo_()
                    enum foo { FOO };
                    void foo() {}
                    void bar( enum foo f) {}
                    ''')
            cppyy.gbl.bar( cppyy.gbl.FOO)
        
        elif arg == '--test-cppyy-simple4':
            path = 'test-cppyy-simple4.cpp'
            with open( path, 'w') as f:
                f.write( '''
                        #include <assert.h>
                        void foo()
                        {
                            assert( 0);
                        }
                        ''')
            e = os.system( 'c++ -shared -fPIC -W -Wall -o test-cppyy-simple4_lib.so test-cppyy-simple4.cpp')
            assert not e
            import ctypes
            import traceback
            import cppyy
            import cppyy.ll
            
            cppyy.cppdef('''
                    void foo();
                    ''')
            cppyy.load_library('test-cppyy-simple4_lib.so')
            
            with cppyy.ll.signals_as_exception():
                
                try:
                    cppyy.gbl.abort()
                except:
                    traceback.print_exc()
                else:
                    assert 0
                
                try:
                    cppyy.gbl.foo()
                except:
                    traceback.print_exc()
                else:
                    assert 0
                
                try:
                    cppyy.gbl.foo()
                except:
                    traceback.print_exc()
                else:
                    assert 0
            
            log( '======= Testing out-param')
            cppyy.cppdef('''
                    void bar( int* out1, unsigned char** out2)
                    {
                        std::cerr
                                << "bar():"
                                << " out1=" << out1
                                << " *out1=" << *out1
                                << " out2=" << out2
                                << " *out2=" << ((void*) *out2)
                                << "\\n";
                        *out1 = 32;
                        *out2 = (unsigned char*) "hello world";
                        std::cerr << "bar(): *out2=" << ((void*) *out2) << "\\n";
                    }
                    ''')
            out1 = ctypes.pointer( ctypes.c_int())
            #out2 = ctypes.pointer( ctypes.pointer( ctypes.c_byte()))
            #out2 = ctypes.pointer( ctypes.c_byte())
            out2 = ctypes.POINTER( ctypes.c_ubyte)()
            #out2_ = out2()
            
            cppyy.gbl.bar( out1,
                    # out2,
                    ctypes.pointer( out2),
                    #out2_,
                    )
            log( f'out1={out1} out1.contents={out1.contents} out1.contents.value={out1.contents.value}')
            
            log( f'out2={out2}')
            #log( f'out2.contents={out2.contents}')
            #log( f'out2.contents.value={out2.contents.value}')
            
            cppyy.gbl.bar( out1,
                    # out2,
                    ctypes.pointer( out2),
                    #out2_,
                    )
            
            log( 'Ok')
        
        elif arg == '--test-cppyy-5':
            import cppyy
            import cppyy.ll
            import ctypes
            cppyy.cppdef('''
                    void foo(const char* name)
                    {
                        std::cerr << "name=" << (void*) name;
                        if (name) std::cerr << "='" << name << "'";
                        std::cerr << "\\n";
                    }
                    ''')
            def call( p):
                print( f'=== calling foo() with p={p}={p!r}', file=sys.stderr)
                try:
                    cppyy.gbl.foo( p)
                except Exception  as e:
                    print( f'Failed: {e}', file=sys.stderr)
                else:
                    print( f'Ok.', file=sys.stderr)
            call( 0)    # Fails.
            call( cppyy.nullptr)    # Fails.
            call( None) # Fails.
            call( cppyy.ll.cast[ 'const char*']( 0))    # Passes pointer to ''.
            call( ctypes.c_char_p())    # Ok, passes nullptr.
        
        elif arg == '--test-cppyy-6':
            import cppyy
            cppyy.cppdef('''
                    struct Foo
                    {
                        unsigned int a : 1;
                        unsigned int b : 2;
                        unsigned int c : 4;
                        unsigned int d : 1;
                        unsigned int e : 8;
                        unsigned int f :16;
                        
                        Foo() : a(1), b(0), c(0), d(0), e(0x33), f(0x5555)
                        {}
                    };
                    ''')
            f = cppyy.gbl.Foo();
            print( f'a=0x{f.a:x}')
            print( f'b=0x{f.b:x}')
            print( f'c=0x{f.c:x}')
            print( f'd=0x{f.d:x}')
            print( f'e=0x{f.e:x}')
            print( f'f=0x{f.f:x}')
            f.c = 0xf0
            print('After setting f.c to 0xf0:')
            print( f'a=0x{f.a:x}')
            print( f'b=0x{f.b:x}')
            print( f'c=0x{f.c:x}')
            print( f'd=0x{f.d:x}')
            print( f'e=0x{f.e:x}')
            print( f'f=0x{f.f:x}')
        
        elif arg == '--test-cppyy-7':
            import cppyy
            import cppyy.ll
            cppyy.cppdef('''
                    struct Foo
                    {
                    };
                    void foo(Foo* f)
                    {
                        std::cerr << "f=" << f << "\\n";
                    }
                    ''')
            p = cppyy.ll.cast['Foo*'](0)
            cppyy.gbl.foo( p)
            cppyy.gbl.foo( cppyy.nullptr)
            cppyy.gbl.foo( None)    # Fails.
            
        elif arg == '--test-cppyy-8':
            import cppyy
            import cppyy.ll
            
            import time
            
            cppyy.cppdef('''
                    struct Foo
                    {
                        virtual void fn() {}
                        virtual void fn2() {}
                        virtual void fn3() {}
                        virtual void fn4() {}
                    };
                    ''')
            class Foo2( cppyy.gbl.Foo):
                def __init__( self):
                    super().__init__()
                    def fn( self):
                        pass
                    def fn2( self):
                        pass
                    def fn3( self):
                        pass
                    def fn4( self):
                        pass
            t = time.time()
            foo = Foo2()
            t = time.time() - t
            print( f't={t}')
            
            t = time.time()
            foo = Foo2()
            t = time.time() - t
            print( f't={t}')
            
            t = time.time()
            foo = Foo2()
            t = time.time() - t
            print( f't={t}')
        
        elif arg == '--test-fz_warn':
            env = state.env_vars()
            # We deliberately put a '%' into the message to check that this
            # doesn't cause a segv by mupdf.mfz_warn() thinking it is a
            # variadic arg.
            command = f'import mupdf; mupdf.mfz_warn( "test %s message")'
            command = f'{state.env_vars()} {sys.executable} -c {shlex.quote( command)}'
            print( f'Running: {command}')
            subprocess.run( command, check=True, shell=1)
        
        elif arg == '--tests':
            ptest_flags = ''
            while 1:
                testname = next( args)
                if not testname.startswith( '-'):
                    break
                a = testname
                ptest_flags += f' {a}'
            if testname in ( 'all', '', '.'):
                testname = None
            run_pymupdf_tests( state, testname, ptest_flags=ptest_flags)
        
        elif arg == '--tests-pypy':
            run_pymupdf_tests( state, pypy=True)
        
        elif arg == '--test-wheel':
            def run( command):
                print( f'Running: {command}')
                subprocess.run( command, shell=True, check=True)
            items = next( args)
            if items == 'all':
                items = '0123'
            for item in items:
                if item == '0':
                    shutil.rmtree( 'test-venv', ignore_errors=1)
                    run( f'{sys.executable} -m venv test-venv')
                    run( f'. test-venv/bin/activate && pip install --upgrade pip')
                elif item == '1':
                    shutil.rmtree( 'build', ignore_errors=1)
                    shutil.rmtree( 'dist', ignore_errors=1)
                    run( f'{sys.executable} setup.py bdist_wheel')
                elif item == '2':
                    wheels = glob.glob( 'dist/*.whl')
                    assert len( wheels) == 1
                    wheel = wheels[ 0]
                    run( f'. test-venv/bin/activate && pip install --force-reinstall {wheel}')
                elif item == '3':
                    # Run test in subdir, otherwise `import` will look in local `fitz/`
                    # directory first.
                    #
                    os.makedirs( 'test-subdir', exist_ok=True)
                    llp = os.path.abspath( '../mupdf/build/shared-release')
                    run( f'. test-venv/bin/activate && cd test-subdir && PYTHONPATH=../../mupdf/build/shared-release LD_LIBRARY_PATH={llp} python -c "import fitz; import fitz.extra; print(\\"Have imported fitz.extra\\")"')
                
                else:
                    raise Exception( f'Unrecognised item after {arg}: {item}')
        
        elif arg == '--run':
            command = state.env_vars() + ' '
            command += ' '.join( [a for a in args])
            log( f'Running: {command}')
            subprocess.run( command, check=True, shell=True)
        
        elif arg == '--venv':
            name = next( args)
            #command = f'{sys.executable} -m venv {name} && . {name}/bin/activate && {next(args)}'
            command = f'{sys.executable} -m venv {name} && . {name}/bin/activate && python {sys.argv[0]}'
            for arg in args:
                command += f' {shlex.quote( arg)}'
            log( f'Running: {command}')
            subprocess.run( command, check=True, shell=True)
        
        else:
            raise Exception( f'Unrecognised arg: {arg!r}')


if __name__ == '__main__':
    main()
