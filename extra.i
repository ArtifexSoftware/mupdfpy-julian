%module fitz_extra

%{
#include "mupdf/classes2.h"
    
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
                //PySys_WriteStdout("Inserted %i of %i pages.\n", counter, total);
            }
        }
    } else {
        for (page = spage; page >= epage; page--, afterpage++) {
            page_merge( doc_des, doc_src, page, afterpage, rotate, links, annots, graft_map);
            counter++;
            if (show_progress > 0 && counter % show_progress == 0) {
                //PySys_WriteStdout("Inserted %i of %i pages.\n", counter, total);
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
        const char* MSG_BAD_PAGENO = "bad page number(s)";
        throw std::runtime_error( MSG_BAD_PAGENO);//, PyExc_ValueError);
    }
    xref = mupdf::pdf_to_num( mupdf::pdf_lookup_page_obj( pdf, n));
    return xref;
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

int ll_fz_absi( int i);
