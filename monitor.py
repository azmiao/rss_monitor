import datetime
import os
from typing import Optional

import feedparser
from rocksdict import Rdict

from yuiChyan import base_db_path, CQEvent, YuiChyan, FunctionException, get_bot
from yuiChyan.service import Service
from yuiChyan.util import RSSParser


sv = Service('rss_monitor')


@sv.on_prefix(('添加RSS订阅', '增加RSS订阅', '新增RSS订阅'))
async def add_rss_url(bot: YuiChyan, ev: CQEvent):
    rss_url = str(ev.message).strip()
    group_id = ev.group_id
    user_id = ev.user_id

    if not rss_url:
        raise FunctionException(ev, f'输入的RSS订阅URL为空')
    rss_monitor_db = await get_database()
    group_dict = rss_monitor_db.get(group_id, {})
    rss_dict = group_dict.get(user_id, {})
    if rss_url in rss_dict:
        raise FunctionException(ev, f'您已经订阅过该RSS了')
    # 更新时间为None
    rss_dict[rss_url] = None
    group_dict[user_id] = rss_dict
    rss_monitor_db[group_id] = group_dict
    rss_monitor_db.close()
    await bot.send(ev, f'已成功订阅：{rss_url}', at_sender=True)


@sv.on_match('查询RSS订阅')
async def query_rss_url_list(bot: YuiChyan, ev: CQEvent):
    group_id = ev.group_id
    user_id = ev.user_id
    rss_monitor_db = await get_database()
    rss_dict = rss_monitor_db.get(group_id, {}).get(user_id, {})
    if not rss_dict:
        raise FunctionException(ev, f'您还没有在本群订阅RSS呢')
    rss_url_list = list(rss_dict.keys())
    rss_monitor_db.close()
    await bot.send(ev, f'您已订阅如下RSS：\n{"\n".join(rss_url_list)}', at_sender=True)


@sv.on_prefix(('删除RSS订阅', '取消RSS订阅'))
async def add_rss_url(bot: YuiChyan, ev: CQEvent):
    rss_url = str(ev.message).strip()
    group_id = ev.group_id
    user_id = ev.user_id

    if not rss_url:
        raise FunctionException(ev, f'输入的RSS订阅URL为空')
    rss_monitor_db = await get_database()
    group_dict = rss_monitor_db.get(group_id, {})
    rss_dict = group_dict.get(user_id, {})
    if rss_url not in rss_dict:
        raise FunctionException(ev, f'您未订阅该RSS')
    rss_dict.pop(rss_url)
    group_dict[user_id] = rss_dict
    rss_monitor_db[group_id] = group_dict
    rss_monitor_db.close()
    await bot.send(ev, f'已成功删除订阅：{rss_url}', at_sender=True)


@sv.scheduled_job(minute='*/1')
async def monitor_schedule():
    bot = get_bot()
    rss_monitor_db = await get_database()
    for group_id in rss_monitor_db.keys():
        group_data: dict = rss_monitor_db.get(group_id, {})
        for user_id, rss_dict in group_data.items():
            # 第一次订阅后update_time为None
            for rss_url, update_time in rss_dict.items():
                # try:
                # 检测 RSS 是否有更新
                new_update_time, new_entries = await check_rss(rss_url, update_time)
                # 有更新
                if new_entries:
                    # 更新数据库里的更新时间
                    rss_dict[rss_url] = new_update_time
                    rss_monitor_db[group_id][user_id] = rss_dict
                    await bot.send_group_msg(group_id=group_id, message=format_entries_message(new_entries))
                # except Exception as e:
                #     print(f"[ERROR] 监控 RSS {rss_url} 失败: {e}")


async def get_database() -> Rdict:
    """
    监控信息数据库
    """
    rss_monitor_db = Rdict(os.path.join(base_db_path, 'rss_monitor.db'))
    return rss_monitor_db


async def check_rss(rss_url: str, update_time: Optional[str]):
    """
    检测 RSS 是否有新内容
    :param rss_url: RSS 链接
    :param update_time: 数据库中记录的上次更新时间（可能是 None）
    :return: (新的更新时间, 新的条目列表)
    """
    parser = RSSParser(rss_url)
    feed = parser.parse_feed()

    if not feed.entries:
        return update_time, []

    # 找出列表里最新的时间
    latest_time_dt = None
    latest_time_str = None
    for entry in feed.entries:
        entry_dt = parse_datetime(entry.published)
        sv.logger.info(entry.published)
        sv.logger.info(entry_dt)
        if entry_dt and (latest_time_dt is None or entry_dt > latest_time_dt):
            latest_time_dt = entry_dt
            latest_time_str = entry.published

    new_entries = []
    # 第一次订阅，返回全部
    if update_time is None:
        new_entries = feed.entries
    else:
        old_time_dt = parse_datetime(update_time)
        for entry in feed.entries:
            entry_dt = parse_datetime(entry.published)
            if entry_dt and entry_dt > old_time_dt:
                new_entries.append(entry)

    return latest_time_str, new_entries


def parse_datetime(dt_str: str) -> datetime.datetime | None:
    """解析 RSS 日期字符串，返回 datetime（UTC标准化）"""
    if not dt_str:
        return None

    # 优先用 ISO8601 格式解析，例如 2025-11-20T22:48:23+08:00
    try:
        return datetime.datetime.fromisoformat(dt_str)
    except ValueError:
        pass

    # 尝试 feedparser 的解析功能（支持 RFC822 等）
    try:
        parsed = feedparser.parse(dt_str)
        if hasattr(parsed, "updated_parsed") and parsed.updated_parsed:
            return datetime.datetime(*parsed.updated_parsed[:6])
    except Exception:
        pass

    return None


def format_entries_message(entries, limit: int = 5):
    msgs = []
    total = len(entries)
    for e in entries[:limit]:
        msgs.append(f"📢 {e.title}\n🔗 {e.link}\n🕒 {e.published}")
    if total > limit:
        msgs.append(f"…还有 {total - limit} 条新内容未显示")
    return "\n\n".join(msgs)
