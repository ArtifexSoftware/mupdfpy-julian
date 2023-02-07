<!--
markdown_py -v -x markdown.extensions.toc README.md > README.md.html
-->

<style>
pre
{
    color: black;
    background-color: #e0e0e0;
}
</style>


# mupdfpy

## Contents

[TOC]


## Overview

**mupdfpy** is an alternative implementation of
[PyMuPDF](https://github.com/pymupdf/PyMuPDF) that primarily uses [MuPDF's
native Python bindings](http://mupdf.com/r/C-and-Python-APIs) instead of SWIG
and C code.

**mupdfpy** provides a Python package/module called `fitz`, a drop-in
replacement for PyMuPDF's package/module of the same name.

To improve speed, some internal routines have alternative implementations
written in C++ (these use MuPDF's C++ API directly). Use of these optimised
routines can be disabled by setting environmental variable `MUPDFPY_USE_EXTRA`
to `0`.


## Benefits

* Simpler implementation because of MuPDF C++ and Python API features:

    * Automatic reference counting.
    * Automatic contexts.
    * Native C++ and Python exceptions.

* Potential support for multithreaded use (native PyMuPDF is explicitly
  single-threaded).

* Access to the underlying MuPDF Python API in the `fitz.mupdf` module.


## Status

* Passes all PyMuPDF tests on Unix and Windows, using MuPDF branch 1.21.x and
  branch master.
* On Windows:
    * We get lots of runtime warnings like:
      `swig/python detected a memory leak of type 'mupdf::PdfObj *', no destructor found.`
    * Debug builds fail to build due to SWIG generating code that tries to access
      MuPDF global variables, which are not visible due to a problem with the
      underlying MuPDF Python API.
    * Unlike on Unix, release builds include refcheck debugging code. This code
      is only active if environmental variables such as `MUPDF_trace` are set,
      but it still may effect performance slightly.
 

## Changelog

**Latest**:

* Passes all PyMuPDF tests on Unix and Windows, using MuPDF branch 1.21.x and
  branch master.
* Also works with MuPDF branch master.
* Updated with recent PyMuPDF code changes.
* Uses pipcl.py's new support for building extension modules.
* Added doctest to pipcl.py.
* Added support for building extension modules to pipcl.py.

**2023-01-20**:

* Simplified build/install instructions and added example commands for windows.
* Installing with `pip` will now install `libclang` and `swig` automatically.
* Removed unnecessary `WeakValueDictionary` code.
* Some code cleanup.

**2023-01-17**:

* Added support for Windows.
* Pass all PyMuPDF tests on Windows.
* Added optimised tracetext device implemented in C++.
* Moved all global trace_device state into individual devices.


**2023-01-13**:
* Added Story support.

**2023-01-04**:

* Recommend using pip to install libclang and swig, to simplify installation.
* warn if incomplete fitz/ directory is in cwd


## License

SPDX-License-Identifier: GPL-3.0-only


## Build and install [last updated 2023-1-20]

Supported OS's:

* Linux
* Windows
* OpenBSD

Steps:

* Get MuPDF, 1.21.x branch.
* Get mupdfpy, master branch.
* Set up a Python virtual environment (venv).
* Update pip to latest version.
* Use pip to install mupdfpy, setting environmental variable
  `PYMUPDF_SETUP_MUPDF_BUILD` to point to the local MuPDF checkout. [Installing
  with pip is better than running `setup.py` directly because it will
  automatically install required packages (libclang and swig).

So:

    # Get MuPDF, branch 1.21.x.
    git clone --recursive git://git.ghostscript.com/mupdf.git
    git checkout 1.21.x
    git submodule update --init

    # Get mupdfpy (requires ghostscript login).
    git clone ghostscript.com:/home/julian/repos/mupdfpy.git

    # Create and enter Python virtual environment.
    python3 -m venv pylocal
    . pylocal/bin/activate
    
    # Update pip to latest version.
    python -m pip install --upgrade pip
    
    # Use pip to build and install mupdfpy (will also build MuPDF).
    
    # Unix:
    cd mupdfpy
    PYMUPDF_SETUP_MUPDF_BUILD=../mupdf python -m pip install -vv ./

    # Windows
    set PYMUPDF_SETUP_MUPDF_BUILD=../mupdf
    python -m pip install -vv ./


## Testing

**Note**: When testing or using mupdfpy, make sure that the current directory
is not `mupdfpy`, otherwise `import fitz` will look in the local `fitz/`
directory, which contains only source files. Usually mupdfpy will output a
warning in this case.


### Basic import check:

    python
    >>> import fitz
    platform/c++/implementation/internal.cpp:160:reinit_singlethreaded(): Reinitialising as single-threaded.


### PyMuPDF tests.

These can be run in the usual way, for example:

    pip install pytest fontTools
    pytest PyMuPDF


## Details

### Layout

As of 2022-11-23 a mupdfpy installation consists of these files in a `fitz`
directory:

    fitz/
        
        __init__.py     The main fitz API.
        __main__.py     A copy of PyMuPDF's `fitz.__main__.py`.
        fitz.py         Does `from fitz import *`, to support particular
                        import patterns.
        utils.py        Modified copy of PyMuPDF's `fitz/utils.py`.
        
        extra.py        Internal optimised routines.
        _extra.so       Internal optimised routines internals.
        
        mupdf.py        MuPDF Python API.
        _mupdf.so       MuPDF Python API internals.
        libmupdf.so     MuPDF C API.
        libmupdfcpp.so  MuPDF C++ API.


### Python code

`fitz/__init__.py` contains most of the code. It has Python implementations of
PyMuPDF's internal C code, and modified copies of PyMuPDF's Python code. For
example it contains the top-level classes such as `fitz.Document`. It uses the
MuPDF Python bindings' classes and functions where the PyMuPDF code called the
native C MuPDF API. Much of the PyMuPDF naming structure is preserved, for
example functions with names starting with `JM_` such as `JM_add_oc_object()`,
and a `TOOLS` namespace containing functions such as `TOOLS.set_annot_stem()`.

We also preserve PyMuPDF's alias deprecation system, albeit with a slightly
different implementation - see `fitz/__init__.py:restore_aliases()`.


### Integrated MuPDF

We currently include the MuPDF C, C++ and Python bindings within `fitz/`
itself. It might be possible to install these separately (e.g. with `cd mupdf
&& ./setup.py install`), but it's not clear whether `_extra.so` (which contains
C++ code that uses the MuPDF C++ API) would get access to `libmupdf.so` and
`libmupdfcpp.so`.
