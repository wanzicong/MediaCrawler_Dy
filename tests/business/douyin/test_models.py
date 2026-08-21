"""抖音业务模型的测试：覆盖媒体资产/迁移模型、采集任务创建与续跑请求模型的字段校验、默认值推导与敏感信息脱敏。"""

import uuid

import pytest
from crawler.business.douyin.accounts.models import DouyinBrowserMode
from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    DouyinMediaAssetPublic,
    DouyinMediaMigrationRequest,
    DouyinMediaProcessRequest,
    MediaMigrationStatus,
    MediaProcessingMode,
    MediaStorageBackend,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskCreate,
    CrawlTaskResumeRequest,
    DouyinCrawlType,
    DouyinLoginType,
    DouyinRequestDelayLevel,
)
from pydantic import ValidationError


def test_media_migration_models_are_persistent_and_private() -> None:
    """验证媒体资产迁移字段的默认值，且公开模型不暴露本地路径、存储桶、对象键等内部字段。"""
    asset = DouyinMediaAsset(task_id=uuid.uuid4(), aweme_id="migration-aweme")
    request = DouyinMediaMigrationRequest(asset_ids=[asset.id])

    assert asset.migration_status == MediaMigrationStatus.idle.value
    assert asset.migration_progress == 0
    assert asset.migration_attempt_count == 0
    assert asset.migration_error is None
    assert request.asset_ids == [asset.id]
    assert "local_path" not in DouyinMediaAssetPublic.model_fields
    assert "storage_bucket" not in DouyinMediaAssetPublic.model_fields
    assert "object_key" not in DouyinMediaAssetPublic.model_fields


def test_media_migration_request_limits_asset_ids() -> None:
    """验证媒体迁移请求对 asset_ids 数量设上限（超过 1000 个即校验失败）。"""
    with pytest.raises(ValidationError):
        DouyinMediaMigrationRequest(asset_ids=[uuid.uuid4() for _ in range(1001)])


def test_search_requires_keywords() -> None:
    """验证搜索类采集任务必须提供 keywords，缺失时校验失败。"""
    with pytest.raises(ValidationError, match="keywords"):
        CrawlTaskCreate(crawl_type=DouyinCrawlType.search)


def test_detail_requires_video_ids() -> None:
    """验证详情类采集任务必须提供 video_ids，缺失时校验失败。"""
    with pytest.raises(ValidationError, match="video_ids"):
        CrawlTaskCreate(crawl_type=DouyinCrawlType.detail)


def test_creator_from_aweme_requires_video_ids() -> None:
    """验证由作品反查作者的采集任务必须提供 video_ids，提供合法值时校验通过。"""
    with pytest.raises(ValidationError, match="video_ids"):
        CrawlTaskCreate(crawl_type=DouyinCrawlType.creator_from_aweme)

    request = CrawlTaskCreate(
        crawl_type=DouyinCrawlType.creator_from_aweme,
        video_ids=["123456"],
        fetch_comments=False,
    )
    assert request.video_ids == ["123456"]


def test_cookie_is_secret_and_never_in_public_request() -> None:
    """验证传入 cookies 时登录方式自动置为 cookie，且公开请求与 repr 中均不泄露 cookie 值。"""
    request = CrawlTaskCreate(
        crawl_type=DouyinCrawlType.search,
        keywords=["中文关键词"],
        cookies="sessionid=secret-value",
    )

    assert request.login_type == DouyinLoginType.cookie
    assert "cookies" not in request.public_request()
    assert "secret-value" not in repr(request)


def test_disabling_comments_also_disables_sub_comments() -> None:
    """验证关闭一级评论采集时，二级评论采集会被强制联动关闭。"""
    request = CrawlTaskCreate(
        keywords=["测试"], fetch_comments=False, fetch_sub_comments=True
    )

    assert request.fetch_sub_comments is False


def test_subtitle_translation_enables_download_and_defaults_to_immediate() -> None:
    """验证开启字幕翻译时自动开启媒体下载，且媒体处理模式默认为即时处理。"""
    request = CrawlTaskCreate(
        keywords=["测试"],
        translate_subtitles=True,
    )

    assert request.download_media is True
    assert request.media_processing_mode == MediaProcessingMode.immediate


