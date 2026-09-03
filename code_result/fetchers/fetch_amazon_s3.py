# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Amazon S3",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="Amazon S3：目标数据位于 MicroSurvey 的 S3 桶 s3.microsurvey.com。唯一公开可达的 GET Object 仅返回 CGG2005.zip 二进制文件而非集合级学术元数据，未发现任何元数据导出接口",
    scope_limit="BOTH"
)
def fetch_amazon_s3(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "Amazon S3：目标数据位于 MicroSurvey 的 S3 桶 s3.microsurvey.com。唯一公开可达的 GET Object 仅返回 CGG2005.zip 二进制文件而非集合级学术元数据，未发现任何元数据导出接口"}
