from app.douyin.privacy import (
    anonymize_account_id,
    anonymize_user_id,
    map_aweme,
    map_comment,
    mask_nickname,
)


def test_aweme_mapping_anonymizes_user_and_keeps_media_urls() -> None:
    mapped = map_aweme(
        {
            "aweme_id": "123",
            "aweme_type": 4,
            "desc": "中文标题",
            "create_time": 123456,
            "author": {
                "uid": "raw-user-id",
                "sec_uid": "sec-user-id",
                "nickname": "张三丰",
            },
            "statistics": {
                "digg_count": 10,
                "collect_count": 2,
                "comment_count": 3,
                "share_count": 4,
            },
            "video": {
                "raw_cover": {"url_list": ["cover-a", "cover-b"]},
                "play_addr": {"url_list": ["video-a", "video-b"]},
            },
            "music": {"play_url": {"uri": "music-url"}},
        },
        "关键词",
    )

    assert mapped["creator_hash"] == anonymize_user_id("raw-user-id")
    assert "raw-user-id" not in mapped.values()
    assert mapped["sec_uid"] == anonymize_user_id("sec-user-id")
    assert "sec-user-id" not in mapped.values()
    assert mapped["nickname"] == "张***丰"
    assert mapped["cover_url"] == "cover-b"
    assert mapped["video_download_url"] == "video-b"
    assert mapped["source_keyword"] == "关键词"


def test_comment_mapping_rejects_wrong_aweme_and_masks_nickname() -> None:
    comment = {
        "aweme_id": "123",
        "cid": "comment-1",
        "text": "评论内容",
        "user": {"uid": "raw", "sec_uid": "raw-sec-uid", "nickname": "李雷"},
    }

    assert map_comment(comment, "other") is None
    mapped = map_comment(comment, "123")
    assert mapped is not None
    assert mapped["nickname"] == "李*"
    assert mapped["creator_hash"] == anonymize_user_id("raw")
    assert mapped["sec_uid"] == anonymize_user_id("raw-sec-uid")
    assert "raw-sec-uid" not in mapped.values()


def test_account_hmac_is_stable_and_keyed() -> None:
    first = anonymize_account_id("dy:sec_uid:abc", "key-one")
    second = anonymize_account_id("dy:sec_uid:abc", "key-one")
    other_key = anonymize_account_id("dy:sec_uid:abc", "key-two")

    assert first == second
    assert first != other_key
    assert "abc" not in first
    assert mask_nickname("") == ""