def test_batch_media_processing_is_preserved() -> None:
    """验证显式指定批量媒体处理模式时被原样保留，不会被字幕翻译等联动逻辑改写。"""
    request = CrawlTaskCreate(
        keywords=["测试"],
        download_media=True,
        media_processing_mode=MediaProcessingMode.batch,
    )

    assert request.media_processing_mode == MediaProcessingMode.batch


def test_browser_mode_is_task_scoped_and_public() -> None:
    """验证浏览器模式按任务维度生效，且会出现在公开请求快照中。"""
    request = CrawlTaskCreate(keywords=["测试"], browser_mode="remote")

    assert request.browser_mode == DouyinBrowserMode.remote
    assert request.public_request()["browser_mode"] == "remote"


def test_media_storage_is_task_scoped_and_public() -> None:
    """验证媒体存储后端按任务维度生效，且会出现在公开请求快照中。"""
    request = CrawlTaskCreate(keywords=["测试"], media_storage="minio")

    assert request.media_storage == MediaStorageBackend.minio
    assert request.public_request()["media_storage"] == "minio"


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (DouyinRequestDelayLevel.fast, (1.0, 2.0)),
        (DouyinRequestDelayLevel.steady, (3.0, 6.0)),
        (DouyinRequestDelayLevel.ultra_steady, (6.0, 12.0)),
    ],
)
def test_request_delay_levels_expose_random_interval_ranges(
    level: DouyinRequestDelayLevel, expected: tuple[float, float]
) -> None:
    """验证各请求延迟档位映射为正确的随机间隔区间，并在公开请求快照中以列表形式暴露。

    参数：
        level: 请求延迟档位枚举。
        expected: 期望的 (最小秒数, 最大秒数) 区间。
    """
    request = CrawlTaskCreate(keywords=["随机延迟"], request_delay_level=level)

    assert request.request_interval_range_seconds() == expected
    assert request.public_request()["request_interval_range_seconds"] == list(expected)


def test_legacy_minimum_interval_is_respected_by_delay_profile() -> None:
    """验证旧版最小间隔参数 request_interval_seconds 仍被遵守，作为随机区间的下界。"""
    request = CrawlTaskCreate(
        keywords=["账号最小延迟"],
        request_delay_level=DouyinRequestDelayLevel.fast,
        request_interval_seconds=5,
    )

    assert request.request_interval_range_seconds() == (5.0, 6.0)


def test_resume_request_rejects_empty_scope_and_hides_cookie() -> None:
    """验证续跑请求不允许采集与媒体补跑同时关闭（空范围），且 cookies 不出现在 repr 中。"""
    with pytest.raises(ValidationError, match="至少需要"):
        CrawlTaskResumeRequest(resume_crawl=False, resume_media=False)

    request = CrawlTaskResumeRequest(cookies="sessionid=resume-secret")

    assert "resume-secret" not in repr(request)


def test_resume_account_override_requires_crawl_and_excludes_cookie() -> None:
    """验证恢复改选托管账号仅用于爬取阶段，且不能与一次性 Cookie 混用。"""
    account_id = uuid.uuid4()

    with pytest.raises(ValidationError, match="恢复爬取阶段"):
        CrawlTaskResumeRequest(
            resume_crawl=False,
            resume_media=True,
            account_id=account_id,
        )
    with pytest.raises(ValidationError, match="不能同时提交"):
        CrawlTaskResumeRequest(
            resume_crawl=True,
            account_id=account_id,
            cookies="sessionid=secret",
        )

    assert CrawlTaskResumeRequest(account_id=account_id).account_id == account_id


def test_media_process_force_translation_is_normalized_and_cookie_is_secret() -> None:
    """验证强制重译会联动开启字幕翻译开关，且媒体处理请求中的 cookies 被脱敏存储。"""
    request = DouyinMediaProcessRequest(
        force_retranslate=True,
        cookies="sessionid=media-secret",
    )

    assert request.translate_subtitles is True
    assert request.cookies is not None
    assert request.cookies.get_secret_value() == "sessionid=media-secret"
    assert "media-secret" not in repr(request)
