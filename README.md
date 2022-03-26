<!--
markdown_py -v -x markdown.extensions.toc README.md > README.md.html
-->

# mupdfpy

## Contents

[TOC]

## Overview

Mupdfpy is a pure-Python implementation of
[PyMuPDF](https://github.com/pymupdf/PyMuPDF) that uses [MuPDF's native Python
bindings](http://mupdf.com/r/C-and-Python-APIs) instead of SWIG and C code.

As of 2022-03-26, limited testing has been done on Linux. No testing has been
done on other platforms such as Windows.


## License

SPDX-License-Identifier: GPL-3.0-only


## Example usage

### Using mupdf from pypi.org

    # Install mupdf
    pip install -U mupdf
    
    # Run a PyMuPDF programme:
    PYTHONPATH=.../mupdfpy myprog.py ...

### Using a local MuPDF checkout and build

    # Build MuPDF Python bindings:
    cd .../mupdf && ./scripts/mupdfwrap.py -d build/shared-debug -b --python all
    
    # Run a PyMuPDF programme:
    PYTHONPATH=.../mupdfpy:.../mupdf/build/shared-debug \
        LD_LIBRARY_PATH=.../mupdf/build/shared-debug \
        myprog.py ...


## Running PyMuPDF's `py.test` tests with mupdfpy's `fitz` module

First get a copy of PyMuPDF so we can access its tests:

    git clone https://github.com/pymupdf/PyMuPDF.git

The following commands assume that the `PyMuPDF` directory is next to the
`mupdfpy` directory. If this is not the case, specify the location of the
`PyMuPDF` directory with `mupdfpy/test.py`'s `--pymupdf <dir>` option.

### Test using system Python

    # Install the latest mupdf Python module from pypi.org.
    pip install -U mupdf
    
    # Run PyMuPDF pytests using mupdfpy's 'fitz' module.
    ./mupdfpy/test.py --tests

### Test in a Python virtual environment

    python3 -m venv pylocal && . pylocal/bin/activate && pip install -U mupdf pytest && ./mupdfpy/test.py --tests

### Test in a Python virtual environment using `mupdfpy/test.py`'s `--venv` option

    ./mupdfpy/test.py --venv pylocal 'pip install -U mupdf pytest && ./mupdfpy/test.py --tests'


### More information

See `mupdfpy/test.py` for more details.


## Details

We provide a Python package/module called `fitz`, a drop-in replacement for
PyMuPDF's module of the same name.

As of 2022-03-26, the implementation consists of these Python files in the
`fitz` directory:

    fitz/
        __init__.py
        __main__.py
        fitz.py
        utils.py

`fitz/__init__.py` contains most of the code. It has Python implementations of
PyMuPDF's internal C code, and modified copies of PyMuPDF's Python code. For
example it contains the top-level classes such as `fitz.Document`. It uses the
MuPDF Python bindings' classes and functions where the PyMuPDF code called the
native C MuPDF API. Much of the PyMuPDF naming structure is preserved, for
example functions with names starting with `JM_` such as `JM_add_oc_object()`,
and a `TOOLS` namespace containing functions such as `TOOLS.set_annot_stem()`.

We also preserve PyMuPDF's alias deprecation system, albeit with a slightly
different implementation - see `fitz/__init__.py:restore_aliases()`.

`fitz/__main__.py` is a copy of PyMuPDF's `fitz.__main__.py`.

`fitz/fitz.py` just does `from fitz import *`, and is provided to support some
particular import patterns.

`fitz/utils.py` is a copy of PyMuPDF's `fitz/utils.py` with various
modifications.

