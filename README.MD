



Main objective: Be able to process a debt prospectus both in html or pdf format with a small LLM and be able to generate a Bond Debt Taxonomy Document.

## Table of Contents
- [Prospectus Sources and file formats:](#prospectus-sources-and-file-formats)
- [Main Blocks](#main-blocks)
- [Small LLM](#small-llm)
- [Objective SEC Edgar](#objective-sec-edgar)
- [TODO](#todo)
- [Page Breaks of prospectus](#page-breaks-of-prospectus)
  - [Examples Used](#examples-used)
- [Formatting of Table of Contents](#formatting-of-table-of-contents)
  - [Example 1](#example-1)
  - [Example 2](#example-2)
  - [Example 3](#example-3)
  - [Example 4](#example-4)
- [Resources](#resources)


# Prospectus Sources and file formats:

- SEC EDGAR: htm/html/mhtml
- Luxembourg Stock Exchange: PDF
- [Singapore Stock Exchange](https://www.sgx.com/securities/prospectus-circulars-offer-documents): PDF

# Main Blocks

- html parsing library
- pdf parsing library
- small LLM
- posgresql database
- Orchestator


# Small LLM

The current choice for the LLM is hugging face [smollm3](https://hub.docker.com/r/ai/smollm3) with a context window of 66K tokens.


# Objective SEC Edgar

Given an HTM of prospectus create a json that contains
- Document split into pages (Done with REGEX)
- The Table of Contents (Found with REGEX but need an LLM to extract the TOC to a JSON)
- The document splitted in Sections (Done with REGEX once we have the hrefs of the table of contents)
- For each section get (with LLM):
  - Tables (If Any)
  - Summary
  - Topics included
  - Subsections
  - Main questions answered by this section
  - First Page Last Page
- By iterating over each section I should update a summary of the document:
  - Document type
  - Who writes this document
  - Date of the document
  - List of securities included including their identifiers.
  - Law


# TODO
- [x] Split document by pages.
- [x] Find the different types of TOC
- [ ] Find TOC with REGEX
- [ ] Be able to find TOC with LLM by iterating over pages if REGEX returns no result 
- [ ] Extract TOC with an LLM
- [ ] With the TOC, identify the sections of the document
- [ ] Split the document by sections
- [ ] Extract sections components
- [ ] Update Document summary by iterating over sections

# Page Breaks of prospectus

## Examples Used

- [Argentina 2005 Bond restructuring](https://www.sec.gov/Archives/edgar/data/914021/000095012305000302/y04567e424b5.htm)
- [Argentina 2020 Bond restructuring](https://www.sec.gov/Archives/edgar/data/914021/000119312520188103/d935251d424b5.htm)
- [Gamestop 2020 Class A shares](https://www.sec.gov/Archives/edgar/data/1326380/000119312521186796/d192873d424b5.htm)
- [Markel Corporation 2005 Debt](https://www.sec.gov/Archives/edgar/data/1096343/000119312506174685/d424b5.htm)


Example 1: HTML/914021_000095012305000302_y04567e424b5.htm (Prospecto 2005)

```html
<!-- PAGEBREAK -->
<H5 align="left" style="page-break-before:always"><A HREF="#tocpage">Table of Contents</A></H5><P>
```

```html
<!-- PAGEBREAK -->
<P><HR noshade><P>
<H5 align="left" style="page-break-before:always"><A HREF="#tocpage">Table of Contents</A></H5><P>
```

The table of contents page does not seem to have the link to the TOC

```html
<!-- PAGEBREAK -->
<P><HR noshade><P>
```

Example 2: Prospecto 2020. All pages have link to TOC.

```html
<p style="margin-top:1em; margin-bottom:0em; page-break-before:always">
<HR SIZE="3" style="COLOR:#999999" WIDTH="100%" ALIGN="CENTER">
<h5 align="left"><a href="#toc">Table of Contents</a></h5>
```

Example 3:

```html
<p Style='page-break-before:always'>
<HR  SIZE="3" COLOR="#999999" WIDTH="100%" ALIGN="CENTER">
<h5 align="left"><a href="#toc">Table of Contents</a></h5>
```

Example 4: Gamestop shares prospectus

This does not signal a page break, but rather to avoid if possible. This is a table row TR

```html
<TR style = "page-break-inside:avoid">
```

This is the break used:
```html
<p style="margin-top:1em; margin-bottom:0em; page-break-before:always">
<HR SIZE="3" style="COLOR:#999999" WIDTH="100%" ALIGN="CENTER">
<h5 align="left"><a href="#toc">Table of Contents</a></h5>
```


# Formatting of Table of Contents

## Example 1
There is an <A> (anchor) tag with a name attribute set to "tocpage". This creates a named anchor in the page called "tocpage," which acts as a target for hyperlinks, allowing users or scripts to jump directly to this location within the webpage. There is only one anchor with that name in the whole document


```html
<DIV align="left">
<A name="tocpage"></A>
</DIV>
```

## Example 2
Example 2 is very similar but has two table of contents using the same anchor.

```
<A NAME="toc"></A>
```

## Example 3

Only one table of contents anchor
```
<A NAME="toc"></A>
```

## Example 4
Only one table of contents with "toc" as anchor

```html
<A NAME="toc"></A>
```

# Resources

- [Docker Compose with Docker AI](https://docs.docker.com/ai/compose/models-and-compose/)
