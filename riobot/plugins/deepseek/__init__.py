from nonebot import on_command, on_message
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import (
    Message,
    MessageEvent,
)
from openai import AsyncOpenAI
from .utils.context import context_manager
from nonebot.rule import to_me

__version__ = "0.2.0"
__plugin_meta__ = PluginMetadata(
    name="deepseekAPi",
    description="deepseek",
    usage="查看详细使用说明",
    supported_adapters={"~onebot.v11"},
)
DEEPSEEK_API_KEY = "sk-93554d78e7b6416599802ed5fa5c2ff8"
# 配置 OpenAI 客户端
client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
)
# 创建消息处理器
chat = on_message(rule=to_me(), priority=10)
clear_cmd = on_command("clear", aliases={"清除历史"}, priority=1)

@chat.handle()
async def handle_chat(event: MessageEvent):
    # 获取历史记录
    history = context_manager.get_history(event)
    
    # 添加用户消息到上下文
    user_message = event.get_plaintext()
    context_manager.add_message(event, "user", user_message)

    try:
        # 调用 DeepSeek API
        response = await client.chat.completions.create(
            # model='deepseek-reasoner'
            model="deepseek-reasoner",
            messages=[
                {"role": "system", "content": "你是一个乐于助人的助手"},
                *history,
                {"role": "user", "content": user_message},
            ],
            stream=False,
            temperature=0.7,
        )

        # 处理回复
        reply = response.choices[0].message.content
        context_manager.add_message(event, "assistant", reply)
        await chat.finish(Message(reply))

    except Exception as e:
        await e

@clear_cmd.handle()
async def handle_clear(event: MessageEvent):
    context_manager.clear_history(event)
    await clear_cmd.finish("对话历史已清除！")