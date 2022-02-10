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


## License

SPDX-License-Identifier: GPL-3.0-only


## Example usage

Using pre-built MuPDF Python bindings:

    pip install mupdf 
    PYTHONPATH=.../mupdfpy myprog.py ...

Using local MuPDF checkout and build:


    # Build MuPDF Python bindings:
    cd .../mupdf && ./scripts/mupdfwrap.py -d build/shared-debug -b --python all
    
    PYTHONPATH=.../mupdfpy:.../mupdf/build/shared-debug \
        LD_LIBRARY_PATH=.../mupdf/build/shared-debug \
        myprog.py ...


## Running tests:

Run PyMuPDF's pytest tests with mupdfpy's `fitz` module, with:
    
    mupdfpy/test.py --tests

This assumes that:

* There is a `PyMuPDF` checkout next to the `mupdfpy`
directory.

* And that one of the following is the case:
    * The MuPDF Python bindings are installed and can be imported with `import mupdf`.

    * There is a `mupdf` checkout next to the `mupdfpy` directory with a build
    of the Python bindings in `build/shared-debug/`.

Use the `--pymupdf` and `--mupdf` options to specify different locations, for example:

    mupdfpy/test.py --mupdf mupdf/build/shared-release/ --tests


## Details:

We provide a Python module called `fitz`, a drop-in replacement for PyMuPDF's
module of the same name.

As of 2022-02-10, the implementation consists of two Python files:

    fitz.py
    fitz_utils.py

`fitz.py` contains new Python implementations of all of PyMuPDF's C code, plus
modified versions of PyMuPDF's Python code, for example the top-level classes
such as `fitz.Document`. This code uses the MuPDF Python bindings' classes
and functions where the PyMuPDF code called the native C MuPDF API. Much of
the PyMuPDF naming structure is preserved, for example functions with names
starting with `JM_` such as `JM_add_oc_object()`, and a `TOOLS` namespace
containing functions such as `TOOLS.set_annot_stem()`.

We also preserve PyMuPDF's alias deprecation system, albeit with a slightly
different implementation - see `fitz.restore_aliases()`.

`fitz_utils.py` is a copy of PyMuPDF's `fitz/utils.py` with minor
modifications; it is renamed to `fitz_utils.py` in order to avoid it appearing
as a module called `utils`, but appears as `fitz.utils`.
