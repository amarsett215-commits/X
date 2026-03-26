"""YouTube Data API v3 wrapper for fetching channel and video data."""

from __future__ import annotations

import os
import re
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")


def get_youtube_client():
    if not API_KEY:
        raise ValueError("YOUTUBE_API_KEY not set. Copy .env.example to .env and add your key.")
    return build("youtube", "v3", developerKey=API_KEY)


def resolve_channel_id(input_str: str) -> str:
    """Resolve a channel URL, handle, or name to a channel ID."""
    youtube = get_youtube_client()

    # Already a channel ID
    if re.match(r"^UC[\w-]{22}$", input_str):
        return input_str

    # Extract from URL patterns
    url_patterns = [
        r"youtube\.com/channel/(UC[\w-]{22})",
        r"youtube\.com/@([\w.-]+)",
        r"youtube\.com/c/([\w.-]+)",
        r"youtube\.com/user/([\w.-]+)",
    ]
    for pattern in url_patterns:
        match = re.search(pattern, input_str)
        if match:
            input_str = match.group(1)
            break

    # If it starts with UC, it's a channel ID
    if input_str.startswith("UC") and len(input_str) == 24:
        return input_str

    # Strip @ prefix for handle lookup
    handle = input_str.lstrip("@")

    # Try handle/username search
    resp = youtube.search().list(
        part="snippet",
        q=handle,
        type="channel",
        maxResults=5,
    ).execute()

    if resp.get("items"):
        # Prefer exact handle match
        for item in resp["items"]:
            title = item["snippet"]["title"].lower()
            custom_url = item["snippet"].get("customUrl", "").lower().lstrip("@")
            if handle.lower() in (title, custom_url):
                return item["snippet"]["channelId"]
        return resp["items"][0]["snippet"]["channelId"]

    raise ValueError(f"Could not find channel: {input_str}")


def get_channel_info(channel_id: str) -> dict:
    """Fetch channel metadata and statistics."""
    youtube = get_youtube_client()
    resp = youtube.channels().list(
        part="snippet,statistics,contentDetails,brandingSettings",
        id=channel_id,
    ).execute()

    if not resp.get("items"):
        raise ValueError(f"Channel not found: {channel_id}")

    channel = resp["items"][0]
    snippet = channel["snippet"]
    stats = channel["statistics"]
    branding = channel.get("brandingSettings", {}).get("channel", {})

    return {
        "id": channel_id,
        "title": snippet["title"],
        "description": snippet.get("description", ""),
        "custom_url": snippet.get("customUrl", ""),
        "published_at": snippet["publishedAt"],
        "thumbnail": snippet["thumbnails"].get("high", {}).get("url", ""),
        "subscriber_count": int(stats.get("subscriberCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
        "view_count": int(stats.get("viewCount", 0)),
        "keywords": branding.get("keywords", ""),
        "uploads_playlist": channel["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def get_all_videos(channel_id: str, max_videos: int = 200) -> list[dict]:
    """Fetch video data from a channel's uploads playlist."""
    youtube = get_youtube_client()
    channel_info = get_channel_info(channel_id)
    playlist_id = channel_info["uploads_playlist"]

    video_ids = []
    next_page = None

    while len(video_ids) < max_videos:
        pl_resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=min(50, max_videos - len(video_ids)),
            pageToken=next_page,
        ).execute()

        for item in pl_resp.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])

        next_page = pl_resp.get("nextPageToken")
        if not next_page:
            break

    # Fetch full video details in batches of 50
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        v_resp = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch),
        ).execute()

        for item in v_resp.get("items", []):
            snippet = item["snippet"]
            stats = item.get("statistics", {})
            videos.append({
                "id": item["id"],
                "title": snippet["title"],
                "description": snippet.get("description", ""),
                "published_at": snippet["publishedAt"],
                "tags": snippet.get("tags", []),
                "category_id": snippet.get("categoryId", ""),
                "thumbnail_url": _best_thumbnail(snippet.get("thumbnails", {})),
                "duration": item["contentDetails"]["duration"],
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
            })

    return videos


def _best_thumbnail(thumbnails: dict) -> str:
    """Get the highest resolution thumbnail URL."""
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbnails:
            return thumbnails[key]["url"]
    return ""
