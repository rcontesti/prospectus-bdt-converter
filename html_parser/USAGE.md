# HTML Page Break Splitter (Regex Only)

This document explains how to use the `html_regex_page_splitter.py` script, which is designed to split HTML files into smaller chunks based on CSS page break indicators, and to reconstruct them from these chunks. This version exclusively uses regular expressions for parsing, avoiding external dependencies like BeautifulSoup.

## Introduction

The `html_regex_page_splitter.py` script processes HTML files to identify page breaks defined by specific CSS styles. It then divides the HTML content into logical "pages" or "chunks" and outputs them as a JSON file. This is particularly useful for handling large HTML documents that need to be segmented for display, processing, or printing. The script also provides functionality to reconstruct the original HTML from the generated JSON chunks.

## Installation

This script has no external dependencies. It uses only standard Python libraries.

## Usage

The script can be run from the command line.

### Splitting an HTML File

To split an HTML file into JSON chunks:

```bash
python html_regex_page_splitter.py <input_html_file> [-o <output_json_file>]
```

**Arguments:**

*   `<input_html_file>`: The path to the HTML or HTM file you want to split.
*   `-o`, `--output` (optional): The name of the output JSON file. If not provided, the script will generate a filename like `<input_html_file_stem>_chunks.json`.

**Example:**

```bash
python html_regex_page_splitter.py my_document.html -o my_document_chunks.json
```

This will create `my_document_chunks.json` containing the split HTML content.

### Reconstructing an HTML File

To reconstruct an HTML file from a JSON chunks file:

```bash
python html_regex_page_splitter.py <input_json_file> -r [-o <output_html_file>]
```

**Arguments:**

*   `<input_json_file>`: The path to the JSON file containing the HTML chunks.
*   `-r`, `--reconstruct`: This flag indicates that the script should operate in reconstruction mode.
*   `-o`, `--output` (optional): The name of the output HTML file. If not provided, the script will generate a filename like `<original_file_stem>_reconstructed.html`.

**Example:**

```bash
python html_regex_page_splitter.py my_document_chunks.json -r -o my_document_reconstructed.html
```

This will create `my_document_reconstructed.html` from the JSON chunks.

### Testing Reconstruction

You can also test the reconstruction process immediately after splitting:

```bash
python html_regex_page_splitter.py <input_html_file> --test
```

**Arguments:**

*   `<input_html_file>`: The path to the HTML or HTM file you want to split and then test.
*   `--test`: This flag will first split the input HTML, then immediately reconstruct it, and print messages about the process.

**Example:**

```bash
python html_regex_page_splitter.py my_document.html --test
```

## Page Break Patterns

The script identifies page breaks based on the following CSS patterns (case-insensitive) found within `style` attributes or `class` attributes of HTML tags:

**Page Break Indicators:**
*   `page-break-before: always`
*   `page-break-after: always`
*   `break-before: page`
*   `break-after: page`
*   `break-before: always`
*   `break-after: always`

**Break Avoidance Indicators:**
The script also considers patterns that indicate a break should be avoided within an element. If a page break indicator is found within an element that also has a break avoidance indicator, the break will not be applied.
*   `page-break-inside: avoid`
*   `break-inside: avoid`
*   `page-break-before: avoid`
*   `page-break-after: avoid`
*   `break-before: avoid`
*   `break-after: avoid`

## Example Workflow

1.  **Split an HTML file:**
    ```bash
    python html_regex_page_splitter.py input.html -o output_chunks.json
    ```
2.  **Review the output JSON (optional):**
    You can open `output_chunks.json` to see the structure and content of the generated chunks.
3.  **Reconstruct the HTML file:**
    ```bash
    python html_regex_page_splitter.py output_chunks.json -r -o reconstructed.html
    ```
4.  **Verify the reconstructed file:**
    Open `reconstructed.html` in a web browser to ensure it matches the original `input.html` in terms of content and structure.
