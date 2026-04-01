import os
import datetime
from pdf_service import generate_judicial_pdf

def save_content_locally(filename, title, content, format="pdf"):
    """
    Saves content directly to the user's Downloads folder.
    Supports both .md and .pdf formats.
    """
    try:
        home = os.path.expanduser("~")
        export_dir = os.path.join(home, "Downloads")
        
        if not os.path.exists(export_dir):
            base_dir = os.path.dirname(os.path.abspath(__file__))
            export_dir = os.path.join(os.path.dirname(base_dir), "legaify_exports")
        
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            
        # Clean filename
        safe_name = "".join([c for c in filename if c.isalnum() or c in (' ', '_', '-')]).strip()
        safe_name = safe_name.replace(' ', '_')
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        extension = ".pdf" if format == "pdf" else ".md"
        full_filename = f"{safe_name}_{timestamp}{extension}"
        file_path = os.path.join(export_dir, full_filename)
        
        if format == "pdf":
            # Generate PDF bytes using the judicial engine
            pdf_buffer = generate_judicial_pdf(title, content)
            with open(file_path, "wb") as f:
                f.write(pdf_buffer.getbuffer())
        else:
            # Standard Markdown text save
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            
        return {
            "status": "success",
            "path": file_path,
            "filename": full_filename
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
