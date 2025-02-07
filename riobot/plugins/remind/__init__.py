import hashlib
import os
import re
import time
from typing import Dict, List, Union
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from nonebot import get_bot, get_driver, on_command, on_regex
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageEvent,
    MessageSegment,
    GroupMessageEvent
)
from nonebot.params import CommandArg, RegexGroup
from nonebot.rule import to_me
from nonebot.plugin import PluginMetadata

__version__ = "0.2.0"
__plugin_meta__ = PluginMetadata(
    name="定时提醒",
    description="群组定时提醒插件",
    usage="查看详细使用说明",
    supported_adapters={"~onebot.v11"},
)

# 初始化核心组件
driver = get_driver()
current_dir = os.getcwd()
db_path = os.path.join(current_dir, 'jobs.sqlite')

# 定时任务配置
jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')}
scheduler = AsyncIOScheduler(jobstores=jobstores)

# 数据存储
group_settings: Dict[int, bool] = {}
reminder_jobs: Dict[str, dict] = {}

# ================
# 工具函数
# ================


def generate_job_id(group_id: int, hour: int, minute: int, content: str) -> str:
    """生成唯一任务ID"""
    timestamp_ns = time.time_ns()
    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"rem_{group_id}_{hour:02}{minute:02}_{content_hash}_{timestamp_ns}"


def parse_at_targets(message: str) -> List[str]:
    targets = re.findall(r'\[CQ:at,qq=(\d+)\]', message)
    # 处理@全体成员
    if '[CQ:at,qq=all]' or '全体' in message:
        targets.append('all')
    return targets


def build_response_message(targets: List[str], time_str: str, content: str, job_id: str) -> Message:
    """构建响应消息"""
    msg = Message()
    msg += MessageSegment.text(f"⏰ 时间:{time_str}\n")
    msg += MessageSegment.text(f"📝 内容:{content}\n")
    if targets:
        msg += MessageSegment.text("👥 对象:")
        if 'all' in targets:
            msg += MessageSegment.at("all")
        else:
            for uid in targets:
                msg += MessageSegment.at(uid)
        msg += "\n"
    msg += MessageSegment.text(f"🔖 ID:{job_id}")
    return msg


# ================
# 命令处理器
# ================
group_manage = on_command("群提醒", priority=5, block=True)


@group_manage.handle()
async def handle_group_manage(event: GroupMessageEvent, args: Message = CommandArg()):
    """群提醒功能开关管理"""
    group_id = event.group_id
    cmd = args.extract_plain_text().strip().lower()

    # 初始化群组状态
    if group_id not in group_settings:
        group_settings[group_id] = True

    # 权限验证
    if event.sender.role not in ["admin", "owner"] and not await SUPERUSER():
        await group_manage.finish("❌ 需要管理员权限")

    # 处理命令
    if cmd == "开启":
        group_settings[group_id] = True
        await group_manage.finish("✅ 已开启本群提醒功能")
    elif cmd == "关闭":
        group_settings[group_id] = False
        await group_manage.finish("🛑 已关闭本群提醒功能")
    else:
        status = "开启" if group_settings[group_id] else "关闭"
        await group_manage.finish(f"当前群提醒状态:{status}\n使用格式:群提醒 [开启/关闭]")
# ================
# 提醒设置功能
# ================
reminder_set = on_command("设置提醒", aliases={"add"}, rule=to_me(), priority=5)


@reminder_set.handle()
async def handle_reminder_set(bot: Bot, event: Union[MessageEvent, GroupMessageEvent], args: Message = CommandArg()):
    try:
        raw_msg = str(args)

        # 解析时间
        time_match = re.search(r'(\d{1,2})[:时h](\d{1,2})分?', raw_msg)
        if not time_match:
            raise ValueError("❌ 时间格式错误!正确格式:时:分")

        hour, minute = map(int, time_match.groups())
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError("❌ 时间范围错误(00:00-23:59)")

        # 解析目标和内容
        targets = parse_at_targets(raw_msg)
        content = re.sub(r'\[CQ:at,qq=\d+\]|\[CQ:at,qq=all\]', '', raw_msg).strip()
        if not content:
            raise ValueError("❌ 提醒内容不能为空")

        # 群聊特殊处理
        if isinstance(event, GroupMessageEvent):
            group_id = event.group_id
            if not group_settings.get(group_id, True):
                raise ValueError("❌ 本群提醒功能未启用")

            # 生成唯一任务ID
            job_id = generate_job_id(group_id, hour, minute, content)

            # 添加任务到调度器
            try:
                scheduler.add_job(
                    send_reminder,
                    'cron',
                    hour=hour,
                    minute=minute,
                    args=(job_id,),
                    id=job_id,
                    replace_existing=True,
                    kwargs={  # 新增此行
                        "targets": targets,
                        "content": content,
                        "creator": event.user_id,
                        "group_id": group_id,
                        "time": f"{hour:02}:{minute:02}"
                    }
                )
            except Exception:
                new_id = f"{job_id}_{hash(os.urandom(4))}"
                scheduler.add_job(
                    send_reminder,
                    'cron',
                    hour=hour,
                    minute=minute,
                    args=(new_id,),
                    id=new_id
                )
                job_id = new_id

            # 存储任务信息
            reminder_jobs[job_id] = {
                "type": "group",
                "group_id": group_id,
                "targets": targets,
                "content": content,
                "time": f"{hour:02}:{minute:02}",
                "creator": event.user_id
            }

            # 构建响应
            response = build_response_message(
                targets=targets,
                time_str=f"{hour:02}:{minute:02}",
                content=content,
                job_id=job_id
            )
            await reminder_set.finish(response)

    except ValueError as e:
        await reminder_set.finish(str(e))
