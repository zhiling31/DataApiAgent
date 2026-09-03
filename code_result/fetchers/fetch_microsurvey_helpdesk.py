# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="MicroSurvey Helpdesk",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="MicroSurvey Helpdesk 是商业软件支持知识库（Kayako 平台），并非学术数据仓储。唯一可用的 Kayako API 返回帮助中心文章元数据，而非数据本体元数据",
    scope_limit="BOTH"
)
def fetch_microsurvey_helpdesk(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "系统判定无API"}
