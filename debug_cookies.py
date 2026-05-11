import yt_dlp
import os

def debug_yt_dlp_cookies():
    video_id = "mWYFwl93uCM"
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    browsers = ['chrome', 'edge', 'firefox', 'brave']
    
    for browser in browsers:
        print(f"\n--- Testing browser: {browser} ---")
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'cookiesfrombrowser': (browser,),
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                print(f"✅ Success with {browser}!")
                return
        except Exception as e:
            print(f"❌ Failed with {browser}: {str(e)}")

if __name__ == "__main__":
    debug_yt_dlp_cookies()
