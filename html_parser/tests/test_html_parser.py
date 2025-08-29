import pytest
from pathlib import Path
from src.html_regex_page_splitter import HTMLPageBreakSplitter
import shutil

# Folder containing test HTML files
TEST_DATA_DIR = Path(__file__).parent / "data"

# Folder to save reconstructed files for failed tests
FAILED_DIR = Path(__file__).parent / "failed_reconstructed"
FAILED_DIR.mkdir(exist_ok=True)


@pytest.fixture
def splitter():
    """Provides an instance of HTMLPageBreakSplitter for tests."""
    return HTMLPageBreakSplitter()


@pytest.fixture(params=list(TEST_DATA_DIR.glob("*.htm")) + list(TEST_DATA_DIR.glob("*.html")))
def html_file(request):
    """Parametrized fixture: each HTML/HTM file in the test data folder."""
    return request.param


def test_split_html_by_regex_basic(splitter, html_file):
    """Test basic splitting functionality on each file."""
    html_content = html_file.read_text(encoding="utf-8", errors="ignore")
    chunks = splitter.split_html_by_regex(html_content)
    assert isinstance(chunks, list)
    assert len(chunks) > 0, "Should find at least one chunk"
    assert all('content' in chunk and 'page' in chunk for chunk in chunks)


def test_process_file_and_reconstruct(splitter, html_file):
    """
    Test splitting and reconstruction:
    - Split each HTML file into chunks
    - Reconstruct HTML from JSON
    - Compare original vs reconstructed (exact byte match)
    - Preserve failed reconstructions for debugging
    """
    output_json_file = html_file.parent / f"{html_file.stem}_chunks.json"
    reconstructed_html_file = html_file.parent / f"{html_file.stem}_reconstructed.html"

    try:
        # Split and write JSON
        processed_json_path = splitter.process_file(str(html_file), str(output_json_file))
        assert processed_json_path.exists()

        # Reconstruct HTML
        reconstructed_path = splitter.reconstruct_file(str(output_json_file), str(reconstructed_html_file))
        assert reconstructed_path.exists()

        # Read original and reconstructed content
        original_content = html_file.read_text(encoding="utf-8", errors="ignore")
        reconstructed_content = reconstructed_html_file.read_text(encoding="utf-8", errors="ignore")

        # Exact comparison
        if original_content != reconstructed_content:
            import difflib

            # Save reconstructed file for inspection
            destination_file = FAILED_DIR / reconstructed_html_file.name
            shutil.copy(reconstructed_html_file, destination_file)

            # Print diff
            diff = "\n".join(
                difflib.unified_diff(
                    original_content.splitlines(),
                    reconstructed_content.splitlines(),
                    fromfile='original',
                    tofile='reconstructed',
                    lineterm=''
                )
            )
            print(f"\n⚠️ Differences for {html_file.name}:\n{diff}")
            print(f"Reconstructed file saved to: {destination_file}")

            assert False, f"{html_file.name}: reconstructed content does not match original"

    finally:
        # Cleanup temporary files
        if output_json_file.exists():
            output_json_file.unlink()
        if reconstructed_html_file.exists():
            reconstructed_html_file.unlink()


def test_no_breaks_file(splitter):
    """Test a file with no explicit page breaks."""
    no_break_html = "<html><body><p>This is a single page document.</p></body></html>"
    chunks = splitter.split_html_by_regex(no_break_html)
    assert len(chunks) == 1
    assert chunks[0]['page'] == 1
    assert "This is a single page document." in chunks[0]['content']


def test_break_avoidance(splitter):
    """Test if break avoidance patterns are respected."""
    html_with_avoid = """
    <html><body>
    <div style="page-break-before: always;">Page 1</div>
    <p style="page-break-inside: avoid; page-break-before: always;">This should not break</p>
    <div style="page-break-before: always;">Page 2</div>
    </body></html>
    """
    chunks = splitter.split_html_by_regex(html_with_avoid)
    # Expecting 3 chunks: initial + Page 1 + Page 2
    assert len(chunks) == 3
    assert "Page 1" in chunks[1]['content']
    assert "This should not break" in chunks[1]['content'] or "This should not break" in chunks[2]['content']
    assert "Page 2" in chunks[2]['content']
