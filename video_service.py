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
    Primary: youtube-transcript-api (Fast)
    Fallback: yt-dlp (Robust for IP blocks on Cloud servers)

    Parameters:
        video_id: YouTube video ID string
        client:   Unused; kept for backward-compatible call signature with main.py

    Returns:
        Full transcript as a single string.
    """
    if not video_id:
        raise ValueError("A valid YouTube video ID is required.")

    # 1. Try Standard YouTubeTranscriptApi (Fastest)
    try:
        # In this environment, YouTubeTranscriptApi uses instance methods .list() and .fetch()
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        
        # Look for English
        target = None
        for t in transcript_list:
            if t.language_code.startswith('en'):
                target = t
                break
        
        # If no English, pick any available
        if not target:
            target = next(iter(transcript_list))
            
        return " ".join(entry.text for entry in api.fetch(video_id, languages=[target.language_code])).strip()

    except Exception as e:
        err_msg = str(e).lower()
        # If it's just disabled, don't even try yt-dlp (it will fail too)
        if "disabled" in err_msg or "no transcripts" in err_msg:
            raise RuntimeError(
                "Transcripts are disabled for this video. "
                "Try a video with captions enabled, or use the 'Upload Video' option."
            )
        
        # 2. Try Fallback with yt-dlp (Bypasses many IP blocks/limitations)
        logger.warning(f"Standard API failed for {video_id} ({e}). Attempting yt-dlp fallback...")
        try:
            return _fetch_with_yt_dlp(video_id)
        except Exception as fallback_err:
            logger.error(f"YouTube transcript error for video_id={video_id}: {fallback_err}")
            
            if "youtube is blocking" in str(fallback_err).lower() or "403" in str(fallback_err):
                raise RuntimeError(
                    "YouTube blocked the request from this server (Common on Render/Cloud). "
                    "Please try the 'Upload Video' option or use a video with accessible captions."
                )
            
            raise RuntimeError(f"Could not retrieve transcript: {str(fallback_err)}")


def _fetch_with_yt_dlp(video_id: str) -> str:
    """
    Fallback method using yt-dlp to extract subtitles.
    Useful when youtube-transcript-api is blocked by cloud provider IP bans.
    """
    import yt_dlp
    import requests
    import re
    
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Check for manually created subtitles first
            subs = info.get('subtitles', {})
            # Check for auto-generated captions
            auto_subs = info.get('automatic_captions', {})
            
            # Look for English (en, en-US, etc.)
            target_sub = None
            for lang in ['en', 'en-US', 'en-GB', 'en-IN']:
                if lang in subs:
                    target_sub = subs[lang]
                    break
                if lang in auto_subs:
                    target_sub = auto_subs[lang]
                    break
            
            if not target_sub:
                if subs:
                    target_sub = next(iter(subs.values()))
                elif auto_subs:
                    target_sub = next(iter(auto_subs.values()))
                
            if target_sub:
                # Prefer json3 format if available (easiest to parse)
                selected = next((s for s in target_sub if s.get('ext') == 'json3'), 
                            next((s for s in target_sub if s.get('ext') == 'vtt'), 
                            target_sub[0]))
                
                resp = requests.get(selected['url'], timeout=10)
                resp.raise_for_status()
                
                if selected.get('ext') == 'json3':
                    data = resp.json()
                    text = ""
                    for event in data.get('events', []):
                        if 'segs' in event:
                            for seg in event['segs']:
                                text += seg.get('utf8', '')
                        text += " "
                    return " ".join(text.split()).strip()
                else:
                    # Basic VTT/text cleanup
                    clean = re.sub(r'<[^>]+>', '', resp.text)
                    clean = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', '', clean)
                    clean = re.sub(r'WEBVTT|Kind: captions|Language: \w+', '', clean)
                    return " ".join(clean.split()).strip()
            
            raise RuntimeError("No captions available for this video.")
    except Exception as e:
        raise RuntimeError(f"yt-dlp extraction failed: {str(e)}")


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