# ================
# 提醒发送逻辑
# ================


async def send_reminder(job_id: str):
    """执行提醒发送"""
    if job_id not in reminder_jobs:
        return

    job = reminder_jobs[job_id]
    bot = get_bot()
    try:
        if job["type"] == "group":
            msg = Message()
            msg += MessageSegment.text("🔔 定时提醒\n")
            msg += MessageSegment.text(f"⏰ 时间:{job['time']}\n")
            msg += MessageSegment.text(f"📝 内容:{job['content']}\n")

            if job["targets"]:
                msg += MessageSegment.text("👥 对象:")
                if 'all' in job["targets"]:
                    msg += MessageSegment.at("all")
                else:
                    for uid in job["targets"]:
                        msg += MessageSegment.at(uid)
                msg += "\n"

            await bot.send_group_msg(
                group_id=job["group_id"],
                message=msg
            )

        else:  # 私聊提醒
            await bot.send_private_msg(
                user_id=job["user_id"],
                message=Message(
                    MessageSegment.text("🔔 私人提醒\n") +
                    MessageSegment.text(f"⏰ 时间:{job['time']}\n") +
                    MessageSegment.text(f"📝 内容:{job['content']}")
                )
            )

    except Exception as e:
        print(f"⚠️ 提醒发送失败 [{job_id}]: {str(e)}")
# ================
# 生命周期管理
# ================


@driver.on_startup
async def startup():
    """启动时初始化"""
    scheduler.start()
    print("✅ 定时任务系统已启动")
    print(f"✅ 已加载 {len(scheduler.get_jobs())} 个定时任务")  # 添加任务数量提示
    # 加载已有任务
    for job in scheduler.get_jobs():
        if job.id.startswith('rem_'):
            try:
                _, gid, time_part, _, _ = job.id.split('_', 4)
                reminder_jobs[job.id] = {
                    "type": "group",
                    "group_id": int(gid),
                    "targets": job.kwargs.get('targets', []),
                    "content": job.kwargs.get('content', ''),
                    "time": f"{time_part[:2]}:{time_part[2:4]}",
                    "creator": job.kwargs.get('creator', 0)
                }
            except Exception as e:
                print(f"⚠️ 加载任务失败 [{job.id}]: {str(e)}")


@driver.on_shutdown
async def shutdown():
    """关闭时清理"""
    scheduler.shutdown()
    print("🛑 定时任务系统已关闭")

# ================
# 查看提醒列表功能
# ================
reminder_list = on_command("查看提醒", aliases={"list"}, priority=5, block=True)

@reminder_list.handle()
async def handle_reminder_list(event: GroupMessageEvent):
    """查看当前群组所有定时提醒"""
    group_id = event.group_id
    task_list = [
        key for key in reminder_jobs.keys() 
        if reminder_jobs[key]["type"] == "group" and reminder_jobs[key]["group_id"] == group_id
    ]
    print(f"reminder_jobs:{reminder_jobs}")
    if not task_list:
        await reminder_list.finish("⭕ 当前群组没有定时提醒任务")
    print(f"task_list:{task_list}")
    msg = Message()
    msg += MessageSegment.text("📜 当前生效的定时提醒:\n")
    for idx, key in enumerate(task_list, 1):
        msg += MessageSegment.text(f"{idx}.{key}")
        msg += MessageSegment.text(f"创建者: {reminder_jobs[key]["creator"]}\n\n")

    await reminder_list.finish(msg)

# ================
# 移除提醒功能
# ================
reminder_remove = on_command("移除提醒", aliases={"del"}, priority=5, block=True)

@reminder_remove.handle()
async def handle_reminder_remove(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    """通过任务ID移除提醒"""
    job_id = args.extract_plain_text().strip()
    
    if not job_id:
        await reminder_remove.finish("❌ 请输入要移除的任务ID\n(可通过{查看提醒}获取ID)")

    # 验证任务存在性
    if job_id not in reminder_jobs:
        await reminder_remove.finish("❌ 未找到对应任务")

    job = reminder_jobs[job_id]
    
    # 权限验证(管理员或创建者)
    is_creator = event.user_id == job["creator"]
    is_admin = event.sender.role in ["admin", "owner"]
    if not (is_admin or is_creator or await SUPERUSER(bot, event)):
        await reminder_remove.finish("❌ 需要管理员权限或创建者身份")

    try:
        # 从调度器移除
        scheduler.remove_job(job_id)
        # 从内存移除
        del reminder_jobs[job_id]
        await reminder_remove.finish(f"✅ 已成功移除任务:\n{job['time']} {job_id}...")
    except Exception as e:
        await e

