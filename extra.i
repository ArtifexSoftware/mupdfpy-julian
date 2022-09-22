%module fitz_extra

%include std_string.i

%{
#include "mupdf/classes2.h"

const char* MSG_BAD_PAGENO = "bad page number(s)";
    
//----------------------------------------------------------------------------
// Deep-copies a specified source page to the target location.
// Modified copy of function of pdfmerge.c: we also copy annotations, but
// we skip **link** annotations. In addition we rotate output.
//----------------------------------------------------------------------------
void page_merge(
        mupdf::PdfDocument& doc_des,
        mupdf::PdfDocument& doc_src,
        int page_from,
        int page_to,
        int rotate,
        int links,
        int copy_annots,
        mupdf::PdfGraftMap& graft_map
        )
{
    // list of object types (per page) we want to copy
    static mupdf::PdfObj const known_page_objs[] = {
        mupdf::PdfObj( PDF_NAME(Contents)),
        mupdf::PdfObj( PDF_NAME(Resources)),
        mupdf::PdfObj( PDF_NAME(MediaBox)),
        mupdf::PdfObj( PDF_NAME(CropBox)),
        mupdf::PdfObj( PDF_NAME(BleedBox)),
        mupdf::PdfObj( PDF_NAME(TrimBox)),
        mupdf::PdfObj( PDF_NAME(ArtBox)),
        mupdf::PdfObj( PDF_NAME(Rotate)),
        mupdf::PdfObj( PDF_NAME(UserUnit))
        };
    int known_page_objs_num = sizeof(known_page_objs) / sizeof(known_page_objs[0]);
    int i, n;

    mupdf::PdfObj   page_ref = mupdf::pdf_lookup_page_obj( doc_src, page_from);

    // make new page dict in dest doc
    mupdf::PdfObj   page_dict = mupdf::pdf_new_dict( doc_des, 4);
    mupdf::pdf_dict_put( page_dict, PDF_NAME(Type), PDF_NAME(Page));

    for (i = 0; i < known_page_objs_num; i++)
    {
        mupdf::PdfObj   obj = mupdf::pdf_dict_get_inheritable( page_ref, known_page_objs[i]);
        if (obj.m_internal)
        {
            mupdf::pdf_dict_put(
                    page_dict,
                    known_page_objs[i],
                    mupdf::pdf_graft_mapped_object( graft_map, obj)
                    );
        }
    }

    // Copy the annotations, but skip types Link, Popup, IRT.
    // Remove dict keys P (parent) and Popup from copied annot.
    if (copy_annots)
    {
        mupdf::PdfObj old_annots = mupdf::pdf_dict_get( page_ref, PDF_NAME(Annots));
        if (old_annots.m_internal)
        {
            n = mupdf::pdf_array_len( old_annots);
            mupdf::PdfObj new_annots = mupdf::pdf_dict_put_array( page_dict, PDF_NAME(Annots), n);
            for (i = 0; i < n; i++)
            {
                mupdf::PdfObj o = mupdf::pdf_array_get( old_annots, i);
                if (mupdf::pdf_dict_get( o, PDF_NAME(IRT)).m_internal) continue;
                mupdf::PdfObj subtype = mupdf::pdf_dict_get( o, PDF_NAME(Subtype));
                if (mupdf::pdf_name_eq( subtype, PDF_NAME(Link))) continue;
                if (mupdf::pdf_name_eq( subtype, PDF_NAME(Popup))) continue;
                if (mupdf::pdf_name_eq( subtype, PDF_NAME(Widget)))
                {
                    mupdf::fz_warn( "skipping widget annotation");
                    continue;
                }
                mupdf::pdf_dict_del( o, PDF_NAME(Popup));
                mupdf::pdf_dict_del( o, PDF_NAME(P));
                mupdf::PdfObj copy_o = mupdf::pdf_graft_mapped_object( graft_map, o);
                mupdf::PdfObj annot = mupdf::pdf_new_indirect(
                        doc_des,
                        mupdf::pdf_to_num( copy_o),
                        0
                        );
                mupdf::pdf_array_push( new_annots, annot);
            }
        }
    }
    // rotate the page
    if (rotate != -1)
    {
        mupdf::pdf_dict_put_int( page_dict, PDF_NAME(Rotate), rotate);
    }
    // Now add the page dictionary to dest PDF
    mupdf::PdfObj ref = mupdf::pdf_add_object( doc_des, page_dict);

    // Insert new page at specified location
    mupdf::pdf_insert_page( doc_des, page_to, ref);
}

//-----------------------------------------------------------------------------
// Copy a range of pages (spage, epage) from a source PDF to a specified
// location (apage) of the target PDF.
// If spage > epage, the sequence of source pages is reversed.
//-----------------------------------------------------------------------------
void JM_merge_range( mupdf::PdfDocument& doc_des, mupdf::PdfDocument& doc_src, int spage, int epage, int apage, int rotate, int links, int annots, int show_progress, mupdf::PdfGraftMap& graft_map)
{
    //std::cerr << "JM_merge_range() called...\n";
    int page, afterpage;
    afterpage = apage;
    int counter = 0;  // copied pages counter
    int total = fz_absi(epage - spage) + 1;  // total pages to copy

    if (spage < epage) {
        for (page = spage; page <= epage; page++, afterpage++) {
            page_merge( doc_des, doc_src, page, afterpage, rotate, links, annots, graft_map);
            counter++;
            if (show_progress > 0 && counter % show_progress == 0) {
                fprintf( stderr, "Inserted %i of %i pages.\n", counter, total);
            }
        }
    } else {
        for (page = spage; page >= epage; page--, afterpage++) {
            page_merge( doc_des, doc_src, page, afterpage, rotate, links, annots, graft_map);
            counter++;
            if (show_progress > 0 && counter % show_progress == 0) {
                fprintf( stderr, "Inserted %i of %i pages.\n", counter, total);
            }
        }
    }
}

bool JM_have_operation( mupdf::PdfDocument& pdf)
{
    // Ensure valid journalling state
    if (pdf.m_internal->journal and !mupdf::pdf_undoredo_step(pdf, 0))
    {
        return 0;
    }
    return 1;
}

void ENSURE_OPERATION( mupdf::PdfDocument& pdf)
{
    if ( !JM_have_operation( pdf))
    {
        throw std::runtime_error( "No journalling operation started");
        //RAISEPY( "No journalling operation started", PyExc_RuntimeError)
    }
}


void FzDocument_insert_pdf(
        mupdf::FzDocument& doc,
        mupdf::FzDocument& src,
        int from_page,
        int to_page,
        int start_at,
        int rotate,
        int links,
        int annots,
        int show_progress,
        int final,
        mupdf::PdfGraftMap& graft_map
        )
{
    mupdf::PdfDocument pdfout = mupdf::pdf_specifics( doc);
    mupdf::PdfDocument pdfsrc = mupdf::pdf_specifics( src);
    int outCount = mupdf::fz_count_pages( doc);
    int srcCount = mupdf::fz_count_pages( src);

    // local copies of page numbers
    int fp = from_page, tp = to_page, sa = start_at;

    // normalize page numbers
    fp = std::max(fp, 0);                // -1 = first page
    fp = std::min(fp, srcCount - 1);     // but do not exceed last page

    if (tp < 0) tp = srcCount - 1;  // -1 = last page
    tp = std::min(tp, srcCount - 1);     // but do not exceed last page

    if (sa < 0) sa = outCount;      // -1 = behind last page
    sa = std::min(sa, outCount);         // but that is also the limit

        if (!pdfout.m_internal || !pdfsrc.m_internal) {
            throw std::runtime_error( "source or target not a PDF");
            //RAISEPY(gctx, "source or target not a PDF", PyExc_TypeError);
        }
        ENSURE_OPERATION( pdfout);
        JM_merge_range( pdfout, pdfsrc, fp, tp, sa, rotate, links, annots, show_progress, graft_map);
}

int page_xref(mupdf::FzDocument& this_doc, int pno)
{
    //fz_document *this_doc = (fz_document *) $self;
    int page_count = mupdf::fz_count_pages( this_doc);
    int n = pno;
    while (n < 0) n += page_count;
    mupdf::PdfDocument pdf = mupdf::pdf_specifics( this_doc);
    assert( pdf.m_internal);
    int xref = 0;
    if (n >= page_count) {
        throw std::runtime_error( MSG_BAD_PAGENO);//, PyExc_ValueError);
    }
    xref = mupdf::pdf_to_num( mupdf::pdf_lookup_page_obj( pdf, n));
    return xref;
}

void _newPage(mupdf::PdfDocument& pdf, int pno=-1, float width=595, float height=842)
{
    if (!pdf.m_internal)
    {
        throw std::runtime_error( "is no PDF");
    }
    mupdf::FzRect mediabox( 0, 0, width, height);
    if (pno < -1)
    {
        throw std::runtime_error( "bad page number(s)");  // Should somehow be Python ValueError
    }
    ENSURE_OPERATION( pdf);
    // create /Resources and /Contents objects
    mupdf::PdfObj resources = mupdf::pdf_add_new_dict( pdf, 1);
    mupdf::FzBuffer contents( (::fz_buffer*) nullptr);
    mupdf::PdfObj page_obj = pdf_add_page( pdf, mediabox, 0, resources, contents);
    mupdf::pdf_insert_page( pdf, pno, page_obj);
}

void _newPage(mupdf::FzDocument& self, int pno=-1, float width=595, float height=842)
{
    mupdf::PdfDocument pdf = mupdf::pdf_specifics(self);
    _newPage( pdf, pno, width, height);
}

#include <algorithm>

//------------------------------------------------------------------------
// return the annotation names (list of /NM entries)
//------------------------------------------------------------------------
std::vector< std::string> JM_get_annot_id_list( mupdf::PdfPage& page)
{
    std::vector< std::string> names;
    mupdf::PdfObj annots = mupdf::pdf_dict_get( page.obj(), PDF_NAME(Annots));
    if (!annots.m_internal) return names;
    int n = mupdf::pdf_array_len( annots);
    for (int i = 0; i < n; i++) {
        mupdf::PdfObj annot_obj = mupdf::pdf_array_get( annots, i);
        mupdf::PdfObj name = mupdf::pdf_dict_gets( annot_obj, "NM");
        if (name.m_internal)
        {
            names.push_back( mupdf::pdf_to_text_string( name));
        }
    }
    return names;
}


//------------------------------------------------------------------------
// Add a unique /NM key to an annotation or widget.
// Append a number to 'stem' such that the result is a unique name.
//------------------------------------------------------------------------
static char JM_annot_id_stem[50] = "fitz";
void JM_add_annot_id( mupdf::PdfAnnot& annot, const char *stem)
{
    mupdf::PdfPage page = mupdf::pdf_annot_page( annot);
    mupdf::PdfObj annot_obj = mupdf::pdf_annot_obj( annot);
    std::vector< std::string> names = JM_get_annot_id_list( page);
    int i = 0;
    char* stem_id = nullptr;
    while (1)
    {
        free(stem_id);
        asprintf( &stem_id,  "%s-%s%d", JM_annot_id_stem, stem, i);
        //std::cout << "stem_id=" << stem_id << "\n";
        if (std::find( names.begin(), names.end(), stem_id) == names.end())
        {
            break;
        }
        i += 1;
    }
    const char *response = stem_id;
    mupdf::PdfObj name = mupdf::pdf_new_string( response, strlen(response));
    free(stem_id);
    mupdf::pdf_dict_puts( annot_obj, "NM", name);
    page.m_internal->doc->resynth_required = 0;
}

//----------------------------------------------------------------
// page add_caret_annot
//----------------------------------------------------------------
mupdf::PdfAnnot _add_caret_annot( mupdf::PdfPage& page, mupdf::FzPoint& point)
{
    mupdf::PdfAnnot annot = mupdf::pdf_create_annot( page, ::PDF_ANNOT_CARET);
    if (1)
    {
        mupdf::FzPoint p = point;
        mupdf::FzRect r = mupdf::pdf_annot_rect( annot);
        r = mupdf::fz_make_rect(p.x, p.y, p.x + r.x1 - r.x0, p.y + r.y1 - r.y0);
        mupdf::pdf_set_annot_rect( annot, r);
    }
    mupdf::pdf_update_annot( annot);
    JM_add_annot_id( annot, "A");
    return annot;
}

mupdf::PdfAnnot _add_caret_annot( mupdf::FzPage& page, mupdf::FzPoint& point)
{
    mupdf::PdfPage  pdf_page = mupdf::pdf_page_from_fz_page( page);
    return _add_caret_annot( pdf_page, point);
}

const char* Tools_parse_da( mupdf::PdfAnnot& this_annot)
{
    const char *da_str = NULL;
    mupdf::PdfObj this_annot_obj = mupdf::pdf_annot_obj( this_annot);
    mupdf::PdfDocument pdf = mupdf::pdf_get_bound_document( this_annot_obj);
    try
    {
        mupdf::PdfObj da = mupdf::pdf_dict_get_inheritable( this_annot_obj, PDF_NAME(DA));
        if (!da.m_internal)
        {
            mupdf::PdfObj trailer = mupdf::pdf_trailer( pdf);
            da = mupdf::pdf_dict_getl(
                    &trailer,
                    PDF_NAME(Root),
                    PDF_NAME(AcroForm),
                    PDF_NAME(DA),
                    nullptr
                    );
        }
        da_str = mupdf::pdf_to_text_string( da);
    }
    catch( std::exception& e)
    {
        return NULL;
    }
    return da_str;
}

//----------------------------------------------------------------------------
// Turn fz_buffer into a Python bytes object
//----------------------------------------------------------------------------
std::string JM_BinFromBuffer( mupdf::FzBuffer& buffer)
{
    if (!buffer.m_internal) return nullptr;
    unsigned char *c = NULL;
    size_t len = mupdf::fz_buffer_storage( buffer, &c);
    return std::string( (char*) c, len);
}

std::string Annot_getAP( mupdf::PdfAnnot& annot)
{
    //std::cerr << __FILE__ << __LINE__ << ": annot.m_internal=" << annot.m_internal << "\n";
    mupdf::PdfObj annot_obj = mupdf::pdf_annot_obj( annot);
    mupdf::PdfObj ap = mupdf::pdf_dict_getl(
            &annot_obj,
            PDF_NAME(AP),
            PDF_NAME(N),
            nullptr
            );
    if (mupdf::pdf_is_stream( ap))
    {
        mupdf::FzBuffer res = mupdf::pdf_load_stream( ap);
        if (res.m_internal)
        {
            std::string r = JM_BinFromBuffer( res);
            return r;
        }
    }
    return "";
}

void Tools_update_da(struct mupdf::PdfAnnot& this_annot, const char *da_str)
{
    std::cerr << "Tools_update_da() ***\n";
    abort();
    mupdf::PdfObj this_annot_obj = mupdf::pdf_annot_obj( this_annot);
    mupdf::pdf_dict_put_text_string( this_annot_obj, PDF_NAME(DA), da_str);
    mupdf::pdf_dict_del( this_annot_obj, PDF_NAME(DS)); /* not supported */
    mupdf::pdf_dict_del( this_annot_obj, PDF_NAME(RC)); /* not supported */
}

static int
JM_FLOAT_ITEM(PyObject *obj, Py_ssize_t idx, double *result)
{
    PyObject *temp = PySequence_ITEM(obj, idx);
    if (!temp) return 1;
    *result = PyFloat_AsDouble(temp);
    Py_DECREF(temp);
    if (PyErr_Occurred()) {
        PyErr_Clear();
        return 1;
    }
    return 0;
}


mupdf::FzPoint JM_point_from_py(PyObject *p)
{
    fz_point p0 = fz_make_point(FZ_MIN_INF_RECT, FZ_MIN_INF_RECT);
    double x, y;

    if (!p || !PySequence_Check(p) || PySequence_Size(p) != 2)
        return p0;

    if (JM_FLOAT_ITEM(p, 0, &x) == 1) return p0;
    if (JM_FLOAT_ITEM(p, 1, &y) == 1) return p0;
    if (x < FZ_MIN_INF_RECT) x = FZ_MIN_INF_RECT;
    if (y < FZ_MIN_INF_RECT) y = FZ_MIN_INF_RECT;
    if (x > FZ_MAX_INF_RECT) x = FZ_MAX_INF_RECT;
    if (y > FZ_MAX_INF_RECT) y = FZ_MAX_INF_RECT;

    return mupdf::fz_make_point(x, y);
}

void Document_extend_toc_items(mupdf::PdfDocument& pdf, PyObject *items)
{
    abort();
}

//-----------------------------------------------------------------------------
// PySequence from fz_rect
//-----------------------------------------------------------------------------
static PyObject *
JM_py_from_rect(fz_rect r)
{
    return Py_BuildValue("ffff", r.x0, r.y0, r.x1, r.y1);
}

//----------------------------------------------------------------
// annotation rectangle
//----------------------------------------------------------------
mupdf::FzRect Annot_rect(mupdf::PdfAnnot& annot)
{
    mupdf::FzRect rect = mupdf::pdf_bound_annot( annot);
    return rect;
}

PyObject* Annot_rect2(mupdf::PdfAnnot& annot)
{
    mupdf::FzRect rect = mupdf::pdf_bound_annot( annot);
    //return JM_py_from_rect( *rect.internal());
    return JM_py_from_rect( *(::fz_rect*) &rect.x0);
}

PyObject* Annot_rect3(mupdf::PdfAnnot& annot)
{
    fz_rect rect = mupdf::ll_pdf_bound_annot( annot.m_internal);
    return JM_py_from_rect( rect);
}

//-----------------------------------------------------------------------------
// PySequence to fz_rect. Default: infinite rect
//-----------------------------------------------------------------------------
static fz_rect
JM_rect_from_py(PyObject *r)
{
    if (!r || !PySequence_Check(r) || PySequence_Size(r) != 4)
        return fz_infinite_rect;
    Py_ssize_t i;
    double f[4];

    for (i = 0; i < 4; i++) {
        if (JM_FLOAT_ITEM(r, i, &f[i]) == 1) return fz_infinite_rect;
        if (f[i] < FZ_MIN_INF_RECT) f[i] = FZ_MIN_INF_RECT;
        if (f[i] > FZ_MAX_INF_RECT) f[i] = FZ_MAX_INF_RECT;
    }

    return fz_make_rect((float) f[0], (float) f[1], (float) f[2], (float) f[3]);
}

//-----------------------------------------------------------------------------
// PySequence to fz_matrix. Default: fz_identity
//-----------------------------------------------------------------------------
static fz_matrix
JM_matrix_from_py(PyObject *m)
{
    Py_ssize_t i;
    double a[6];

    if (!m || !PySequence_Check(m) || PySequence_Size(m) != 6)
        return fz_identity;

    for (i = 0; i < 6; i++)
        if (JM_FLOAT_ITEM(m, i, &a[i]) == 1) return fz_identity;

    return fz_make_matrix((float) a[0], (float) a[1], (float) a[2], (float) a[3], (float) a[4], (float) a[5]);
}

PyObject *util_transform_rect(PyObject *rect, PyObject *matrix)
{
	return JM_py_from_rect(::fz_transform_rect(JM_rect_from_py(rect), JM_matrix_from_py(matrix)));
}

//----------------------------------------------------------------------------
// return normalized /Rotate value:one of 0, 90, 180, 270
//----------------------------------------------------------------------------
int JM_norm_rotation(int rotate)
{
    while (rotate < 0) rotate += 360;
    while (rotate >= 360) rotate -= 360;
    if (rotate % 90 != 0) return 0;
    return rotate;
}


//----------------------------------------------------------------------------
// return a PDF page's /Rotate value: one of (0, 90, 180, 270)
//----------------------------------------------------------------------------
int JM_page_rotation(mupdf::PdfPage& page)
{
    int rotate = 0;
    rotate = mupdf::pdf_to_int(
            mupdf::pdf_dict_get_inheritable( page.obj(), PDF_NAME(Rotate))
            );
    rotate = JM_norm_rotation(rotate);
    return rotate;
}


//----------------------------------------------------------------------------
// return a PDF page's MediaBox
//----------------------------------------------------------------------------
mupdf::FzRect JM_mediabox( mupdf::PdfObj& page_obj)
{
   mupdf::FzRect mediabox, page_mediabox;

    mediabox = mupdf::pdf_to_rect(
            mupdf::pdf_dict_get_inheritable( page_obj, PDF_NAME(MediaBox))
            );
    if (mupdf::fz_is_empty_rect(mediabox) || mupdf::fz_is_infinite_rect(mediabox))
    {
        mediabox.x0 = 0;
        mediabox.y0 = 0;
        mediabox.x1 = 612;
        mediabox.y1 = 792;
    }

    page_mediabox.x0 = mupdf::fz_min(mediabox.x0, mediabox.x1);
    page_mediabox.y0 = mupdf::fz_min(mediabox.y0, mediabox.y1);
    page_mediabox.x1 = mupdf::fz_max(mediabox.x0, mediabox.x1);
    page_mediabox.y1 = mupdf::fz_max(mediabox.y0, mediabox.y1);

    if (page_mediabox.x1 - page_mediabox.x0 < 1 ||
        page_mediabox.y1 - page_mediabox.y0 < 1)
        page_mediabox = fz_unit_rect;

    return page_mediabox;
}


//----------------------------------------------------------------------------
// return a PDF page's CropBox
//----------------------------------------------------------------------------
mupdf::FzRect JM_cropbox( mupdf::PdfObj& page_obj)
{
    mupdf::FzRect mediabox = JM_mediabox( page_obj);
    mupdf::FzRect cropbox = mupdf::pdf_to_rect(
                mupdf::pdf_dict_get_inheritable( page_obj, PDF_NAME(CropBox))
                );
    if (mupdf::fz_is_infinite_rect(cropbox) || mupdf::fz_is_empty_rect(cropbox))
        cropbox = mediabox;
    float y0 = mediabox.y1 - cropbox.y1;
    float y1 = mediabox.y1 - cropbox.y0;
    cropbox.y0 = y0;
    cropbox.y1 = y1;
    return cropbox;
}


//----------------------------------------------------------------------------
// calculate width and height of the UNROTATED page
//----------------------------------------------------------------------------
mupdf::FzPoint JM_cropbox_size( mupdf::PdfObj& page_obj)
{
    mupdf::FzPoint size;
    mupdf::FzRect rect = JM_cropbox( page_obj);
    float w = (rect.x0 < rect.x1 ? rect.x1 - rect.x0 : rect.x0 - rect.x1);
    float h = (rect.y0 < rect.y1 ? rect.y1 - rect.y0 : rect.y0 - rect.y1);
    size = mupdf::fz_make_point(w, h);
    return size;
}


//----------------------------------------------------------------------------
// calculate page rotation matrices
//----------------------------------------------------------------------------
mupdf::FzMatrix JM_rotate_page_matrix(mupdf::PdfPage& page)
{
    if (!page.m_internal) return fz_identity;  // no valid pdf page given
    int rotation = JM_page_rotation( page);
    if (rotation == 0) return fz_identity;  // no rotation
    mupdf::FzMatrix m;
    auto po = page.obj();
    mupdf::FzPoint cb_size = JM_cropbox_size( po);
    float w = cb_size.x;
    float h = cb_size.y;
    if (rotation == 90)
        m = mupdf::fz_make_matrix(0, 1, -1, 0, h, 0);
    else if (rotation == 180)
        m = mupdf::fz_make_matrix(-1, 0, 0, -1, w, h);
    else
        m = mupdf::fz_make_matrix(0, -1, 1, 0, 0, w);
    return m;
}


mupdf::FzMatrix JM_derotate_page_matrix(mupdf::PdfPage& page)
{  // just the inverse of rotation
    return mupdf::fz_invert_matrix(JM_rotate_page_matrix( page));
}

//-----------------------------------------------------------------------------
// PySequence from fz_matrix
//-----------------------------------------------------------------------------
static PyObject *
JM_py_from_matrix(mupdf::FzMatrix m)
{
    return Py_BuildValue("ffffff", m.a, m.b, m.c, m.d, m.e, m.f);
}

PyObject *Page_derotate_matrix(mupdf::PdfPage& pdfpage)
{
    if (!pdfpage.m_internal) return JM_py_from_matrix(fz_identity);
    return JM_py_from_matrix(JM_derotate_page_matrix( pdfpage));
}

PyObject *Page_derotate_matrix(mupdf::FzPage& page)
{
    mupdf::PdfPage pdf_page = mupdf::pdf_page_from_fz_page( page);
    return Page_derotate_matrix( pdf_page);
}

static int LIST_APPEND_DROP(PyObject *list, PyObject *item)
{
    if (!list || !PyList_Check(list) || !item) return -2;
    int rc = PyList_Append(list, item);
    Py_DECREF(item);
    return rc;
}

//------------------------------------------------------------------------
// return the xrefs and /NM ids of a page's annots, links and fields
//------------------------------------------------------------------------
PyObject *JM_get_annot_xref_list( const mupdf::PdfObj& page_obj)
{
    PyObject *names = PyList_New(0);
    //pdf_obj *id, *annot_obj = NULL;
    mupdf::PdfObj annots = mupdf::pdf_dict_get( page_obj, PDF_NAME(Annots));
    if (!annots.m_internal) return names;
    int n = mupdf::pdf_array_len( annots);
    for (int i = 0; i < n; i++) {
        mupdf::PdfObj annot_obj = pdf_array_get( annots, i);
        int xref = mupdf::pdf_to_num( annot_obj);
        mupdf::PdfObj subtype = mupdf::pdf_dict_get( annot_obj, PDF_NAME(Subtype));
        int type = PDF_ANNOT_UNKNOWN;
        if (subtype.m_internal) {
            const char *name = mupdf::pdf_to_name( subtype);
            type = mupdf::pdf_annot_type_from_string( name);
        }
        mupdf::PdfObj id = mupdf::pdf_dict_gets( annot_obj, "NM");
        LIST_APPEND_DROP(names, Py_BuildValue("iis", xref, type, mupdf::pdf_to_text_string( id)));
    }
    return names;
}

PyObject *JM_get_annot_xref_list2( mupdf::PdfPage& page)
{
    mupdf::PdfObj   page_obj = page.obj();
    return JM_get_annot_xref_list( page_obj);
}

PyObject *JM_get_annot_xref_list2( mupdf::FzPage& page)
{
    mupdf::PdfPage pdf_page = mupdf::pdf_page_from_fz_page( page);
    return JM_get_annot_xref_list2( pdf_page);
}

static const char* MSG_IS_NO_PDF = "is no PDF";
static const char* MSG_BAD_XREF = "bad xref";
#define EMPTY_STRING PyUnicode_FromString("")
#define JM_StrAsChar(x) (char *)PyUnicode_AsUTF8(x)

mupdf::FzBuffer JM_object_to_buffer( const mupdf::PdfObj& what, int compress, int ascii)
{
    mupdf::FzBuffer res = mupdf::fz_new_buffer( 512);
    mupdf::FzOutput out( res);
    mupdf::pdf_print_obj( out, what, compress, ascii);
    mupdf::fz_terminate_buffer( res);
    return res;
}

PyObject *JM_EscapeStrFromBuffer( mupdf::FzBuffer& buff)
{
    if (!buff.m_internal) return EMPTY_STRING;
    unsigned char *s = NULL;
    size_t len = mupdf::fz_buffer_storage( buff, &s);
    PyObject *val = PyUnicode_DecodeRawUnicodeEscape((const char *) s, (Py_ssize_t) len, "replace");
    if (!val) {
        val = EMPTY_STRING;
        PyErr_Clear();
    }
    return val;
}

PyObject* xref_object(mupdf::PdfDocument& pdf, int xref, int compressed=0, int ascii=0)
{
    if (!pdf.m_internal) throw std::runtime_error( MSG_IS_NO_PDF);
    int xreflen = mupdf::pdf_xref_len( pdf);
    if (( xref < 1 || xref >= xreflen) and xref != -1) 
    {
        throw std::runtime_error( MSG_BAD_XREF);
    }
    mupdf::PdfObj obj = (xref > 0) ? mupdf::pdf_load_object( pdf, xref) : mupdf::pdf_trailer( pdf);
    mupdf::FzBuffer res = JM_object_to_buffer( mupdf::pdf_resolve_indirect( obj), compressed, ascii);
    PyObject* text = JM_EscapeStrFromBuffer( res);
    return text;
}

PyObject* xref_object(mupdf::FzDocument& document, int xref, int compressed=0, int ascii=0)
{
    mupdf::PdfDocument pdf = mupdf::pdf_document_from_fz_document( document);
    return xref_object( pdf, xref, compressed, ascii);
}


//-----------------------------------------------------------------------------
// perform some cleaning if we have /EmbeddedFiles:
// (1) remove any /Limits if /Names exists
// (2) remove any empty /Collection
// (3) set /PageMode/UseAttachments
//-----------------------------------------------------------------------------
void JM_embedded_clean( mupdf::PdfDocument& pdf)
{
    mupdf::PdfObj root = mupdf::pdf_dict_get( mupdf::pdf_trailer( pdf), PDF_NAME(Root));

    // remove any empty /Collection entry
    mupdf::PdfObj coll = mupdf::pdf_dict_get( root, PDF_NAME(Collection));
    if (coll.m_internal && mupdf::pdf_dict_len( coll) == 0)
        mupdf::pdf_dict_del( root, PDF_NAME(Collection));

    mupdf::PdfObj efiles = mupdf::pdf_dict_getl(
            &root,
            PDF_NAME(Names),
            PDF_NAME(EmbeddedFiles),
            PDF_NAME(Names),
            nullptr
            );
    if (efiles.m_internal) {
        mupdf::pdf_dict_put_name( root, PDF_NAME(PageMode), "UseAttachments");
    }
}

//------------------------------------------------------------------------
// Store ID in PDF trailer
//------------------------------------------------------------------------
void JM_ensure_identity( mupdf::PdfDocument& pdf)
{
    unsigned char rnd[16];
    mupdf::PdfObj id = mupdf::pdf_dict_get( mupdf::pdf_trailer( pdf), PDF_NAME(ID));
    if (!id.m_internal) {
        mupdf::fz_memrnd( rnd, nelem(rnd));
        id = mupdf::pdf_dict_put_array( mupdf::pdf_trailer( pdf), PDF_NAME(ID), 2);
        mupdf::pdf_array_push( id, mupdf::pdf_new_string( (char *) rnd + 0, nelem(rnd)));
        mupdf::pdf_array_push( id, mupdf::pdf_new_string( (char *) rnd + 0, nelem(rnd)));
    }
}

static PyObject *JM_Exc_CurrentException = nullptr;
#define RAISEPY(context, msg, exc) {JM_Exc_CurrentException=exc; fz_throw(context, FZ_ERROR_GENERIC, msg);}

static int64_t
JM_bytesio_tell(fz_context *ctx, void *opaque)
{  // returns bio.tell() -> int
    PyObject *bio = (PyObject*) opaque, *rc = NULL, *name = NULL;
    int64_t pos = 0;
    fz_try(ctx) {
        name = PyUnicode_FromString("tell");
        rc = PyObject_CallMethodObjArgs(bio, name, NULL);
        if (!rc) {
            RAISEPY(ctx, "could not tell Py file obj", PyErr_Occurred());
        }
        pos = (int64_t) PyLong_AsUnsignedLongLong(rc);
    }
    fz_always(ctx) {
        Py_XDECREF(name);
        Py_XDECREF(rc);
        PyErr_Clear();
    }
    fz_catch(ctx) {
        fz_rethrow(ctx);
    }
    return pos;
}

static void
JM_bytesio_seek(fz_context *ctx, void *opaque, int64_t off, int whence)
{  // bio.seek(off, whence=0)
    PyObject *bio = (PyObject*) opaque, *rc = NULL, *name = NULL, *pos = NULL;
    fz_try(ctx) {
        name = PyUnicode_FromString("seek");
        pos = PyLong_FromUnsignedLongLong((unsigned long long) off);
        PyObject_CallMethodObjArgs(bio, name, pos, whence, NULL);
        rc = PyErr_Occurred();
        if (rc) {
            RAISEPY(ctx, "could not seek Py file obj", rc);
        }
    }
    fz_always(ctx) {
        Py_XDECREF(rc);
        Py_XDECREF(name);
        Py_XDECREF(pos);
        PyErr_Clear();
    }
    fz_catch(ctx) {
        fz_rethrow(ctx);
    }
}

//-------------------------------------
// fz_output for Python file objects
//-------------------------------------
static void
JM_bytesio_write(fz_context *ctx, void *opaque, const void *data, size_t len)
{  // bio.write(bytes object)
    PyObject *bio = (PyObject*) opaque, *b, *name, *rc;
    fz_try(ctx){
        b = PyBytes_FromStringAndSize((const char *) data, (Py_ssize_t) len);
        name = PyUnicode_FromString("write");
        PyObject_CallMethodObjArgs(bio, name, b, NULL);
        rc = PyErr_Occurred();
        if (rc) {
            RAISEPY(ctx, "could not write to Py file obj", rc);
        }
    }
    fz_always(ctx) {
        Py_XDECREF(b);
        Py_XDECREF(name);
        Py_XDECREF(rc);
        PyErr_Clear();
    }
    fz_catch(ctx) {
        fz_rethrow(ctx);
    }
}

static void
JM_bytesio_truncate(fz_context *ctx, void *opaque)
{  // bio.truncate(bio.tell()) !!!
    PyObject *bio = (PyObject*) opaque, *trunc = NULL, *tell = NULL, *rctell= NULL, *rc = NULL;
    fz_try(ctx) {
        trunc = PyUnicode_FromString("truncate");
        tell = PyUnicode_FromString("tell");
        rctell = PyObject_CallMethodObjArgs(bio, tell, NULL);
        PyObject_CallMethodObjArgs(bio, trunc, rctell, NULL);
        rc = PyErr_Occurred();
        if (rc) {
            RAISEPY(ctx, "could not truncate Py file obj", rc);
        }
    }
    fz_always(ctx) {
        Py_XDECREF(tell);
        Py_XDECREF(trunc);
        Py_XDECREF(rc);
        Py_XDECREF(rctell);
        PyErr_Clear();
    }
    fz_catch(ctx) {
        fz_rethrow(ctx);
    }
}

/*
mupdf::FzOutput
JM_new_output_fileptr( PyObject *bio)
{
    mupdf::FzOutput out( 0, bio, JM_bytesio_write, NULL, NULL);
    out.m_internal->seek = JM_bytesio_seek;
    out.m_internal->tell = JM_bytesio_tell;
    out.m_internal->truncate = JM_bytesio_truncate;
    return out;
}
*/
/* Deliberately returns low-level fz_output*, because mupdf::FzOutput is not
copyable. */
fz_output *
JM_new_output_fileptr(PyObject *bio)
{
    fz_output *out = mupdf::ll_fz_new_output( 0, bio, JM_bytesio_write, NULL, NULL);
    out->seek = JM_bytesio_seek;
    out->tell = JM_bytesio_tell;
    out->truncate = JM_bytesio_truncate;
    return out;
}


void Document_save(
        mupdf::PdfDocument& pdf,
        PyObject *filename,
        int garbage,
        int clean,
        int deflate,
        int deflate_images,
        int deflate_fonts,
        int incremental,
        int ascii,
        int expand,
        int linear,
        int no_new_id,
        int appearance,
        int pretty,
        int encryption,
        int permissions,
        char *owner_pw,
        char *user_pw
        )
{
    mupdf::PdfWriteOptions opts;// = pdf_default_write_options;
    opts.do_incremental     = incremental;
    opts.do_ascii           = ascii;
    opts.do_compress        = deflate;
    opts.do_compress_images = deflate_images;
    opts.do_compress_fonts  = deflate_fonts;
    opts.do_decompress      = expand;
    opts.do_garbage         = garbage;
    opts.do_pretty          = pretty;
    opts.do_linear          = linear;
    opts.do_clean           = clean;
    opts.do_sanitize        = clean;
    opts.dont_regenerate_id = no_new_id;
    opts.do_appearance      = appearance;
    opts.do_encrypt         = encryption;
    opts.permissions        = permissions;
    if (owner_pw) {
        memcpy(&opts.opwd_utf8, owner_pw, strlen(owner_pw)+1);
    } else if (user_pw) {
        memcpy(&opts.opwd_utf8, user_pw, strlen(user_pw)+1);
    }
    if (user_pw) {
        memcpy(&opts.upwd_utf8, user_pw, strlen(user_pw)+1);
    }
    fz_output *out = NULL;
    if (!pdf.m_internal) throw std::runtime_error( MSG_IS_NO_PDF);
    pdf.m_internal->resynth_required = 0;
    JM_embedded_clean( pdf);
    if (no_new_id == 0) {
        JM_ensure_identity( pdf);
    }
    if (PyUnicode_Check(filename)) {
        mupdf::pdf_save_document( pdf, JM_StrAsChar(filename), opts);
    } else {
        out = JM_new_output_fileptr( filename);
        mupdf::FzOutput out2( out);
        mupdf::pdf_write_document( pdf, out2, opts);
    }
}

void Document_save(
        mupdf::FzDocument& document,
        PyObject *filename,
        int garbage,
        int clean,
        int deflate,
        int deflate_images,
        int deflate_fonts,
        int incremental,
        int ascii,
        int expand,
        int linear,
        int no_new_id,
        int appearance,
        int pretty,
        int encryption,
        int permissions,
        char *owner_pw,
        char *user_pw
        )
{
    mupdf::PdfDocument pdf = mupdf::pdf_document_from_fz_document( document);
    Document_save(
            pdf,
            filename,
            garbage,
            clean,
            deflate,
            deflate_images,
            deflate_fonts,
            incremental,
            ascii,
            expand,
            linear,
            no_new_id,
            appearance,
            pretty,
            encryption,
            permissions,
            owner_pw,
            user_pw
            );
}

bool Link_is_external( mupdf::FzLink& this_link)
{
    const char* uri = this_link.uri();
    if (!uri) return false;
    return mupdf::fz_is_external_link( uri);
}

mupdf::FzLink Link_next( mupdf::FzLink& this_link)
{
    return this_link.next();
}

#define ASSERT_PDF(cond) if (!cond.m_internal) throw std::runtime_error( MSG_IS_NO_PDF)


//-----------------------------------------------------------------------------
// create PDF object from given string (new in v1.14.0: MuPDF dropped it)
//-----------------------------------------------------------------------------
mupdf::PdfObj JM_pdf_obj_from_str( const mupdf::PdfDocument& doc, char *src)
{
    mupdf::FzStream stream = mupdf::fz_open_memory( (unsigned char *)src, strlen(src));
    mupdf::PdfLexbuf lexbuf( PDF_LEXBUF_SMALL);
    mupdf::PdfObj result = mupdf::pdf_parse_stm_obj( doc, stream, lexbuf);
    mupdf::pdf_lexbuf_fin( lexbuf);
    return result;
}

/*********************************************************************/
// Page._addAnnot_FromString
// Add new links provided as an array of string object definitions.
/*********************************************************************/
PyObject *Page_addAnnot_FromString( mupdf::PdfPage& page, PyObject *linklist)
{
    //pdf_obj *annots, *annot, *ind_obj;
    //pdf_page *page = pdf_page_from_fz_page(gctx, (fz_page *) $self);
    PyObject *txtpy = NULL;
    char *text = NULL;
    int lcount = (int) PySequence_Size(linklist); // link count
    if (lcount < 1) Py_RETURN_NONE;
    int i = -1;
    fz_var(text);

    try
    {
    // insert links from the provided sources
        ASSERT_PDF(page);
        if (!mupdf::pdf_dict_get( page.obj(), PDF_NAME(Annots)).m_internal) {
            mupdf::pdf_dict_put_array( page.obj(), PDF_NAME(Annots), lcount);
        }
        mupdf::PdfObj annots = mupdf::pdf_dict_get( page.obj(), PDF_NAME(Annots));
        for (i = 0; i < lcount; i++) {
            text = NULL;
            txtpy = PySequence_ITEM(linklist, (Py_ssize_t) i);
            text = JM_StrAsChar(txtpy);
            Py_CLEAR(txtpy);
            if (!text) {
                PySys_WriteStderr("skipping bad link / annot item %i.\n", i);
                continue;
            }
            try {
                mupdf::PdfObj annot = mupdf::pdf_add_object(
                        page.doc(),
                        JM_pdf_obj_from_str( page.doc(), text)
                        );
                mupdf::PdfObj ind_obj = mupdf::pdf_new_indirect(
                        page.doc(),
                        mupdf::pdf_to_num( annot),
                        0
                        );
                mupdf::pdf_array_push( annots, ind_obj);
            }
            catch( std::exception& e) {
                PySys_WriteStderr("skipping bad link / annot item %i.\n", i);
            }
        }
    }
    catch( std::exception& e) {
        PyErr_Clear();
        return NULL;
    }
    Py_RETURN_NONE;
}

PyObject *Page_addAnnot_FromString( mupdf::FzPage& page, PyObject *linklist)
{
    mupdf::PdfPage pdf_page = mupdf::pdf_page_from_fz_page( page);
    return Page_addAnnot_FromString( pdf_page, linklist);
}

int page_count( mupdf::FzDocument& document)
{
    return mupdf::fz_count_pages( document);
}

int page_count( mupdf::PdfDocument& pdf)
{
    mupdf::FzDocument document = pdf.super();
    return page_count( document);
}

static PyObject* page_annot_xrefs( mupdf::FzDocument& document, mupdf::PdfDocument& pdf, int pno)
{
    int page_count = mupdf::fz_count_pages( document);
    int n = pno;
    while (n < 0) n += page_count;
    PyObject *annots = NULL;
    if (n >= page_count) {
        throw std::runtime_error( MSG_BAD_PAGENO);
    }
    ASSERT_PDF(pdf);
    annots = JM_get_annot_xref_list( mupdf::pdf_lookup_page_obj( pdf, n));
    return annots;
}

PyObject* page_annot_xrefs( mupdf::FzDocument& document, int pno)
{
    mupdf::PdfDocument pdf = mupdf::pdf_specifics( document);
    return page_annot_xrefs( document, pdf, pno);
}

PyObject* page_annot_xrefs( mupdf::PdfDocument& pdf, int pno)
{
    mupdf::FzDocument document = pdf.super();
    return page_annot_xrefs( document, pdf, pno);
}

int ll_fz_absi( int i)
{
    return fz_absi(i);
}

%}

