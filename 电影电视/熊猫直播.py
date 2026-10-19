# -*- coding: utf-8 -*-
# @name 熊猫直播
# @version 1.0.0
# @downloadURL https://raw.githubusercontent.com/Silent1566/OmniBox-Spider/main/直播/熊猫直播.py
# @description PandaLive 直播源（OmniBox 适配版）：列表聚合、IVS 播放、已去掉 localProxy

"""
熊猫直播 (PandaLive) — OmniBox 适配版

站点: https://www.pandalive.co.kr
API: https://api.pandalive.co.kr
原 T3 接口已统一为 OmniBox handler (params, context)
"""

import json
import re
import time

from spider_runner import OmniBox, run

BASE = "https://www.pandalive.co.kr"
API = "https://api.pandalive.co.kr"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

_x_device_info = {"t": "webPc", "v": "1.0", "ui": "0", "ck": {"sessKeyAsp": ""}}
_extra_cookie = ""
_token_ready = False


def _to_int(v, default=0):
    try:
        return int(float(v)) if isinstance(v, str) else int(v)
    except (ValueError, TypeError):
        return default


def _headers(extra=None):
    h = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Origin": BASE,
        "Referer": BASE + "/",
        "x-device-info": json.dumps(_x_device_info, separators=(",", ":")),
    }
    if _extra_cookie:
        h["Cookie"] = _extra_cookie
    if extra:
        h.update(extra)
    return h


async def _ensure_token():
    global _token_ready
    if _token_ready:
        return
    try:
        await OmniBox.request(BASE, {"method": "GET", "headers": _headers(), "timeout": 8})
        await OmniBox.request(
            f"{API}/v1/member/app_token",
            {"method": "GET", "headers": _headers(), "timeout": 8},
        )
        _token_ready = True
    except Exception:
        pass


