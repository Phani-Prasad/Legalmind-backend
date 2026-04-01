"""
Legaify - Video Service
Handles YouTube transcript extraction and video file transcription via OpenAI Whisper.
"""

import os
import re
import tempfile
import logging
from urllib.parse import urlparse, parse_qs

from youtube_transcript_api import YouTubeTranscriptApi

logger = logging.getLogger(__name__)

# ── YouTube Helpers ────────────────────────────────────────────────────────────

def extract_video_id(url: str) -> str | None:
    """
    Extract YouTube video ID from various URL formats:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/embed/VIDEO_ID
      - https://m.youtube.com/watch?v=VIDEO_ID
    Returns the video ID string, or None if not found.
    """
    if not url:
        return None

    url = url.strip()

    # Handle short URL: youtu.be/VIDEO_ID
    short_url_match = re.match(r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})', url)
    if short_url_match:
        return short_url_match.group(1)

    # Handle standard and embed URLs
    try:
        parsed = urlparse(url)
        # e.g. /embed/VIDEO_ID or /v/VIDEO_ID
        path_match = re.match(r'^/(?:embed|v)/([a-zA-Z0-9_-]{11})', parsed.path)
        if path_match:
            return path_match.group(1)

        # e.g. ?v=VIDEO_ID
        qs = parse_qs(parsed.query)
        if 'v' in qs:
            return qs['v'][0]
    except Exception:
        pass

    # Fallback: bare 11-char alphanumeric string
    bare_match = re.fullmatch(r'[a-zA-Z0-9_-]{11}', url)
    if bare_match:
        return url

    return None


def get_youtube_transcript(video_id: str, client=None) -> str:
    """
    Fetch transcript/captions for a YouTube video.
    Compatible with youtube-transcript-api v1.x (fetch + list API).

    Parameters:
        video_id: YouTube video ID string
        client:   Unused; kept for backward-compatible call signature with main.py

    Returns:
        Full transcript as a single string.
    """
    if not video_id:
        raise ValueError("A valid YouTube video ID is required.")

    # v1.x: YouTubeTranscriptApi must be instantiated (no longer static)
    api = YouTubeTranscriptApi()

    try:
        # --- Try fetching English directly first (fastest path) ---
        try:
            fetched = api.fetch(video_id, languages=['en', 'en-US', 'en-GB'])
            return " ".join(entry.text for entry in fetched).strip()
        except Exception:
            pass  # Fall through to language-discovery path

        # --- Discover all available transcripts and pick the first ---
        transcript_list = api.list(video_id)
        available = list(transcript_list)
        if not available:
            raise RuntimeError("No transcripts are available for this video.")

        # Pick first available language
        first = available[0]
        fetched = api.fetch(video_id, languages=[first.language_code])
        return " ".join(entry.text for entry in fetched).strip()

    except RuntimeError:
        raise
    except Exception as e:
        err_str = str(e).lower()
        if "disabled" in err_str or "no transcripts" in err_str:
            raise RuntimeError(
                "Transcripts are disabled for this video. "
                "Try a video with captions enabled, or use the 'Upload Video' option."
            )
        if "unavailable" in err_str or "private" in err_str:
            raise RuntimeError(
                "The video is unavailable. It may be private, deleted, or region-locked."
            )
        logger.error(f"YouTube transcript error for video_id={video_id}: {e}")
        raise RuntimeError(f"Could not retrieve transcript: {str(e)}")


# ── Video File Transcription ────────────────────────────────────────────────────

# Maximum upload size enforced at service level (25 MB — Whisper API limit)
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

SUPPORTED_EXTENSIONS = {
    '.mp4', '.mp3', '.mpeg', '.mpga', '.m4a',
    '.wav', '.webm', '.ogg', '.mkv', '.mov', '.avi'
}


def transcribe_video_file(content: bytes, filename: str, client) -> str:
    """
    Transcribe an uploaded video/audio file using OpenAI Whisper.

    Parameters:
        content:  Raw bytes of the uploaded file
        filename: Original filename (used to determine extension)
        client:   Initialized openai.OpenAI client

    Returns:
        Transcription text as a string.

    Raises:
        ValueError: On unsupported file type or file too large.
        RuntimeError: On transcription failures.
    """
    if not content:
        raise ValueError("Uploaded file is empty.")

    # --- File size guard ---
    if len(content) > MAX_FILE_SIZE_BYTES:
        size_mb = len(content) / (1024 * 1024)
        raise ValueError(
            f"File is too large ({size_mb:.1f} MB). "
            "Please upload a file smaller than 25 MB, or paste a YouTube URL instead."
        )

    # --- Extension check ---
    _, ext = os.path.splitext(filename.lower())
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # Use .mp4 as a safe fallback extension for temp file if unknown
    safe_ext = ext if ext in SUPPORTED_EXTENSIONS else '.mp4'

    tmp_path = None
    try:
        # Write to a named temp file (Whisper API needs a seekable file-like object)
        with tempfile.NamedTemporaryFile(
            suffix=safe_ext,
            delete=False
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        with open(tmp_path, 'rb') as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )

        # response is a plain string when response_format="text"
        if isinstance(response, str):
            return response.strip()

        # Fallback for older SDK versions that return an object
        return response.text.strip()

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Whisper transcription error for file={filename}: {e}")
        raise RuntimeError(f"Transcription failed: {str(e)}")
    finally:
        # Always clean up temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass