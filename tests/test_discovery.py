import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))

from discovery import compute_outliers  # noqa: E402


def make_video(video_id, views, age_hours, channel_id="UC_test"):
    return {
        "id": video_id,
        "title": f"video {video_id}",
        "view_count": views,
        "upload_date": datetime.now(timezone.utc) - timedelta(hours=age_hours),
        "channel": "Test Channel",
        "channel_id": channel_id,
    }


def test_no_outliers_when_all_similar():
    videos = [make_video(f"v{i}", views=1000 * (24 * i + 24), age_hours=24 * (i + 1)) for i in range(5)]
    # all roughly the same views/hour (~1000/h) -- nothing should stand out
    outliers = compute_outliers(videos, multiplier=2.5)
    assert outliers == []


def test_flags_a_genuine_outlier():
    videos = [make_video(f"v{i}", views=1000 * 24, age_hours=24) for i in range(4)]  # baseline ~1000/h
    videos.append(make_video("viral1", views=1000 * 24 * 5, age_hours=24))  # 5x the others
    outliers = compute_outliers(videos, multiplier=2.5)
    ids = [o["id"] for o in outliers]
    assert "viral1" in ids
    assert outliers[0]["velocity"] >= 2.5


def test_too_new_video_excluded_even_if_high_views():
    videos = [make_video(f"v{i}", views=1000 * 24, age_hours=24) for i in range(4)]
    videos.append(make_video("brandnew", views=50000, age_hours=1))  # 1 hour old, unstable early count
    outliers = compute_outliers(videos, multiplier=2.5, min_age_hours=6)
    assert "brandnew" not in [o["id"] for o in outliers]


def test_too_old_video_excluded():
    videos = [make_video(f"v{i}", views=1000 * 24, age_hours=24) for i in range(4)]
    videos.append(make_video("stale", views=1000 * 24 * 10, age_hours=24 * 60))  # 60 days old
    outliers = compute_outliers(videos, multiplier=2.5, max_age_days=30)
    assert "stale" not in [o["id"] for o in outliers]


def test_min_views_floor_applies():
    """A small channel can have a 5x-baseline video that's still only
    a handful of views -- shouldn't count as a real outlier worth acting on."""
    videos = [make_video(f"v{i}", views=10, age_hours=24) for i in range(4)]
    videos.append(make_video("tiny_spike", views=100, age_hours=24))  # 10x baseline but only 100 views
    outliers = compute_outliers(videos, multiplier=2.5, min_views=3000)
    assert outliers == []


def test_too_few_videos_returns_empty():
    videos = [make_video("v1", views=5000, age_hours=24), make_video("v2", views=50000, age_hours=24)]
    assert compute_outliers(videos) == []
