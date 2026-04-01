from pdf_service import generate_judicial_pdf
import os

def test_pdf():
    title = "Diagnostic Test"
    content = "# Title\nThis is a body.\n## Subsection\n- Item 1\n- Item 2\n**Bold Text**"
    
    try:
        buffer = generate_judicial_pdf(title, content)
        size = len(buffer.getvalue())
        print(f"PDF Generated successfully. Size: {size} bytes")
        
        # Save to a temp file for manual verification if possible
        with open("diag_test.pdf", "wb") as f:
            f.write(buffer.getvalue())
        print(f"Diagnostic file 'diag_test.pdf' written to {os.getcwd()}")
        
        if size > 1000: # Typical PDF header + some content
            print("PDF size looks healthy.")
        else:
            print("WARNING: PDF size seems too small!")
            
    except Exception as e:
        print(f"PDF Generation FAILED: {str(e)}")

if __name__ == "__main__":
    test_pdf()
