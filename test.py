#! /usr/bin/env python3

import os
import subprocess
import sys

dir_self        = os.path.abspath( f'{__file__}/..')
dir_pymupdf     = os.path.abspath( f'{dir_self}/../PyMuPDF')
dir_mupdf       = os.path.abspath( f'{dir_self}/../mupdf')
dir_mupdf_build = os.path.abspath( f'{dir_mupdf}/build/shared-debug')

env_vars = f'PYTHONPATH={dir_mupdf_build}:{dir_self}:{dir_mupdf}/scripts LD_LIBRARY_PATH={dir_mupdf_build}'

def run_pymupdf_tests():
    command = f'cd {dir_pymupdf}/tests && {env_vars} py.test -s'
    print( f'Running: {command}', file=sys.stderr)
    subprocess.run( command, check=True, shell=1)
    
def main():
    run_pymupdf_tests()

if __name__ == '__main__':
    main()
