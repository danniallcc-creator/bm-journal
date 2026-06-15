"""翻译工具 - 将英文新闻标题/摘要翻译为中文
使用 MyMemory Translation API (免费, 无需 Key, 1000字/天)
有降级策略: 翻译失败时保留英文原文
"""
import re
import time
import requests
from ..utils import log, cache_get, cache_set


def _mymemory_translate(text: str, source: str = "en", target: str = "zh",
                       timeout: int = 10) -> str | None:
    """调用 MyMemory API 翻译文本 (免费, 无需 Key, 1000字/天)

    Args:
        text: 待翻译文本
        source: 源语言代码
        target: 目标语言代码
        timeout: 请求超时秒数

    Returns:
        翻译结果字符串, 失败时返回 None
    """
    if not text or not text.strip():
        return text

    # 跳过已经是中文的内容 (粗略检测: 含中文字符比例 > 30%)
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    if len(text) > 0 and chinese_chars / len(text) > 0.3:
        return text

    try:
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text[:500],  # 限制长度
            "langpair": f"{source}|{target}"
        }
        resp = requests.get(url, params=params, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        if resp.status_code == 200:
            data = resp.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            # 检查是否真的有翻译 (MyMemory有时返回原文)
            if translated and translated != text.strip():
                return translated
            # 检查 matches 是否有高质量翻译
            matches = data.get("matches", [])
            if matches:
                best = max(matches, key=lambda m: int(m.get("quality", 0)))
                if best.get("translation"):
                    return best["translation"]
    except Exception as e:
        log.debug(f"MyMemory translation failed: {e}")

    return None


def translate_text(text: str, max_retries: int = 1) -> str:
    """翻译文本, 带缓存和重试

    Args:
        text: 待翻译的英文文本
        max_retries: 最大重试次数

    Returns:
        翻译后的中文文本, 失败时返回原文
    """
    if not text or not text.strip():
        return text

    # 检查缓存
    cache_key = f"trans:{text[:100]}"
    cached = cache_get(cache_key, "translations", ttl=86400 * 7)  # 7天缓存
    if cached:
        return cached.get("translated", text)

    for attempt in range(max_retries + 1):
        result = _mymemory_translate(text)
        if result:
            cache_set(cache_key, "translations", {
                "original": text,
                "translated": result
            })
            return result
        if attempt < max_retries:
            time.sleep(0.5)

    # 降级: 返回原文
    return text


def translate_articles(articles: list[dict]) -> list[dict]:
    """批量翻译新闻文章的标题和摘要

    Args:
        articles: 文章列表, 每个元素含 title, summary 字段

    Returns:
        翻译后的文章列表 (原地修改)
    """
    translated_count = 0
    for article in articles:
        title = article.get("title", "")
        summary = article.get("summary", "")

        # 清理 HTML 标签
        clean_summary = re.sub(r'<[^>]+>', '', summary).strip()

        # 翻译标题
        translated_title = translate_text(title)
        if translated_title != title:
            article["title"] = translated_title
            article["title_en"] = title  # 保留英文原标题
            translated_count += 1

        # 翻译摘要 (清理后)
        if clean_summary:
            translated_summary = translate_text(clean_summary[:300])
            article["summary"] = translated_summary

        # 请求间隔, 避免被限流
        time.sleep(0.3)

    log.info(f"Translated {translated_count}/{len(articles)} articles to Chinese")
    return articles


if __name__ == "__main__":
    # 测试
    test_texts = [
        "Fed holds rates steady at 3.62% amid inflation concerns",
        "How the Hormuz crisis is pushing Gulf states toward greater resilience",
        "Why housing demand is up and inventory is down in 2026",
    ]
    for t in test_texts:
        result = translate_text(t)
        print(f"EN: {t}")
        print(f"CN: {result}")
        print()