void page_merge(
        mupdf::PdfDocument& doc_des,
        mupdf::PdfDocument& doc_src,
        int page_from,
        int page_to,
        int rotate,
        int links,
        int copy_annots,
        mupdf::PdfGraftMap& graft_map
        );

void JM_merge_range( mupdf::PdfDocument& doc_des, mupdf::PdfDocument& doc_src, int spage, int epage, int apage, int rotate, int links, int annots, int show_progress, mupdf::PdfGraftMap& graft_map);

void FzDocument_insert_pdf(
        mupdf::FzDocument& doc,
        mupdf::FzDocument& src,
        int from_page,
        int to_page,
        int start_at,
        int rotate,
        int links,
        int annots,
        int show_progress,
        int final,
        mupdf::PdfGraftMap& graft_map
        );

int page_xref(mupdf::FzDocument& this_doc, int pno);
void _newPage(mupdf::FzDocument& self, int pno=-1, float width=595, float height=842);
void _newPage(mupdf::PdfDocument& self, int pno=-1, float width=595, float height=842);
void JM_add_annot_id( mupdf::PdfAnnot& annot, const char *stem);
std::vector< std::string> JM_get_annot_id_list( mupdf::PdfPage& page);
mupdf::PdfAnnot _add_caret_annot( mupdf::PdfPage& self, mupdf::FzPoint& point);
mupdf::PdfAnnot _add_caret_annot( mupdf::FzPage& self, mupdf::FzPoint& point);
const char* Tools_parse_da( mupdf::PdfAnnot& this_annot);
std::string Annot_getAP( mupdf::PdfAnnot& annot);
mupdf::FzPoint JM_point_from_py(PyObject *p);
mupdf::FzRect Annot_rect(mupdf::PdfAnnot& annot);
PyObject *util_transform_rect(PyObject *rect, PyObject *matrix);
PyObject* Annot_rect2(mupdf::PdfAnnot& annot);
PyObject* Annot_rect3(mupdf::PdfAnnot& annot);
PyObject *Page_derotate_matrix(mupdf::PdfPage& pdfpage);
PyObject *Page_derotate_matrix(mupdf::FzPage& pdfpage);
PyObject *JM_get_annot_xref_list( const mupdf::PdfObj& page_obj);
PyObject *JM_get_annot_xref_list2( mupdf::PdfPage& page);
PyObject *JM_get_annot_xref_list2( mupdf::FzPage& page);
PyObject* xref_object(mupdf::PdfDocument& pdf, int xref, int compressed=0, int ascii=0);
PyObject* xref_object(mupdf::FzDocument& document, int xref, int compressed=0, int ascii=0);

