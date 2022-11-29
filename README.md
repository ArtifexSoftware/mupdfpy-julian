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

To improve speed, some routines have alternative implementations that use
MuPDF's C++ API. This can be disabled by setting `MUPDFPY_USE_EXTRA=0`.

As of 2022-11-23, only limited testing has been done, and only on Linux and
OpenBSD. No testing has been done on other platforms such as Windows.


## License

SPDX-License-Identifier: GPL-3.0-only


## Build and install [last updated 2022-11-29]

* General.

    * Supported OS's:

        * Linux
        * OpenBSD

          [`mupdfpy/setup.py` does not yet support Windows.]

    * An account on `ghostscript.com` is required.

    * SWIG should be installed.


* Set up a Python virtual environment.

    We need to set things up differently depending on the OS, in order to get a
    working Python clang module.

    #### Linux

    `pip install libclang` seems to be unreliable due to clang not being integrated
    with system headers (for example not having a typedef for `size_t`) which
    breaks MuPDF's Python build.

    So instead we need to install the system package `python3-clang`, and create
    a Python virtual environment with `--system-site-packages` so it can see the
    system's python3-clang.
    
    For example on Devuan:

        sudo apt install python3-clang
        python3 -m venv --system-site-packages pylocal
        . pylocal/bin/activate


    #### OpenBSD

    One can use pip's libclang:

        python3 -m venv pylocal
        . pylocal/bin/activate
        pip install libclang

    Or the system libclang:

        sudo pkg_add py3-llvm
        python3 -m venv --system-site-packages pylocal
        . pylocal/bin/activate


* Get MuPDF, mupdfpy, and build.

    * **MuPDF**

        We need branch `1.21.x` of MuPDF repository: `ghostscript.com:/home/julian/repos/mupdf.git`

        Because of the MuPDF's git repository's use of submodules, this
        requires first getting MuPDF from the main MuPDF repository
        `ghostscript.com:/home/git/mupdf.git`, then pulling from
        `ghostscript.com:/home/julian/repos/mupdf.git`.

    * **mupdfpy**

        We need branch `master` of mupdfpy repository: `ghostscript.com:/home/julian/repos/mupdfpy.git`

    * When building mupdfpy, set `PYMUPDF_SETUP_MUPDF_BUILD` to point to the local MuPDF checkout.

    So, with `USER` replaced by an appropriate username on ghostscript.com:

        # Get MuPDF.
        git clone --branch 1.21.x --recursive USER@ghostscript.com:/home/git/mupdf.git
        cd mupdf
        git pull -r USER@ghostscript.com:/home/julian/repos/mupdf.git 1.21.x
        cd ..

        # Get mupdfpy.
        git clone USER@ghostscript.com:/home/julian/repos/mupdfpy.git

        # Build mupdfpy (will also build MuPDF).
        cd mupdfpy
        PYMUPDF_SETUP_MUPDF_BUILD=../mupdf ./setup.py install


## Testing

**Note**: When testing or using mupdfpy, make sure that the current directory
is not `mupdfpy`, otherwise `import fitz` will look in the local `fitz/`
directory, which contains only source files.

### Basic import check:

    python
    >>> import fitz
    platform/c++/implementation/internal.cpp:160:reinit_singlethreaded(): Reinitialising as single-threaded.

### PyMuPDF tests.

These can be run in the usual way, for example:

    pip install pytest fontTools
    pytest PyMuPDF

### Known failures as of 2022-11-23:

    PyMuPDF/tests/test_annots.py::test_freetext - RuntimeError: code=2: FreeText annotations have no IC property
    PyMuPDF/tests/test_annots.py::test_1645 - RuntimeError: code=2: FreeText annotations have no IC property
    
    Stories are not implemented so all the Story tests fail.
    
    PyMuPDF/tests/test_drawings.py::test_drawings1 - assert "[{'closePath...dth': 1.0}]\n" == "[{'closePath...dth': 1.0}]\n"
    PyMuPDF/tests/test_drawings.py::test_drawings3 - AssertionError: assert (set(), set(), {}) == (set(), set()...False, True)})
 

## Details

We provide a Python package/module called `fitz`, a drop-in replacement for
PyMuPDF's package/module of the same name.

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

`fitz/__init__.py` contains most of the code. It has Python implementations of
PyMuPDF's internal C code, and modified copies of PyMuPDF's Python code. For
example it contains the top-level classes such as `fitz.Document`. It uses the
MuPDF Python bindings' classes and functions where the PyMuPDF code called the
native C MuPDF API. Much of the PyMuPDF naming structure is preserved, for
example functions with names starting with `JM_` such as `JM_add_oc_object()`,
and a `TOOLS` namespace containing functions such as `TOOLS.set_annot_stem()`.

We also preserve PyMuPDF's alias deprecation system, albeit with a slightly
different implementation - see `fitz/__init__.py:restore_aliases()`.

We currently include the MuPDF C, C++ and Python bindings within `fitz/`
itself. It would be possible to install these separately (e.g. with `cd mupdf
&& ./setup.py install`), but it's not clear whether `_extra.so` (which contains
C++ code that uses the MuPDF C++ API) would get access to `libmupdf.so` and
`libmupdfcpp.so`.
