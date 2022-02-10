#! /usr/bin/env python3

'''
Test script for mupdfpy.

Usage:
    --mupdf <dir>
        Specify location of MuPDF library and Python files, for example:
            ../mupdf/build/shared-debug
    --pymupdf <dir>
        Specify location of PyMuPDF directory, for example:
            ../PyMuPDF
    --tests
        Run PyMuPDF's tests.
'''

import os
import subprocess
import sys


class State:
    def __init__( self):
        self.mupdfpy    = f'{__file__}/..'
        self.mupdf      = f'{self.mupdfpy}/../mupdf/build/shared-debug'
        self.pymupdf    = f'{self.mupdfpy}/../PyMuPDF'
    def env_vars( self):
        
        return (''
                + f' PYTHONPATH='
                    + f'{os.path.abspath(self.mupdfpy)}'
                    + f':{os.path.abspath(self.mupdf)}'
                + f' LD_LIBRARY_PATH={os.path.abspath(self.mupdf)}'
                )


def run_pymupdf_tests( state):
    '''
    Run all tests in PyMuPDF/tests, using mupdfpy.
    '''
    command = f'cd {state.pymupdf}/tests && {state.env_vars()} py.test -s'
    print( f'Running: {command}', file=sys.stderr)
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
        elif arg == '--tests':
            run_pymupdf_tests( state)
        else:
            raise Exception( f'Unrecognised arg: {arg!r}')

if __name__ == '__main__':
    main()
