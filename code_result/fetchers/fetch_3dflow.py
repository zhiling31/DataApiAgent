# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="3Dflow",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="1、3DF Zephyr仅为摄影测量软件公司，Geoids download页面是其静态下载支持页面，并非学术数据仓储平台。S3 桶仅提供文件清单而非集合级元数据，下载链接为二进制 ZIP 文件，未发现任何元数据导出接口 \
        2、DigitalOcean：S3 兼容对象存储服务，3Dflow背后的文件存储后端，未发现任何元数据导出接口",
    scope_limit="BOTH"
)
def fetch_3dflow(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "1、3DF Zephyr仅为摄影测量软件公司，Geoids download页面是其静态下载支持页面，并非学术数据仓储平台。S3 桶仅提供文件清单而非集合级元数据，下载链接为二进制 ZIP 文件，未发现任何元数据导出接口 \
        2、DigitalOcean：S3 兼容对象存储服务，3Dflow背后的文件存储后端，未发现任何元数据导出接口"}
