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
    rss_dict = rss_monitor_db.get(group_id, {}).get(user_id, {})
    # 更新时间为None
    rss_dict[rss_url] = None
    rss_monitor_db[group_id][user_id] = rss_dict
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
    rss_dict = rss_monitor_db.get(group_id, {}).get(user_id, {})
    if rss_url not in rss_dict:
        raise FunctionException(ev, f'您未订阅该RSS')
    rss_dict.pop(rss_url)
    rss_monitor_db[group_id][user_id] = rss_dict
    await bot.send(ev, f'已成功删除订阅：{rss_url}', at_sender=True)


@sv.scheduled_job(minute='*/1')
async def monitor_schedule():
    bot = get_bot()
    rss_monitor_db = await get_database()
    for group_id in rss_monitor_db:
        group_data: dict = rss_monitor_db.get(group_id, {})
        for user_id in group_data:
            rss_dict: dict = group_data.get(user_id, {})
            # 第一次订阅后update_time为None
            for rss_url, update_time in rss_dict.items():
                try:
                    # 检测 RSS 是否有更新
                    new_update_time, new_entries = await check_rss(rss_url, update_time)

                    if new_entries:  # 有更新
                        # 更新数据库里的更新时间
                        rss_dict[rss_url] = new_update_time
                        rss_monitor_db[group_id][user_id] = rss_dict
                        await bot.send(group_id=group_id, message=format_entries_message(new_entries))

                except Exception as e:
                    print(f"[ERROR] 监控 RSS {rss_url} 失败: {e}")


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

    new_entries = []
    latest_update_time = update_time

    for entry in feed.entries:
        entry_time = parse_datetime(entry.published)

        # 第一次订阅 || 有新内容
        if update_time is None or (entry_time and entry_time > parse_datetime(update_time)):
            new_entries.append(entry)
            # 同时更新最新时间
            if latest_update_time is None or (entry_time and entry_time > parse_datetime(latest_update_time)):
                latest_update_time = entry.published

    return latest_update_time, new_entries


def parse_datetime(dt_str: str) -> Optional[datetime.datetime]:
    """把 RSS 的时间字符串转换为 datetime"""
    try:
        return datetime.datetime(*feedparser.parse(dt_str).updated_parsed[:6])
    except Exception:
        try:
            return datetime.datetime.fromisoformat(dt_str)
        except Exception:
            return None


def format_entries_message(entries):
    """把新 RSS 条目格式化为可发送消息"""
    msgs = []
    for e in entries:
        msgs.append(f"📢 {e.title}\n🔗 {e.link}\n🕒 {e.published}")
    return "\n\n".join(msgs)
