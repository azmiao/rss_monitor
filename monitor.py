import os
from datetime import datetime, timezone

from rocksdict import Rdict

from yuiChyan import base_db_path, CQEvent, YuiChyan, FunctionException, get_bot
from yuiChyan.config import PROXY
from yuiChyan.service import Service
from yuiChyan.util import RSSParser, parse_datetime, FeedEntry
from yuiChyan.util.date_utils import format_datetime

sv = Service('rss_monitor')


async def get_database() -> Rdict:
    """
    监控信息数据库
    """
    rss_monitor_db = Rdict(os.path.join(base_db_path, 'rss_monitor.db'))
    return rss_monitor_db


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


@sv.scheduled_job(minute='*/10')
async def monitor_schedule():
    bot = get_bot()
    rss_monitor_db = await get_database()
    for group_id in rss_monitor_db.keys():
        group_data: dict = rss_monitor_db.get(group_id, {})
        for user_id, rss_dict in group_data.items():
            # 第一次订阅后old_time_str为None
            for rss_url, old_time_str in rss_dict.items():
                try:
                    # 检测 RSS 是否有更新
                    new_time_str, new_entries = await check_rss(rss_url, old_time_str)
                    # 有更新
                    if new_entries:
                        # 更新数据库里的更新时间
                        rss_dict[rss_url] = new_time_str
                        group_data[user_id] = rss_dict
                        rss_monitor_db[group_id] = group_data
                        format_msg = format_entries_message(new_entries)
                        msg = f'[CQ:at,qq={user_id}]您订阅的RSS有更新：\n{format_msg}'
                        await bot.send_group_msg(group_id=group_id, message=msg)
                except Exception as e:
                    print(f"[ERROR] 监控 RSS {rss_url} 失败: {str(e)}")
    rss_monitor_db.close()


async def check_rss(rss_url: str, old_time_str: str | None) -> tuple[str | None, list[FeedEntry]]:
    """
    检测 RSS 是否有新内容
    :param rss_url: RSS 链接
    :param old_time_str: 数据库中记录的上次更新时间（可能是 None）
    :return: (新的更新时间, 新的条目列表)
    """
    parser = RSSParser(rss_url, PROXY)
    feed = parser.parse_feed()

    if not feed.entries:
        return old_time_str, []

    # 按照时间从新到旧排序
    feed.entries.sort(reverse=True)

    new_entries: list[FeedEntry]
    if old_time_str is None:
        # 第一次订阅，返回全部
        new_entries = feed.entries
    else:
        # 后续只返回新的
        old_time = parse_datetime(old_time_str) or datetime.min.replace(tzinfo=timezone.utc)
        new_entries = [e for e in feed.entries if e.update_time > old_time]

    return new_entries[0].update_time_str if new_entries else old_time_str, new_entries


def format_entries_message(entries: list[FeedEntry], limit: int = 5):
    msgs = []
    total = len(entries)
    for e in entries[:limit]:
        msgs.append(f"📢 {e.title}\n🔗 {e.link}\n🕒 {format_datetime(e.update_time)}")
    if total > limit:
        msgs.append(f"> 另外还有 {total - limit} 条新内容未显示")
    return "\n\n".join(msgs)
