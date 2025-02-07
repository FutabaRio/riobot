from typing import Dict, List
from nonebot.adapters.onebot.v11 import MessageEvent

class ChatContextManager:
    def __init__(self, max_length: int = 10):
        # 数据结构：{会话ID: 消息历史}
        self.contexts: Dict[str, List[dict]] = {}
        self.max_length = max_length

    def _get_session_id(self, event: MessageEvent) -> str:
        """生成唯一的会话ID（群聊用群号，私聊用用户ID）"""
        if event.message_type == "group":
            return f"group_{event.group_id}"
        return f"private_{event.user_id}"

    def get_history(self, event: MessageEvent) -> List[dict]:
        session_id = self._get_session_id(event)
        return self.contexts.get(session_id, [])

    def add_message(self, event: MessageEvent, role: str, content: str):
        session_id = self._get_session_id(event)
        if session_id not in self.contexts:
            self.contexts[session_id] = []
    
    # # 添加消息时自动清理连续重复角色（可选）
    #     if self.contexts[session_id] and self.contexts[session_id][-1]["role"] == role:
    #         self.contexts[session_id].pop()
        
        self.contexts[session_id].append({"role": role, "content": content})
    
    # 保持长度（保留最后10条）
        self.contexts[session_id] = self.contexts[session_id][-self.max_length:]

    def clear_history(self, event: MessageEvent):
        session_id = self._get_session_id(event)
        if session_id in self.contexts:
            self.contexts[session_id] = []

# 全局上下文管理器
context_manager = ChatContextManager(max_length=10)