void Document_save(
        mupdf::PdfDocument& pdf,
        PyObject *filename,
        int garbage,
        int clean,
        int deflate,
        int deflate_images,
        int deflate_fonts,
        int incremental,
        int ascii,
        int expand,
        int linear,
        int no_new_id,
        int appearance,
        int pretty,
        int encryption,
        int permissions,
        char *owner_pw,
        char *user_pw
        );

void Document_save(
        mupdf::FzDocument& document,
        PyObject *filename,
        int garbage,
        int clean,
        int deflate,
        int deflate_images,
        int deflate_fonts,
        int incremental,
        int ascii,
        int expand,
        int linear,
        int no_new_id,
        int appearance,
        int pretty,
        int encryption,
        int permissions,
        char *owner_pw,
        char *user_pw
        );

bool Link_is_external( mupdf::FzLink& this_link);
PyObject *Page_addAnnot_FromString( mupdf::PdfPage& page, PyObject *linklist);
PyObject *Page_addAnnot_FromString( mupdf::FzPage& page, PyObject *linklist);
mupdf::FzLink Link_next( mupdf::FzLink& this_link);
int page_count( mupdf::FzDocument& document);
int page_count( mupdf::PdfDocument& pdf);

PyObject* page_annot_xrefs( mupdf::PdfDocument& pdf, int pno);
PyObject* page_annot_xrefs( mupdf::FzDocument& document, int pno);

int ll_fz_absi( int i);