async def _list_live(page=None, page_size=60, order_by="user", only_new="N"):
    await _ensure_token()
    limit = page_size
    offset = 0 if page is None else max(0, (page - 1) * limit)
    body = f"orderBy={order_by}&onlyNewBj={only_new}&limit={limit}&offset={offset}"
    try:
        res = await OmniBox.request(
            f"{API}/v1/live",
            {
                "method": "POST",
                "headers": _headers(
                    {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
                ),
                "body": body,
                "timeout": 8,
            },
        )
        text = res.get("body") or ""
        j = json.loads(text) if text else {}
        if isinstance(j, dict) and isinstance(j.get("list"), list) and len(j["list"]) > 0:
            return j
    except Exception:
        pass
    try:
        res = await OmniBox.request(
            f"{API}/v1/live",
            {"method": "GET", "headers": _headers(), "timeout": 8},
        )
        text = res.get("body") or ""
        return json.loads(text) if text else {}
    except Exception:
        return {}


async def _list_live_page(page, page_size, order_by="user", only_new="N"):
    j = await _list_live(page=page, page_size=page_size, order_by=order_by, only_new=only_new)
    return j.get("list", []) if isinstance(j, dict) else []


async def _list_live_aggregate(max_pages=5, page_size=60, min_expect=60, order_by="user", only_new="N"):
    cache_key = f"pandalive_agg_v2_{order_by}_{only_new}"
    try:
        cached = await OmniBox.getCache(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("list"), list):
            return cached["list"]
    except Exception:
        pass

    seen, result = set(), []
    first = await _list_live(page=None, page_size=page_size, order_by=order_by, only_new=only_new)
    items = first.get("list", []) if isinstance(first, dict) else []
    for it in items:
        code = it.get("code") or it.get("userId")
        if code and code not in seen:
            seen.add(code)
            result.append(it)

    p = 1
    while len(result) < min_expect and p <= max_pages:
        page_items = await _list_live_page(page=p, page_size=page_size, order_by=order_by, only_new=only_new)
        added = 0
        for it in page_items:
            code = it.get("code") or it.get("userId")
            if code and code not in seen:
                seen.add(code)
                result.append(it)
                added += 1
        if added == 0 and p > 1:
            break
        p += 1

    try:
        await OmniBox.setCache(cache_key, {"expiresAt": int(time.time()) + 20, "list": result})
    except Exception:
        pass
    return result


async def _live_play(play_id):
    await _ensure_token()
    body = json.dumps({"play_id": play_id, "device": "webPc", "player": "ivs"})
    headers = _headers(
        {
            "Content-Type": "application/json",
            "Referer": f"{BASE}/play/{play_id.split('_')[0]}",
        }
    )
    res = await OmniBox.request(
        f"{API}/v1/live/play",
        {"method": "POST", "headers": headers, "body": body, "timeout": 8},
    )
    if (res.get("statusCode") or 0) != 200:
        try:
            await OmniBox.request(
                f"{API}/v1/member/app_token",
                {"method": "GET", "headers": _headers(), "timeout": 8},
            )
        except Exception:
            pass
        res = await OmniBox.request(
            f"{API}/v1/live/play",
            {"method": "POST", "headers": headers, "body": body, "timeout": 8},
        )
    try:
        return json.loads(res.get("body") or "{}")
    except Exception:
        return {"result": False}


def _find_first_m3u8(obj):
    try:
        text = json.dumps(obj, ensure_ascii=False)
        m = re.search(r'https?://[^\s"\\]+\.m3u8[^\s"\\]*', text)
        if m:
            return m.group(0)
    except Exception:
        pass
    return ""


def _to_vod(it):
    title = it.get("title") or it.get("userNick") or it.get("userId") or "LIVE"
    pic = it.get("thumbUrl") or it.get("ivsThumbnail") or ""
    user_id = it.get("userId", "")
    play_id = it.get("code", user_id)
    vod_id = f"{play_id}|{user_id}|{title}"
    remarks = f"观众 {it.get('user', 0)} | 点赞 {it.get('likeCnt', 0)}"
    return {
        "vod_id": vod_id,
        "vod_name": title,
        "vod_pic": pic,
        "vod_remarks": remarks,
    }


def _tid_to_sort(tid):
    t = (tid or "").lower()
    if t == "live_newbj":
        return "user", "Y"
    if t == "live_hot":
        return "hot", "N"
    if t == "live_new":
        return "new", "N"
    return "user", "N"


async def home(params, context):
    try:
        await OmniBox.log("info", f"[home] from={(context or {}).get('from', 'web')}")
        classes = [{"type_name": "LIVE", "type_id": "live"}]
        filters = {
            "live": [
                {
                    "key": "sort",
                    "name": "排序",
                    "value": [
                        {"n": "观看次数", "v": "user-N"},
                        {"n": "热门", "v": "hot-N"},
                        {"n": "最新", "v": "new-N"},
                        {"n": "新人", "v": "user-Y"},
                    ],
                }
            ]
        }
        items = await _list_live_aggregate(
            max_pages=3, page_size=60, min_expect=48, order_by="user", only_new="N"
        )
        if not items:
            items = (await _list_live()).get("list", [])
        return {
            "class": classes,
            "list": [_to_vod(it) for it in items[:48]],
            "filters": filters,
        }
    except Exception as e:
        await OmniBox.log("error", f"[home] 失败: {e}")
        return {"class": [{"type_name": "LIVE", "type_id": "live"}], "list": [], "filters": {}}


async def category(params, context):
    try:
        tid = str((params or {}).get("categoryId") or "live")
        page = _to_int((params or {}).get("page"), 1) or 1
        page_size = 24
        extend = (params or {}).get("filters") or {}
        order_by, only_new = "user", "N"
        s = extend.get("sort") if isinstance(extend, dict) else None
        if isinstance(s, str) and "-" in s:
            ab = s.split("-", 1)
            if len(ab) == 2:
                order_by, only_new = (ab[0] or "user"), (ab[1] or "N")
        elif (tid or "").lower() != "live":
            order_by, only_new = _tid_to_sort(tid)

        await OmniBox.log(
            "info", f"[category] categoryId={tid}, page={page}, sort={order_by}-{only_new}"
        )

        server_items = await _list_live_page(
            page=page, page_size=page_size, order_by=order_by, only_new=only_new
        )
        if len(server_items) >= page_size:
            return {
                "page": page,
                "pagecount": 99999,
                "limit": page_size,
                "total": 999999,
                "list": [_to_vod(it) for it in server_items],
            }

        all_items = await _list_live_aggregate(
            max_pages=12, page_size=100, min_expect=120, order_by=order_by, only_new=only_new
        )
        total = len(all_items)
        if total <= 0:
            base_list = (await _list_live()).get("list", [])
            total = len(base_list)
            if total <= 0:
                return {"page": page, "pagecount": 1, "limit": page_size, "total": 0, "list": []}
            start = (page - 1) * page_size
            part = base_list[start : start + page_size]
            return {
                "page": page,
                "pagecount": (total + page_size - 1) // page_size,
                "limit": page_size,
                "total": total,
                "list": [_to_vod(it) for it in part],
            }

        start = ((page - 1) * page_size) % total
        part = [all_items[(start + i) % total] for i in range(page_size)]
        return {
            "page": page,
            "pagecount": 99999,
            "limit": page_size,
            "total": 999999,
            "list": [_to_vod(it) for it in part],
        }
    except Exception as e:
        await OmniBox.log("error", f"[category] 失败: {e}")
        return {"list": [], "page": 1, "pagecount": 0, "total": 0, "limit": 24}


async def detail(params, context):
    try:
        vid = str((params or {}).get("videoId") or "")
        if not vid:
            return {"list": []}
        await OmniBox.log("info", f"[detail] videoId={vid}")
        parts = vid.split("|")
        play_id = parts[0]
        user_id = parts[1] if len(parts) > 1 else play_id.split("_")[0]
        title = parts[2] if len(parts) > 2 else user_id
        vod = {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": "",
            "vod_remarks": "PandaLive",
            "vod_content": title,
            "vod_play_sources": [
                {"name": "IVS", "episodes": [{"name": "直播", "playId": vid}]}
            ],
        }
        return {"list": [vod]}
    except Exception as e:
        await OmniBox.log("error", f"[detail] 失败: {e}")
        return {"list": []}


async def search(params, context):
    try:
        key = str((params or {}).get("keyword") or (params or {}).get("wd") or "").strip()
        if not key:
            return {"list": [], "page": 1, "pagecount": 0, "total": 0, "limit": 0}
        await OmniBox.log("info", f"[search] keyword={key}")
        items = (await _list_live()).get("list", [])
        key_l = key.lower()
        result = []
        for it in items:
            title = str(it.get("title", ""))
            user_id = str(it.get("userId", ""))
            user_nick = str(it.get("userNick", ""))
            if key_l in title.lower() or key_l in user_id.lower() or key_l in user_nick.lower():
                result.append(_to_vod(it))
        return {"list": result, "page": 1, "pagecount": 1, "limit": len(result), "total": len(result)}
    except Exception as e:
        await OmniBox.log("error", f"[search] 失败: {e}")
        return {"list": [], "page": 1, "pagecount": 0, "total": 0, "limit": 0}


async def play(params, context):
    try:
        vid = str((params or {}).get("playId") or "").strip()
        flag = str((params or {}).get("flag") or "play")
        if not vid:
            raise ValueError("playId 为空")
        await OmniBox.log("info", f"[play] playId={vid}")
        parts = vid.split("|")
        play_id = parts[0]
        j = await _live_play(play_id)
        m3u8 = _find_first_m3u8(j) if isinstance(j, dict) else ""
        headers = {"User-Agent": UA, "Referer": BASE + "/", "Origin": BASE}
        if m3u8:
            return {
                "urls": [{"name": "直播", "url": m3u8}],
                "flag": flag,
                "header": headers,
                "parse": 0,
            }
        fallback = f"{BASE}/play/{play_id.split('_')[0]}"
        return {
            "urls": [{"name": "直播", "url": fallback}],
            "flag": flag,
            "header": headers,
            "parse": 1,
        }
    except Exception as e:
        await OmniBox.log("error", f"[play] 失败: {e}")
        return {
            "urls": [],
            "flag": (params or {}).get("flag", "play"),
            "header": {},
            "parse": 0,
        }


if __name__ == "__main__":
    run(
        {
            "home": home,
            "category": category,
            "detail": detail,
            "search": search,
            "play": play,
        }
    )
